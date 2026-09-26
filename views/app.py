"""应用外壳：侧边导航、全局状态、快捷键与状态栏。

全局状态只在这里维护一份（项目列表、加载态、git 可用性），
各视图通过 props 获取数据、通过回调上报意图，避免多处重复请求。
"""

from __future__ import annotations

import logging
from datetime import datetime

import flet as ft

from core import theme as T
from core.config import APP_VERSION
from services.project_service import ProjectService
from views import ui
from views.commit_view import CommitView
from views.guard import guarded
from views.projects_view import ProjectsView
from views.reports_view import ReportsView

logger = logging.getLogger(__name__)

_NAV_ITEMS = (
    (ft.Icons.FOLDER_OUTLINED, ft.Icons.FOLDER, "项目"),
    (ft.Icons.COMMIT_OUTLINED, ft.Icons.COMMIT, "提交"),
    (ft.Icons.ANALYTICS_OUTLINED, ft.Icons.ANALYTICS, "统计"),
)
_SHORTCUT_HINT = "Ctrl+1/2/3 切换 · Ctrl+N 新建 · F5 刷新"


@guarded
def AppShell():
    page = ft.context.page
    # use_ref 只在首次渲染时构造一次，既避免重复创建，也保证服务实例不被回收
    service = ft.use_ref(ProjectService).current
    picker = ft.use_ref(ft.FilePicker).current

    tab_index, set_tab_index = ft.use_state(0)
    projects, set_projects = ft.use_state(list)
    loading, set_loading = ft.use_state(True)
    progress, set_progress = ft.use_state("")
    git_ready, set_git_ready = ft.use_state(True)
    refreshed_at, set_refreshed_at = ft.use_state(None)
    new_request, set_new_request = ft.use_state(0)

    # ------------------------------------------------------------------ 数据
    def report_progress(done: int, total: int) -> None:
        set_progress(f"已探测 {done}/{total} 个仓库")

    async def refresh(deep: bool = False) -> None:
        """``deep=True`` 会真正调用 git 探测每个仓库，否则只读数据库。"""
        set_loading(True)
        if deep:
            set_progress("正在探测仓库状态…")
        try:
            data = (
                await service.refresh_all(on_progress=report_progress)
                if deep
                else await service.list_projects()
            )
            set_projects(data)
            set_refreshed_at(datetime.now())
        except Exception as exc:
            logger.exception("刷新项目列表失败（deep=%s）", deep)
            ui.toast(page, f"刷新失败：{exc}", tone=T.Tone.DANGER)
        finally:
            set_progress("")
            set_loading(False)

    async def bootstrap() -> None:
        available = await service.git_available()
        set_git_ready(available)
        if not available:
            ui.toast(page, "未检测到 git 命令，仓库状态将无法刷新", tone=T.Tone.WARNING)
        await refresh(deep=True)

    ft.use_effect(bootstrap, [])

    # ------------------------------------------------------------------ 快捷键
    def open_new_project() -> None:
        set_tab_index(0)
        set_new_request(lambda current: current + 1)

    def handle_key(event: ft.KeyboardEvent) -> None:
        key = event.key.upper()
        match (event.ctrl, key):
            case (True, "1" | "NUMPAD1"):
                set_tab_index(0)
            case (True, "2" | "NUMPAD2"):
                set_tab_index(1)
            case (True, "3" | "NUMPAD3"):
                set_tab_index(2)
            case (True, "N"):
                open_new_project()
            case (True, "R") | (False, "F5"):
                page.run_task(refresh, True)
            case _:
                return

    def bind_shortcuts():
        page.on_keyboard_event = handle_key
        return lambda: setattr(page, "on_keyboard_event", None)

    ft.use_effect(bind_shortcuts, [])

    # ------------------------------------------------------------------ 视图
    match tab_index:
        case 1:
            current = CommitView(
                projects=projects,
                service=service,
                busy=loading,
                refresh=refresh,
            )
        case 2:
            current = ReportsView(
                projects=projects,
                service=service,
                picker=picker,
                busy=loading,
            )
        case _:
            current = ProjectsView(
                projects=projects,
                service=service,
                picker=picker,
                busy=loading,
                new_request=new_request,
                refresh=refresh,
            )

    return ft.Row(
        spacing=0,
        expand=True,
        controls=[
            _sidebar(tab_index, set_tab_index, refresh, loading),
            ui.divider(vertical=True),
            ft.Column(
                expand=True,
                spacing=0,
                controls=[
                    ft.Container(expand=True, content=current),
                    ui.divider(),
                    _status_bar(
                        git_ready=git_ready,
                        projects=projects,
                        loading=loading,
                        progress=progress,
                        refreshed_at=refreshed_at,
                        on_refresh=lambda _: page.run_task(refresh, True),
                    ),
                ],
            ),
        ],
    )


