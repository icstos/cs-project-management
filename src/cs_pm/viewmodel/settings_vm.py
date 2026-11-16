"""设置页视图模型：打包参数的草稿、校验、预览与保存。

一次改动的完整链路
------------------
1. 用户在某个字段里敲字 → :meth:`SettingsViewModel.change` 只更新草稿文本；
2. 同一帧里重算两件**纯计算**的事：能不能保存（校验）与生效后的命令行
   （交给 :class:`~cs_pm.service.build_service.BuildService.plan_with` 推导）——
   于是"改一项参数、下面的命令跟着变"不需要用户先保存再看；
3. 点保存 → 深校验（这一次会去磁盘看模板目录是否存在）→ 落库 → 打包页重取参数。

草稿与"已保存值"分开存（``values`` / ``baseline``），所以界面能如实显示"未保存"，
也能算出"恢复默认"到底是回默认还是回上一次保存的版本。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from cs_pm.models.build_options import BUILD_OPTIONS
from cs_pm.models.dtos import Project
from cs_pm.models.enums import Tone
from cs_pm.service.build_service import BuildService
from cs_pm.service.settings_service import SettingsError, SettingsService
from cs_pm.viewmodel.base import PlatformAction, ViewModel
from cs_pm.viewmodel.build_vm import ToolInfo

logger = logging.getLogger(__name__)

__all__ = ["SettingsState", "SettingsViewModel"]

#: 字段 key → 界面标签（选目录时用作对话框标题）
_LABELS: dict[str, str] = {option.key: option.label for option in BUILD_OPTIONS}
#: 只读展示用的「示例项目文件夹名」占位
_SAMPLE_FOLDER = "<项目文件夹名>"


@dataclass(frozen=True, slots=True)
class SettingsState:
    """设置页的全部状态。"""

    #: 正在编辑的草稿（key → 文本）
    values: Mapping[str, str] = field(default_factory=dict)
    #: 上一次保存的值。与 ``values`` 不同即为"未保存"
    baseline: Mapping[str, str] = field(default_factory=dict)
    problems: tuple[str, ...] = ()
    saving: bool = False
    loaded: bool = False
    tool: ToolInfo | None = None
    projects: tuple[Project, ...] = ()
    #: 生效后会执行的命令（用第一个项目当样本推导）
    steps: tuple[str, ...] = ()
    #: 示例产物目录（``<根目录>/<项目文件夹名>``）
    sample: str = ""

    # ------------------------------------------------------------------ 派生
    @property
    def dirty(self) -> bool:
        """有没有未保存的改动。"""
        return dict(self.values) != dict(self.baseline)

    @property
    def can_save(self) -> bool:
        """能保存：有改动、没有校验问题、不在保存中。"""
        return self.dirty and not self.problems and not self.saving

    @property
    def changed_keys(self) -> tuple[str, ...]:
        """被改动过的字段（界面上给它们加一点提示）。"""
        return tuple(key for key, value in self.values.items() if self.baseline.get(key) != value)


class SettingsViewModel(ViewModel[SettingsState]):
    """设置页的状态与命令。"""

    def __init__(
        self,
        service: SettingsService,
        build: BuildService,
        *,
        on_saved: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(SettingsState())
        self._service = service
        self._build = build
        #: 保存成功后叫一声：打包页的计划与命令预览都基于参数包，得重取一遍
        self._on_saved = on_saved
        #: 正在等目录选择框回填的字段
        self._picking: str = ""

    # ------------------------------------------------------------------ 载入
    async def load(self) -> None:
        """首次进入设置页：把库里的值读成草稿。

        只在第一次调用时真正读取 —— 切到别的页签再切回来会重新挂载组件，
        每次都重读会把用户没保存的改动冲掉。
        """
        if self.state.loaded:
            return
        values = self._service.values()
        logger.debug("设置页载入 %d 项参数", len(values))
        self.update(values=values, baseline=values, loaded=True, **self._preview(values))

    def sync(self, *, projects: tuple[Project, ...]) -> None:
        """接收 App 下发的项目列表（只用于推导示例路径与命令）。"""
        if self.state.projects == projects:
            return
        # 新列表还没写进状态，必须显式传进去 —— 否则预览用的还是"没有项目"那一份
        self.update(projects=projects, **self._preview(self.state.values, projects))

    # ------------------------------------------------------------------ 编辑
    def change(self, key: str, raw: str) -> None:
        """某个字段的文本变了。"""
        if key not in self.state.values:
            return
        values = {**self.state.values, key: raw}
        self.update(values=values, **self._preview(values))

    def set_flag(self, key: str, enabled: bool) -> None:
        """开关类字段：界面上给的是布尔，库里存 ``"1"/"0"``。"""
        self.change(key, "1" if enabled else "0")

    def choose(self, key: str, value: str) -> None:
        """下拉框选定某一项。"""
        self.change(key, value)

    def restore_defaults(self) -> None:
        """把草稿换回默认值（还需点保存才落库）。"""
        values = self._service.default_values()
        self.update(values=values, **self._preview(values))
        self.notify("已填入默认值，点「保存」后生效", Tone.INFO)

    # ------------------------------------------------------------------ 目录选择
    def request_pick(self, key: str) -> None:
        """某个路径字段点了「浏览」：请视图弹系统目录选择框。"""
        self._picking = key
        self.ask_platform(PlatformAction.PICK_DIRECTORY, text=f"选择{_LABELS.get(key, '目录')}")

    def accept_directory(self, path: str) -> None:
        key, self._picking = self._picking, ""
        if not path or not key:
            return
        logger.debug("设置页选择目录（%s）：%s", key, path)
        self.change(key, path)

    # ------------------------------------------------------------------ 保存
    async def save(self) -> None:
        """保存草稿。校验问题直接顶到状态里，由视图显示在保存按钮旁边。"""
        if self.state.saving:
            return
        values = dict(self.state.values)
        logger.debug("请求保存设置：%d 项未保存", len(self.state.changed_keys))
        problems = self._service.problems(values, check_exists=True)
        if problems:
            self.update(problems=problems)
            self.notify(problems[0], Tone.DANGER)
            return

        self.update(saving=True)
        try:
            self._service.save(values)
        except SettingsError as exc:
            logger.warning("保存设置失败：%s", exc)
            self.update(saving=False)
            self.notify(str(exc), Tone.DANGER)
            return

        # 保存前归一过（去尾斜杠、去重、平台合法性），回读到的才是真正生效的值
        values = self._service.values()
        self.update(
            values=values,
            baseline=values,
            saving=False,
            **self._preview(values),
        )
        self.notify("设置已保存，下次打包生效")
        if self._on_saved is not None:
            self._on_saved()

    # ------------------------------------------------------------------ 工具
    async def probe_tool(self) -> None:
        """探测 flet CLI（设置页改完路径后可以立刻验证）。"""
        try:
            available, detail = await self._build.probe_tool()
        except Exception as exc:  # 探测失败不该让整页渲染不出来
            logger.exception("探测 flet CLI 失败")
            available, detail = False, str(exc)
        self.update(tool=ToolInfo(available, detail))

    async def open_output_root(self) -> None:
        """在文件管理器中打开当前草稿的发布根目录（不存在时提示，不硬闯）。"""
        root = self.state.values.get("output_root", "").strip()
        if not root:
            self.notify("还没有设置生成文件夹根目录", Tone.WARNING)
            return
        if not Path(root).is_dir():
            self.notify(f"目录还不存在，打包时会自动创建：{root}", Tone.WARNING)
            return
        await self.reveal(root)

    async def reveal(self, path: str) -> None:
        ok, reason = await self._build.reveal(path)
        if not ok:
            self.notify(reason, Tone.DANGER)

    # ------------------------------------------------------------------ 内部
    def _preview(
        self, values: Mapping[str, str], projects: tuple[Project, ...] | None = None
    ) -> dict[str, object]:
        """由草稿推导「校验问题 + 示例产物目录 + 命令预览」。

        三件都是纯计算（字符串与 dataclass 操作），每次敲键重算一遍也不会有
        明显代价；真正的执行仍然只在打包页发生。

        ``projects`` 显式传入：:meth:`sync` 要在"新列表还没写进状态"的那一刻
        就用它算预览。
        """
        if not values:
            return {"problems": (), "steps": (), "sample": ""}
        settings = self._service.settings_of(values)
        problems = self._service.problems(values)
        known = self.state.projects if projects is None else projects
        sample_project = known[0] if known else None
        if sample_project is None:
            return {
                "problems": problems,
                "steps": (),
                "sample": str(Path(settings.output_root) / _SAMPLE_FOLDER),
            }
        plan = self._build.plan_with(settings, sample_project)
        return {
            "problems": problems,
            "steps": self._build.preview_steps(plan),
            "sample": plan.output,
        }
