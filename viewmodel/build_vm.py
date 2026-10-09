"""打包视图模型。

执行顺序刻意做成"先体检、再确认、后施工"：

1. 点开始 → 先统计产物目录，若已有文件就把冲突放进状态，由视图弹确认框；
2. 删除失败（文件被占用）单独记录一份阻塞详情，给出具体路径与处理建议；
3. 确认后交给打包服务跑完清理 → ``flet clean`` → ``flet build``；
4. 命令输出按固定间隔合并刷新成 ``console`` 状态。

控制台按固定间隔合并刷新：构建输出动辄上千行，每来一行就重渲染一次会把界面拖垮；
被截掉的部分在日志文件里有完整记录，控制台只负责"看得见正在发生什么"。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from models.dtos import BuildOutcome, BuildPlan, Project, Readiness, TreeStats
from models.enums import Tone
from service.build_service import BuildService
from viewmodel.base import ViewModel
from viewmodel.formatting import human_bytes

logger = logging.getLogger(__name__)

__all__ = [
    "BuildState",
    "BuildViewModel",
    "OutputConflict",
    "RemovalFailure",
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
class OutputConflict:
    """产物目录里已有文件：开跑之前需要用户确认是否删除。"""

    path: str
    files: int
    size: str
    top: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RemovalFailure:
    """产物目录删不掉（多半是文件被占用）。"""

    path: str
    reason: str
    blocked_path: str = ""
    remaining: int = 0


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
    conflict: OutputConflict | None = None
    failure: RemovalFailure | None = None
    #: 将要执行的步骤文本，与实际执行同源（由打包端口生成）
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
        plan = self._service.plan(project)
        self.update(
            selected_id=project.id,
            plan=plan,
            readiness=self._service.precheck(plan),
            steps=self._service.preview_steps(plan),
            outcome=None,
            conflict=None,
            failure=None,
            phase="",
            console="",
            console_lines=0,
            output_state=None,
        )
        self._buffer.clear()

    def select(self, project: Project) -> None:
        if self.state.running or project.id == self.state.selected_id:
            return
        logger.debug("打包页切换到项目「%s」", project.name)
        self._select(project)

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
        self.update(output_state=stats)

    # ------------------------------------------------------------------ 主流程
    def request_start(self) -> None:
        """点「开始打包」：先体检产物目录，再决定是直接构建还是先问用户。"""
        if not self.state.can_start:
            issue = self.state.readiness.issue
            if issue:
                self.notify(issue, Tone.DANGER)
            logger.debug("开始打包被忽略：can_start=%s", self.state.can_start)
            return
        self.update(conflict=None, failure=None, outcome=None, phase="检查产物目录…")
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

        self.update(output_state=stats)
        if stats.empty:
            await self._launch()
            return

        logger.info(
            "产物目录已有 %d 个文件（%s），等待确认删除：%s",
            stats.files,
            human_bytes(stats.bytes),
            plan.output,
        )
        self.update(
            phase="产物目录非空，等待确认…",
            conflict=OutputConflict(
                path=plan.output,
                files=stats.files,
                size=human_bytes(stats.bytes),
                top=stats.top,
            ),
        )

    def cancel_conflict(self) -> None:
        self.update(conflict=None, phase="")

    def confirm_remove(self) -> None:
        """确认删除已有产物后继续打包。"""
        self._run_task = asyncio.create_task(self._remove_then_build())

    def retry_remove(self) -> None:
        self.update(failure=None)
        self._run_task = asyncio.create_task(self._remove_then_build())

    async def _remove_then_build(self) -> None:
        plan = self.state.plan
        if plan is None:
            return
        self.update(phase="删除已有产物…")
        try:
            report = await self._service.purge(plan.output)
        except Exception as exc:
            logger.exception("删除产物目录异常：%s", plan.output)
            self.update(phase="")
            self.notify(f"删除失败：{exc}", Tone.DANGER)
            return

        if not report.ok:
            blocker = report.first_blocker
            logger.warning(
                "产物目录未能删净：%s（剩余 %d 个文件，首个阻塞 %s）",
                plan.output,
                report.remaining,
                blocker.path if blocker else "未知",
            )
            self.update(
                phase="",
                failure=RemovalFailure(
                    path=plan.output,
                    reason=blocker.reason if blocker else "目录仍然存在，可能被其他程序占用",
                    blocked_path=blocker.path if blocker else "",
                    remaining=report.remaining,
                ),
            )
            return

        self.update(output_state=await self._service.inspect(plan.output))
        await self._launch()

    async def _launch(self) -> None:
        plan = self.state.plan
        if plan is None:
            return
        self._buffer.clear()
        self.update(
            conflict=None,
            failure=None,
            outcome=None,
            running=True,
            phase="准备打包…",
            console="",
            console_lines=0,
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
