"""应用外壳视图模型：当前页签、全局项目列表、加载态与快捷键。

全局状态只在这里维护一份（项目列表、加载态、git 可用性），再由
:meth:`AppViewModel._publish` 下发给各页的视图模型；各页只上报意图，
不各自去读一遍台账 —— 这样列表页的改动能立刻反映到提交页与打包页。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from models.dtos import Project
from models.enums import Tone
from service.build_service import BuildService
from service.commit_service import CommitService
from service.project_service import ProjectService
from service.report_service import ReportService
from viewmodel.base import Shortcut, ViewModel
from viewmodel.build_vm import BuildViewModel
from viewmodel.commit_vm import CommitViewModel
from viewmodel.projects_vm import ProjectsViewModel
from viewmodel.reports_vm import ReportsViewModel

logger = logging.getLogger(__name__)

__all__ = ["AppState", "AppViewModel", "Tab"]


class Tab(StrEnum):
    """左侧导航的四个页面。"""

    PROJECTS = "projects"
    COMMIT = "commit"
    REPORTS = "reports"
    BUILD = "build"

    @property
    def label(self) -> str:
        match self:
            case Tab.COMMIT:
                return "提交"
            case Tab.REPORTS:
                return "统计"
            case Tab.BUILD:
                return "打包"
            case _:
                return "项目"


@dataclass(frozen=True, slots=True)
class AppState:
    """应用外壳的全部状态。"""

    tab: Tab = Tab.PROJECTS
    projects: tuple[Project, ...] = ()
    loading: bool = True
    progress: str = ""
    git_ready: bool = True
    refreshed_at: datetime | None = None

    # ------------------------------------------------------------------ 派生
    @property
    def dirty_files(self) -> int:
        return sum(project.changed_files for project in self.projects)

    @property
    def attention(self) -> int:
        return sum(1 for project in self.projects if project.warnings)


class AppViewModel(ViewModel[AppState]):
    """外壳状态与全局数据加载。"""

    def __init__(
        self,
        *,
        projects: ProjectService,
        commits: CommitService,
        reports: ReportService,
        build: BuildService,
    ) -> None:
        super().__init__(AppState())
        self._service = projects
        self.projects_vm = ProjectsViewModel(projects, on_changed=self.refresh)
        self.commit_vm = CommitViewModel(commits)
        self.reports_vm = ReportsViewModel(reports)
        self.build_vm = BuildViewModel(build)
        self._refresh_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------ 启动
    async def bootstrap(self) -> None:
        """首次进入界面：先确认 git 可用，再深探测一遍所有仓库。"""
        available = await self._service.git_available()
        self.update(git_ready=available)
        if not available:
            self.notify("未检测到 git 命令，仓库状态将无法刷新", Tone.WARNING)
        await self.refresh(deep=True)

    # ------------------------------------------------------------------ 数据
    async def refresh(self, deep: bool = False) -> None:
        """``deep=True`` 会真正调用 git 探测每个仓库，否则只读台账。"""
        logger.debug("刷新项目列表（deep=%s）", deep)
        self.update(loading=True, progress="正在探测仓库状态…" if deep else "")
        try:
            data = (
                await self._service.refresh_all(on_progress=self._report_progress)
                if deep
                else await self._service.list_projects()
            )
        except Exception as exc:  # 读库或探测整体失败：给出提示但保持界面可用
            logger.exception("刷新项目列表失败（deep=%s）", deep)
            self.update(loading=False, progress="")
            self.notify(f"刷新失败：{exc}", Tone.DANGER)
            return

        self.update(
            projects=tuple(data),
            loading=False,
            progress="",
            refreshed_at=datetime.now(),
        )
        self._publish()

    def request_refresh(self, *, deep: bool = True) -> None:
        """请后台刷新一次（快捷键与状态栏按钮共用）。"""
        self._refresh_task = asyncio.create_task(self.refresh(deep=deep))

    def _report_progress(self, done: int, total: int) -> None:
        self.update(progress=f"已探测 {done}/{total} 个仓库")

    def _publish(self) -> None:
        """把全局数据分发给各页的视图模型。"""
        state = self.state
        self.projects_vm.sync(projects=state.projects, busy=state.loading)
        self.commit_vm.sync(projects=state.projects)
        self.reports_vm.sync(projects=state.projects)
        self.build_vm.sync(projects=state.projects, busy=state.loading)

    # ------------------------------------------------------------------ 导航
    def select_tab(self, tab: Tab) -> None:
        if tab is not self.state.tab:
            logger.debug("切换到页签：%s", tab.label)
            self.update(tab=tab)

    def open_new_project(self) -> None:
        """Ctrl+N：回到项目页并打开新建表单。"""
        self.update(tab=Tab.PROJECTS)
        self.projects_vm.start_create()

    def on_shortcut(self, shortcut: Shortcut) -> None:
        """处理归一化后的键盘手势。未认识的手势直接忽略。"""
        key = shortcut.key.upper()
        if shortcut.ctrl:
            match key:
                case "1" | "NUMPAD1":
                    self.select_tab(Tab.PROJECTS)
                case "2" | "NUMPAD2":
                    self.select_tab(Tab.COMMIT)
                case "3" | "NUMPAD3":
                    self.select_tab(Tab.REPORTS)
                case "4" | "NUMPAD4":
                    self.select_tab(Tab.BUILD)
                case "N":
                    self.open_new_project()
                case "R":
                    self.request_refresh()
            return
        if key == "F5":
            self.request_refresh()
