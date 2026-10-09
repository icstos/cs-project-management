"""项目管理视图模型：搜索、筛选、排序与增删改。

视图把"用户干了什么"翻译成这里的命令，这里负责状态流转与业务调用，
再把结果放回不可变状态；视图只根据状态渲染，不做任何判断。

路径输入是本模块最讲究的一段，规则与理由写在
:meth:`ProjectsViewModel.change_path` / :meth:`ProjectsViewModel.commit_path`
的注释里：输入过程中的整理与输入完成后的整理必须分开，否则用户敲
``D:\\`` 时字符会当场被吃掉。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from models.dtos import Project
from models.enums import Permission, Tone
from service.project_service import ProjectService
from viewmodel.base import PlatformAction, ViewModel

logger = logging.getLogger(__name__)

__all__ = [
    "ProjectDraft",
    "ProjectFilter",
    "ProjectsState",
    "ProjectsViewModel",
    "SortKey",
]


class ProjectFilter(StrEnum):
    """列表筛选条件。"""

    ALL = "all"
    DIRTY = "dirty"
    ATTENTION = "attention"

    @property
    def label(self) -> str:
        match self:
            case ProjectFilter.DIRTY:
                return "有本地变更"
            case ProjectFilter.ATTENTION:
                return "需关注"
            case _:
                return "全部"


class SortKey(StrEnum):
    """列表排序方式。"""

    NAME = "name"
    UPDATED = "updated"
    DIRTY = "dirty"

    @property
    def label(self) -> str:
        match self:
            case SortKey.UPDATED:
                return "最近更新"
            case SortKey.DIRTY:
                return "待提交文件"
            case _:
                return "名称"


@dataclass(frozen=True, slots=True)
class ProjectDraft:
    """新增 / 编辑项目的表单草稿。"""

    project_id: int | None = None
    name: str = ""
    local_path: str = ""
    permission: Permission = Permission.PRIVATE
    #: 被核验的那份文本。核验在线程池里异步完成，用户可能已经接着改了输入框，
    #: 渲染时靠它判断结论是否还属于当前内容（不匹配就退回中性提示，连续输入不会闪出过期报错）
    checked_text: str = ""
    path_issue: str | None = None
    error: str | None = None
    saving: bool = False

    @property
    def is_edit(self) -> bool:
        return self.project_id is not None

    @property
    def can_save(self) -> bool:
        return bool(self.name.strip() and self.local_path.strip()) and not self.saving

    @classmethod
    def blank(cls) -> ProjectDraft:
        return cls()

    @classmethod
    def from_project(cls, project: Project) -> ProjectDraft:
        return cls(
            project_id=project.id,
            name=project.name,
            local_path=project.local_path,
            permission=project.permission,
        )

    def with_fields(self, **changes: object) -> ProjectDraft:
        return replace(self, **changes)


@dataclass(frozen=True, slots=True)
class ProjectsState:
    """项目管理页的全部状态。派生读数（``visible`` / ``counts``）都是纯计算。"""

    projects: tuple[Project, ...] = ()
    #: 全局加载态（由 App 下发）：列表可能已被清空重取
    busy: bool = False
    query: str = ""
    active_filter: ProjectFilter = ProjectFilter.ALL
    sort_key: SortKey = SortKey.NAME
    busy_project: int | None = None
    draft: ProjectDraft | None = None
    pending_delete: Project | None = None

    # ------------------------------------------------------------------ 派生
    @property
    def visible(self) -> tuple[Project, ...]:
        """过滤 + 排序后的列表。"""
        keyword = self.query.strip().casefold()
        selected = [p for p in self.projects if _matches(p, keyword, self.active_filter)]
        match self.sort_key:
            case SortKey.UPDATED:
                selected.sort(key=lambda p: p.updated_at, reverse=True)
            case SortKey.DIRTY:
                selected.sort(key=lambda p: (p.changed_files, p.name), reverse=True)
            case _:
                selected.sort(key=lambda p: p.name.casefold())
        return tuple(selected)

    @property
    def counts(self) -> dict[ProjectFilter, int]:
        """每个筛选条件下的项目数，用于标签上的角标。"""
        return {item: sum(1 for p in self.projects if _FILTERS[item](p)) for item in ProjectFilter}

    @property
    def filtered(self) -> bool:
        return bool(self.query) or self.active_filter is not ProjectFilter.ALL


def _matches(project: Project, keyword: str, active: ProjectFilter) -> bool:
    if (
        keyword
        and keyword not in project.name.casefold()
        and keyword not in project.local_path.casefold()
    ):
        return False
    return _FILTERS[active](project)


_FILTERS: dict[ProjectFilter, Callable[[Project], bool]] = {
    ProjectFilter.ALL: lambda _project: True,
    ProjectFilter.DIRTY: lambda project: project.has_local_changes,
    ProjectFilter.ATTENTION: lambda project: bool(project.warnings),
}


class ProjectsViewModel(ViewModel[ProjectsState]):
    """项目列表与项目表单的状态与命令。

    ``on_changed`` 由 App 注入：台账增删改之后，全局项目列表需要重新读取，
    但"全局"归 App 管，所以这里只负责叫一声，不去动别人的状态。
    """

    def __init__(
        self,
        service: ProjectService,
        *,
        on_changed: Callable[[], Awaitable[None]],
    ) -> None:
        super().__init__(ProjectsState())
        self._service = service
        self._on_changed = on_changed

    # ------------------------------------------------------------------ 同步
    def sync(self, *, projects: tuple[Project, ...], busy: bool) -> None:
        """接收 App 下发的全局数据。内容不变时什么也不做，避免多余重渲染。"""
        if self.state.projects == projects and self.state.busy == busy:
            return
        self.update(projects=projects, busy=busy)

    # ------------------------------------------------------------------ 筛选
    def set_query(self, text: str) -> None:
        self.update(query=text)

    def clear_query(self) -> None:
        self.update(query="")

    def set_filter(self, item: ProjectFilter) -> None:
        self.update(active_filter=item)

    def set_sort(self, item: SortKey) -> None:
        self.update(sort_key=item)

    # ------------------------------------------------------------------ 表单
    def start_create(self) -> None:
        self.update(draft=ProjectDraft.blank())

    def start_edit(self, project: Project) -> None:
        self.update(draft=ProjectDraft.from_project(project))

    def close_form(self) -> None:
        self.update(draft=None)

    def _patch_draft(self, **changes: object) -> None:
        draft = self.state.draft
        if draft is None:
            return
        self.update(draft=draft.with_fields(**changes))

    def change_name(self, name: str) -> None:
        self._patch_draft(name=name)

    def change_permission(self, permission: Permission) -> None:
        self._patch_draft(permission=permission)

    # ------------------------------------------------------------------ 路径输入
    def change_path(self, raw: str) -> None:
        """输入过程中：只整理"绝不可能是手输中间态"的粘贴痕迹。

        包裹引号、``file:`` 链接、换行都来自粘贴；正斜杠与尾部反斜杠则留给
        :meth:`commit_path`，否则用户敲到 ``D:\\`` 时字符会被当场吃掉。
        """
        text = (
            self._service.normalize_path(raw) if self._service.has_paste_marks(raw) else raw.strip()
        )
        changes: dict[str, object] = {"local_path": text}
        draft = self.state.draft
        # 新增项目时名称多半还空着，顺手用目录名补一个，省得对着路径再敲一遍；
        # 编辑项目时不动名称——改路径不等于想改名。
        if draft is not None and not draft.is_edit and not draft.name.strip():
            changes["name"] = self._service.suggest_name(text)
        self._patch_draft(**changes)

    def commit_path(self) -> None:
        """失焦 / 回车：把分隔符、盘符大小写、多余的反斜杠统一成本机写法。

        取值以草稿为准 —— blur 事件不携带文本，而 change 已经把最新值写进来了。
        """
        draft = self.state.draft
        if draft is None:
            return
        text = self._service.normalize_path(draft.local_path)
        if text and text != draft.local_path:
            self._patch_draft(local_path=text)

    def request_paste(self) -> None:
        """请视图去读剪贴板，结果通过 :meth:`accept_clipboard` 回来。"""
        self.ask_platform(PlatformAction.READ_CLIPBOARD_PATH)

    def accept_clipboard(self, candidates: Sequence[str]) -> None:
        """回填剪贴板内容：取第一个能整理成本机路径的候选。"""
        for item in candidates:
            text = self._service.normalize_path(item)
            if text:
                logger.debug("从剪贴板填入路径：%s", text)
                self._patch_draft(local_path=text, error=None)
                return
        self.notify("剪贴板里没有可用的路径", Tone.WARNING)

    def request_pick_directory(self) -> None:
        """请视图弹系统目录选择框。"""
        self.ask_platform(PlatformAction.PICK_DIRECTORY, text="选择 Git 仓库目录")

    def accept_directory(self, path: str) -> None:
        if not path:
            return
        logger.debug("浏览选择目录：%s", path)
        self._patch_draft(local_path=self._service.normalize_path(path), error=None)

    async def verify_path(self, raw: str) -> None:
        """核验路径是不是可用的 Git 仓库；结论连文本一起记，避免过期结论误导用户。"""
        text = raw.strip()
        if not text:
            return
        issue = await self._service.check_path(text)
        draft = self.state.draft
        if draft is None or draft.local_path.strip() != text:
            return  # 用户已经接着改了输入框，这条结论作废
        self._patch_draft(checked_text=text, path_issue=issue)

    # ------------------------------------------------------------------ 保存
    async def save(self) -> None:
        draft = self.state.draft
        if draft is None or not draft.can_save:
            return
        self._patch_draft(saving=True, error=None)
        logger.debug("保存项目（%s）：%s", "编辑" if draft.is_edit else "新增", draft.local_path)
        try:
            if draft.is_edit:
                await self._service.update(
                    draft.project_id,
                    name=draft.name,
                    local_path=draft.local_path,
                    permission=draft.permission,
                )
                self.notify("项目已更新")
            else:
                await self._service.create(
                    name=draft.name,
                    local_path=draft.local_path,
                    permission=draft.permission,
                )
                self.notify("项目已添加")
        except (ValueError, RuntimeError) as exc:
            logger.warning(
                "保存项目失败（%s，路径=%r）：%s",
                "编辑" if draft.is_edit else "新增",
                draft.local_path,
                exc,
            )
            self._patch_draft(error=str(exc), saving=False)
            return
        self.update(draft=None)
        await self._refresh_all()

    # ------------------------------------------------------------------ 删除
    def ask_delete(self, project: Project) -> None:
        self.update(pending_delete=project)

    def cancel_delete(self) -> None:
        self.update(pending_delete=None)

    async def confirm_delete(self) -> None:
        project = self.state.pending_delete
        if project is None:
            return
        self.update(pending_delete=None)
        try:
            await self._service.delete(project.id)
            self.notify(f"已移除「{project.name}」")
        except (ValueError, RuntimeError) as exc:
            logger.warning("删除项目失败（#%d「%s」）：%s", project.id, project.name, exc)
            self.notify(str(exc), Tone.DANGER)
            return
        await self._refresh_all()

    # ------------------------------------------------------------------ 单项操作
    async def refresh_one(self, project: Project) -> None:
        self.update(busy_project=project.id)
        try:
            logger.debug("重新探测项目「%s」（%s）", project.name, project.local_path)
            await self._service.refresh(project.id)
        except (ValueError, RuntimeError) as exc:
            logger.warning("重新探测项目「%s」失败：%s", project.name, exc)
            self.notify(str(exc), Tone.DANGER)
        finally:
            self.update(busy_project=None)
        await self._refresh_all()

    async def reveal(self, project: Project) -> None:
        ok, reason = await self._service.reveal(project.local_path)
        if not ok:
            self.notify(reason, Tone.DANGER)

    def request_copy_path(self, project: Project) -> None:
        """请视图把路径写进剪贴板。"""
        self.ask_platform(PlatformAction.COPY_TEXT, text=project.local_path)

    def clipboard_written(self, error: str | None) -> None:
        if error:
            logger.warning("复制路径到剪贴板失败：%s", error)
            self.notify(f"复制失败：{error}", Tone.DANGER)
            return
        self.notify("路径已复制到剪贴板", Tone.INFO)

    # ------------------------------------------------------------------ 内部
    async def _refresh_all(self) -> None:
        """保存 / 删除后请 App 重新读取台账：视图模型不持有业务数据的真相，服务才是。"""
        await self._on_changed()
