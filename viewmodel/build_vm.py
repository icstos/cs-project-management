"""打包视图模型。

执行顺序刻意做成"先体检、再腾位置、后施工"：

1. 点开始 → 先统计产物目录；非空就把整个目录移入同级的「历史版本」文件夹
   （名字追加 ``-before-年-月-日_时-分-秒``），搬去哪了同时写进控制台与日志。
   移动不丢数据，所以不需要先问一句；
2. 移不动（目录里的程序还在运行）时停在原地，弹框给出原因与重试；
3. 交给打包服务跑完清理 → ``flet clean`` → ``flet build``
   （页面上的「清理 build 目录」开关关掉时，前两步跳过，直接增量构建）；
4. 命令输出按固定间隔合并刷新成 ``console`` 状态。

控制台按固定间隔合并刷新：构建输出动辄上千行，每来一行就重渲染一次会把界面拖垮；
被截掉的部分在日志文件里有完整记录，控制台只负责"看得见正在发生什么"。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field, replace

from models.dtos import ArchiveReport, BuildOutcome, BuildPlan, Project, Readiness, TreeStats
from models.enums import Tone
from service.build_service import BuildService
from viewmodel.base import ViewModel
from viewmodel.formatting import human_bytes

logger = logging.getLogger(__name__)

__all__ = [
    "ArchiveFailure",
    "BuildState",
    "BuildViewModel",
    "ToolInfo",
]

#: 控制台保留的行数。再多就开始拖慢重绘，完整输出以日志文件为准。
CONSOLE_KEEP = 250
#: 输出合并刷新的间隔（秒）
FLUSH_SECONDS = 0.4


@dataclass(frozen=True, slots=True)
class ToolInfo:
    """外部打包工具（flet CLI）的探测结果。"""

    available: bool
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ArchiveFailure:
    """旧产物移不进历史版本（多半是目录里的程序还在运行）。"""

    path: str
    target: str = ""
    reason: str = ""


@dataclass(frozen=True, slots=True)
class BuildState:
    """打包页的全部状态。"""

    projects: tuple[Project, ...] = ()
    #: 全局加载态（由 App 下发）
    busy: bool = False
    selected_id: int | None = None
    plan: BuildPlan | None = None
    readiness: Readiness = field(default_factory=Readiness)
    tool: ToolInfo | None = None
    output_state: TreeStats | None = None
    phase: str = ""
    console: str = ""
    console_lines: int = 0
    running: bool = False
    outcome: BuildOutcome | None = None
    failure: ArchiveFailure | None = None
    #: 本次打包前是哪一个旧版本被移入了历史版本（空串表示这次没有旧产物）
    archived: str = ""
    #: 本轮是否先清理源目录的 ``build``（打包页开关，默认开；不进设置页的持久化参数）
    clean_build: bool = True
    #: 将要执行的步骤文本，与实际执行同源（打包端口 + 产物非空时的存档步骤）
    steps: tuple[str, ...] = ()

    # ------------------------------------------------------------------ 派生
    @property
    def selected(self) -> Project | None:
        return next((p for p in self.projects if p.id == self.selected_id), None)

    @property
    def tool_ready(self) -> bool:
        """工具还没探测完时按"可用"处理，避免按钮先灰后亮造成误判。"""
        return True if self.tool is None else self.tool.available

    @property
    def can_start(self) -> bool:
        return (
            self.plan is not None
            and self.readiness.ready
            and self.tool_ready
            and not self.running
            and not self.busy
        )

    @property
    def occupied(self) -> bool:
        return self.output_state is not None and not self.output_state.empty


class BuildViewModel(ViewModel[BuildState]):
    """打包页的状态与命令。"""

    def __init__(self, service: BuildService) -> None:
        super().__init__(BuildState())
        self._service = service
        #: 控制台行缓冲与合并刷新标志不能进状态：它们的每次变化都会触发重渲染，
        #: 正是要避免的事
        self._buffer: list[tuple[str, str]] = []
        self._flush_task: asyncio.Task[None] | None = None
        self._run_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------ 同步
    def sync(self, *, projects: tuple[Project, ...], busy: bool) -> None:
        if self.state.projects == projects and self.state.busy == busy:
            return
        self.update(projects=projects, busy=busy)
        if not projects:
            self.update(selected_id=None, plan=None, readiness=Readiness())
            return
        if not any(project.id == self.state.selected_id for project in projects):
            self._select(projects[0])

    def output_name(self, project: Project) -> str:
        """该项目会产出到哪个目录名（= 源目录名）。"""
        return self._service.plan(project).output_name

    # ------------------------------------------------------------------ 选择
    def _select(self, project: Project) -> None:
        plan = self._service.plan(project, clean_build=self.state.clean_build)
        # 换项目时产物目录还没统计，"是否要先存旧版本"未知，先按不存算
        self.update(
            selected_id=project.id,
            plan=plan,
            readiness=self._service.precheck(plan),
            steps=self._service.preview_steps(plan),
            outcome=None,
            failure=None,
            archived="",
            phase="",
            console="",
            console_lines=0,
            output_state=None,
        )
        self._buffer.clear()

    def _steps(self, plan: BuildPlan, stats: TreeStats | None) -> tuple[str, ...]:
        """按产物目录的现状给出步骤：非空时第一步是"移入历史版本"。

        ``stats`` 为 ``None`` 表示还没统计过 —— 这时不承诺那一步，等
        :meth:`load_output` 拿到真实读数再补上，避免"预览里说要移动、
        实际没有旧产物"这种自相矛盾。
        """
        return self._service.preview_steps(plan, archive=stats is not None and not stats.empty)

    def select(self, project: Project) -> None:
        if self.state.running or project.id == self.state.selected_id:
            return
        logger.debug("打包页切换到项目「%s」", project.name)
        self._select(project)

    def refresh_plan(self) -> None:
        """按当前生效的设置重算计划与命令预览。

        设置页保存后由 App 调用：参数包变了，产物目录、传了哪些开关都会跟着变，
        页面上的命令必须立刻跟实际执行的一致。构建进行中不动 —— 正在跑的命令
        不能和"将要执行的步骤"打架。
        """
        project = self.state.selected
        if project is None or self.state.running:
            return
        plan = self._service.plan(project, clean_build=self.state.clean_build)
        if plan == self.state.plan:
            return
        logger.debug("打包参数已更新：%s → %s", plan.project_name, plan.output)
        self.update(
            plan=plan,
            readiness=self._service.precheck(plan),
            steps=self._steps(plan, self.state.output_state),
            failure=None,
        )

    # ------------------------------------------------------------------ 构建选项
    def set_clean_build(self, enabled: bool) -> None:
        """打包页的「清理 build 目录」开关：只影响本轮的步骤与执行。

        关掉后不只是少删一次：``flet clean`` 也一并跳过（它删的正是同一个
        ``build/``，留着它只会因为只读文件直接失败），于是变成增量构建。
        计划里带着这个标记，所以「将要执行的步骤」会同步少掉两条命令。
        """
        if self.state.running or enabled == self.state.clean_build:
            return
        logger.debug("打包前清理 build 目录：%s", "开" if enabled else "关")
        plan = self.state.plan
        if plan is None:
            self.update(clean_build=enabled)
            return
        plan = replace(plan, clean_build=enabled)
        self.update(
            clean_build=enabled,
            plan=plan,
            steps=self._steps(plan, self.state.output_state),
        )

    # ------------------------------------------------------------------ 探测
    async def probe_tool(self) -> None:
        try:
            available, detail = await self._service.probe_tool()
        except Exception as exc:  # 探测本身失败也不该让整页渲染不出来
            logger.exception("探测 flet CLI 失败")
            available, detail = False, str(exc)
        self.update(tool=ToolInfo(available, detail))

    async def load_output(self) -> None:
        plan = self.state.plan
        if plan is None:
            self.update(output_state=None)
            return
        try:
            stats = await self._service.inspect(plan.output)
        except Exception:
            logger.exception("统计产物目录失败：%s", plan.output)
            self.update(output_state=None)
            return
        self.update(output_state=stats, steps=self._steps(plan, stats))

    # ------------------------------------------------------------------ 主流程
    def request_start(self) -> None:
        """点「开始打包」：先看产物目录，有旧版本就先存起来再构建。"""
        if not self.state.can_start:
            issue = self.state.readiness.issue
            if issue:
                self.notify(issue, Tone.DANGER)
            logger.debug("开始打包被忽略：can_start=%s", self.state.can_start)
            return
        self.update(failure=None, outcome=None, archived="", phase="检查产物目录…")
        self._run_task = asyncio.create_task(self._inspect_then_start())

    async def _inspect_then_start(self) -> None:
        plan = self.state.plan
        if plan is None:
            return
        try:
            stats = await self._service.inspect(plan.output)
        except Exception as exc:
            logger.exception("统计产物目录失败：%s", plan.output)
            self.update(phase="")
            self.notify(f"无法读取产物目录：{exc}", Tone.DANGER)
            return

        self.update(output_state=stats, steps=self._steps(plan, stats))
        if stats.empty:
            await self._launch()
            return

        logger.info(
            "产物目录已有 %d 个文件（%s），先移入历史版本再打包：%s",
            stats.files,
            human_bytes(stats.bytes),
            plan.output,
        )
        await self._archive_then_build()

    async def _archive_then_build(self) -> None:
        """把已有产物整体移入历史版本，然后开跑。

        移动而不是删除：存档目录与产物目录同父级（同一个卷），改名即完成 ——
        不占额外空间，旧版本随时能翻回来。也正因为不丢数据，这里不再先问一句。
        """
        plan = self.state.plan
        if plan is None:
            return
        self.update(phase=f"移入历史版本：{plan.archive_target().name}")
        try:
            report = await self._service.archive(plan)
        except Exception as exc:
            logger.exception("移入历史版本时出现未预期异常：%s", plan.output)
            self.update(phase="")
            self.notify(f"移入历史版本失败：{exc}", Tone.DANGER)
            return

        if not report.ok:
            logger.error("旧产物移入历史版本失败：%s（%s）", report.source, report.reason)
            self.update(
                phase="",
                failure=ArchiveFailure(
                    path=report.source, target=report.target, reason=report.reason
                ),
            )
            return

        logger.info("旧产物已移入历史版本：%s", report.target)
        stats = await self._service.inspect(plan.output)
        self.update(output_state=stats, archived=report.target, steps=self._steps(plan, stats))
        await self._launch(archived=report)

    def retry_archive(self) -> None:
        """移动失败后重试（用户已经关掉占用目录的程序）。"""
        self.update(failure=None)
        self._run_task = asyncio.create_task(self._archive_then_build())

    def dismiss_failure(self) -> None:
        """关掉失败提示，保持产物目录原样，等用户自己处理。"""
        self.update(failure=None, phase="")

    async def _launch(self, archived: ArchiveReport | None = None) -> None:
        plan = self.state.plan
        if plan is None:
            return
        self._buffer.clear()
        if archived is not None and archived.ok:
            # 输出版本记录的第一行：上一次的产物搬去哪了，不用去翻日志才知道
            self._buffer.append(
                (
                    "out",
                    f"[历史版本] {archived.source} → {archived.target}"
                    f"（{archived.files} 个文件）",
                )
            )
        self.update(
            failure=None,
            outcome=None,
            running=True,
            phase="准备打包…",
            console=self._console_text() if self._buffer else "",
            console_lines=len(self._buffer),
        )
        try:
            result = await self._service.run(
                plan, on_line=self._append_line, on_phase=self._set_phase
            )
        except asyncio.CancelledError:
            # 是我们自己发起的终止，子进程已在基础设施层被杀掉，这里只做收尾
            logger.warning("打包被终止：%s", plan.source)
            result = BuildOutcome(
                ok=False, detail="已终止打包（构建进程已结束）", output=plan.output
            )
        except Exception as exc:
            logger.exception("打包过程中出现未预期异常（%s）", plan.source)
            result = BuildOutcome(ok=False, detail=f"打包异常：{exc}", output=plan.output)

        self.update(
            running=False,
            phase="",
            outcome=result,
            console=self._console_text(),
            console_lines=len(self._buffer),
        )
        self.notify(result.detail, Tone.SUCCESS if result.ok else Tone.DANGER)
        if result.ok:
            await self.load_output()

    def stop(self) -> None:
        """终止正在进行的构建。"""
        task = self._run_task
        if task is not None and not task.done():
            logger.info("用户请求终止打包")
            task.cancel()

    async def open_output_dir(self) -> None:
        """在文件管理器中打开发布根目录。"""
        await self.reveal(self._service.output_root())

    async def reveal(self, path: str) -> None:
        ok, reason = await self._service.reveal(path)
        if not ok:
            self.notify(reason, Tone.DANGER)

    # ------------------------------------------------------------------ 控制台
    def _console_text(self) -> str:
        if not self._buffer:
            return "（等待输出…）"
        return "\n".join(f"! {line}" if stream == "err" else line for stream, line in self._buffer)

    def _set_phase(self, text: str) -> None:
        self.update(phase=text)

    def _append_line(self, stream: str, line: str) -> None:
        self._buffer.append((stream, line))
        if len(self._buffer) > CONSOLE_KEEP:
            del self._buffer[: len(self._buffer) - CONSOLE_KEEP]
        # 合并刷新：一个刷新任务没结束就不再开新的，输出再密也只按固定节奏重渲染
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._flush_console())

    async def _flush_console(self) -> None:
        await asyncio.sleep(FLUSH_SECONDS)
        self.update(console=self._console_text(), console_lines=len(self._buffer))