# --------------------------------------------------------------------------- 构件
def _sidebar(selected: int, on_change, refresh, loading: bool) -> ft.Container:
    destinations = [
        ft.NavigationRailDestination(icon=icon, selected_icon=selected_icon, label=label)
        for icon, selected_icon, label in _NAV_ITEMS
    ]

    brand = ft.Container(
        padding=ft.Padding.only(top=T.SPACE_LG, bottom=T.SPACE_SM),
        alignment=ft.Alignment.CENTER,
        content=ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=T.SPACE_XS,
            tight=True,
            controls=[
                ft.Container(
                    width=42,
                    height=42,
                    border_radius=T.RADIUS_MD,
                    bgcolor=ft.Colors.PRIMARY,
                    alignment=ft.Alignment.CENTER,
                    content=ft.Icon(ft.Icons.TERMINAL, color=ft.Colors.ON_PRIMARY, size=22),
                ),
                ft.Text("CS PM", size=11, weight=ft.FontWeight.W_700, color=T.MUTED_TEXT),
            ],
        ),
    )

    footer = ft.Container(
        padding=ft.Padding.only(bottom=T.SPACE_MD),
        alignment=ft.Alignment.CENTER,
        content=ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=T.SPACE_XS,
            tight=True,
            controls=[
                ft.IconButton(
                    icon=ft.Icons.SYNC,
                    tooltip="刷新全部仓库状态（F5）",
                    icon_size=20,
                    disabled=loading,
                    on_click=lambda _: ft.context.page.run_task(refresh, True),
                ),
                ft.Text(f"v{APP_VERSION}", size=10, color=T.MUTED_TEXT),
            ],
        ),
    )

    return ft.Container(
        bgcolor=T.SHELL_COLOR,
        content=ft.Column(
            expand=True,
            spacing=0,
            controls=[
                brand,
                ft.NavigationRail(
                    expand=True,
                    selected_index=selected,
                    min_width=T.SIDEBAR_WIDTH,
                    label_type=ft.NavigationRailLabelType.ALL,
                    use_indicator=True,
                    bgcolor=ft.Colors.TRANSPARENT,
                    destinations=destinations,
                    leading=None,
                    trailing=footer,
                    on_change=lambda e: on_change(e.control.selected_index),
                ),
            ],
        ),
    )


def _status_item(icon: str, text: str, *, tone: T.Tone = T.Tone.NEUTRAL) -> ft.Row:
    return ft.Row(
        spacing=T.SPACE_XS,
        tight=True,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.Icon(icon, size=14, color=T.tone_style(tone).accent),
            ft.Text(text, size=11, color=T.MUTED_TEXT),
        ],
    )


def _status_bar(
    *,
    git_ready: bool,
    projects: list,
    loading: bool,
    progress: str,
    refreshed_at: datetime | None,
    on_refresh,
) -> ft.Container:
    dirty = sum(project.changed_files for project in projects)
    warnings = sum(1 for project in projects if project.warnings)

    left = ft.Row(
        spacing=T.SPACE_LG,
        controls=[
            _status_item(
                ft.Icons.CHECK_CIRCLE_OUTLINE if git_ready else ft.Icons.ERROR_OUTLINE,
                "git 就绪" if git_ready else "未检测到 git",
                tone=T.Tone.SUCCESS if git_ready else T.Tone.DANGER,
            ),
            _status_item(ft.Icons.FOLDER_OUTLINED, f"{len(projects)} 个项目"),
            *(
                [_status_item(ft.Icons.FILE_PRESENT_OUTLINED, f"{dirty} 个待提交文件")]
                if dirty
                else []
            ),
            *(
                [
                    _status_item(
                        ft.Icons.WARNING_AMBER_ROUNDED,
                        f"{warnings} 项需关注",
                        tone=T.Tone.WARNING,
                    )
                ]
                if warnings
                else []
            ),
        ],
    )

    right = ft.Row(
        spacing=T.SPACE_MD,
        tight=True,
        controls=[
            ft.Text(
                progress or (f"更新于 {ui.format_relative(refreshed_at)}" if refreshed_at else ""),
                size=11,
                color=T.MUTED_TEXT,
            ),
            ui.key_hint(_SHORTCUT_HINT),
            ft.IconButton(
                icon=ft.Icons.REFRESH,
                tooltip="刷新全部",
                icon_size=17,
                disabled=loading,
                on_click=on_refresh,
            ),
        ],
    )

    return ft.Container(
        bgcolor=T.SHELL_COLOR,
        content=ft.Column(
            spacing=0,
            tight=True,
            controls=[
                ft.ProgressBar(visible=loading, height=2, border_radius=0),
                ft.Container(
                    padding=ft.Padding.symmetric(horizontal=T.SPACE_LG, vertical=T.SPACE_XS),
                    content=ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Container(expand=True, content=left),
                            right,
                        ],
                    ),
                ),
            ],
        ),
    )


@ft.component
def App():
    return ft.SafeArea(expand=True, content=AppShell())
