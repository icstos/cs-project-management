"""应用外壳：侧边导航、全局状态栏与快捷键。

外壳只做一件事：**把状态翻译成布局**。当前页签、全局进度、状态栏统计全部来自
:class:`~viewmodel.app_vm.AppState`，任何点击都只调用视图模型的方法，视图本身
不保存任何数据，也不判断业务规则。

平台能力（剪贴板、文件选择器）是**页面级服务**，构造即注册到 page，重复构造会
注册多份，所以在这里用 ``use_ref`` 各创建一次，交给 :class:`FletPlatform` 统一
分派；四个子页共享这同一套。

唯一一处"视图自己的状态"是明暗模式：它属于展示偏好而非业务数据，因此放在
``use_state`` 里，不污染视图模型。切换时先把 :func:`view.design.set_dark` 同步给
令牌层，再让组件重渲染 —— 两次渲染之间整棵树取到的是同一套色板。
"""

from __future__ import annotations

import flet as ft

from models.enums import Tone
from models.settings import APP_VERSION
from view import design as T
from view import widgets
from view.build import BuildView
from view.commit import CommitView
from view.guard import guarded
from view.projects import ProjectsView
from view.reports import ReportsView
from view.view_platform import FletPlatform, use_notices, use_shortcuts
from viewmodel.app_vm import AppState, AppViewModel, Tab
from viewmodel.formatting import format_relative

#: 导航项与页签一一对应，顺序即 NavigationRail 的索引。
_NAV_ITEMS: tuple[tuple[Tab, str, str], ...] = (
    (Tab.PROJECTS, ft.Icons.FOLDER_OUTLINED, ft.Icons.FOLDER),
    (Tab.COMMIT, ft.Icons.COMMIT_OUTLINED, ft.Icons.COMMIT),
    (Tab.REPORTS, ft.Icons.ANALYTICS_OUTLINED, ft.Icons.ANALYTICS),
    (Tab.BUILD, ft.Icons.ROCKET_LAUNCH_OUTLINED, ft.Icons.ROCKET_LAUNCH),
)

_SHORTCUT_HINT = "Ctrl+1/2/3/4 切换 · Ctrl+N 新建 · F5 刷新"


@guarded
def AppShell(*, vm: AppViewModel, platform: FletPlatform) -> ft.Control:
    page = ft.context.page
    state = vm.state

    # 明暗模式是纯展示偏好，放在组件本地状态里；每次渲染都把亮度同步给令牌层，
    # 保证 tone_style / card_shadow 这类 Python 侧查表与客户端解析出来的角色色一致。
    dark, set_dark_state = ft.use_state(False)
    T.set_dark(dark)

    # 钩子的数量与顺序必须在每次渲染中保持一致，因此全部集中在顶部无条件调用。
    use_notices(page, vm)
    use_shortcuts(page, vm)
    ft.use_effect(lambda: page.run_task(vm.bootstrap), [])

    match state.tab:
        case Tab.COMMIT:
            current: ft.Control = CommitView(vm=vm.commit_vm, platform=platform)
        case Tab.REPORTS:
            current = ReportsView(vm=vm.reports_vm, platform=platform)
        case Tab.BUILD:
            current = BuildView(vm=vm.build_vm, platform=platform)
        case _:
            current = ProjectsView(
                vm=vm.projects_vm,
                platform=platform,
                on_refresh=vm.request_refresh,
            )

    def toggle_theme(_=None) -> None:
        """切换深浅色：先同步令牌层与页面主题，再触发一次重渲染。"""
        next_dark = not dark
        T.set_dark(next_dark)
        page.theme_mode = ft.ThemeMode.DARK if next_dark else ft.ThemeMode.LIGHT
        set_dark_state(next_dark)

    return ft.Row(
        spacing=0,
        expand=True,
        controls=[
            _sidebar(state, vm, dark=dark, on_toggle_theme=toggle_theme),
            ft.Column(
                expand=True,
                spacing=0,
                controls=[
                    ft.Container(expand=True, content=current),
                    widgets.divider(),
                    _status_bar(state, vm),
                ],
            ),
        ],
    )


# --------------------------------------------------------------------------- 侧栏
def _sidebar(state: AppState, vm: AppViewModel, *, dark: bool, on_toggle_theme) -> ft.Container:
    destinations = [
        ft.NavigationRailDestination(icon=icon, selected_icon=selected, label=tab.label)
        for tab, icon, selected in _NAV_ITEMS
    ]
    selected_index = next((i for i, (tab, _, _) in enumerate(_NAV_ITEMS) if tab is state.tab), 0)

    # 侧栏与页面同色、只用一条发丝线分隔：视觉上"通透"，把注意力留给内容。
    return ft.Container(
        width=T.SIDEBAR_WIDTH,
        bgcolor=T.SHELL_COLOR,
        border=ft.Border.only(right=ft.BorderSide(1, T.BORDER_COLOR)),
        content=ft.Column(
            expand=True,
            spacing=0,
            controls=[
                _brand(),
                # ⚠️ 指示块与标签样式必须写在控件上：flet 1.0 的客户端不会从
                # NavigationRailTheme 取这几项（实测：设置主题后仍是默认蓝）。
                ft.NavigationRail(
                    expand=True,
                    selected_index=selected_index,
                    min_width=T.SIDEBAR_WIDTH,
                    label_type=ft.NavigationRailLabelType.ALL,
                    use_indicator=True,
                    bgcolor=ft.Colors.TRANSPARENT,
                    elevation=0,
                    indicator_color=ft.Colors.PRIMARY_CONTAINER,
                    indicator_shape=ft.RoundedRectangleBorder(radius=T.RADIUS_MD),
                    selected_label_text_style=T.text_style(
                        11,
                        weight=ft.FontWeight.W_600,
                        color=ft.Colors.ON_PRIMARY_CONTAINER,
                    ),
                    unselected_label_text_style=T.text_style(
                        11, weight=ft.FontWeight.W_500, color=T.MUTED_TEXT
                    ),
                    pin_trailing_to_bottom=True,
                    destinations=destinations,
                    trailing=_sidebar_footer(state, vm, dark=dark, on_toggle_theme=on_toggle_theme),
                    on_change=lambda event: vm.select_tab(_nav_target(event)),
                ),
            ],
        ),
    )


def _brand() -> ft.Container:
    """品牌区：微渐变圆角标 + 小字标识，克制但有记忆点。"""
    return ft.Container(
        padding=ft.Padding.only(top=T.SPACE_XL, bottom=T.SPACE_MD),
        alignment=ft.Alignment.CENTER,
        content=ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=T.SPACE_SM,
            tight=True,
            controls=[
                ft.Container(
                    width=40,
                    height=40,
                    border_radius=T.RADIUS_LG,
                    gradient=T.brand_gradient(),
                    alignment=ft.Alignment.CENTER,
                    shadow=T.card_shadow(),
                    content=ft.Icon(ft.Icons.TERMINAL, color="#FFFFFF", size=21),
                ),
                T.text(
                    "CS PM",
                    level=T.TextLevel.CAPTION,
                    size=11,
                    weight=ft.FontWeight.W_700,
                    color=T.MUTED_TEXT,
                ),
            ],
        ),
    )


def _sidebar_footer(
    state: AppState, vm: AppViewModel, *, dark: bool, on_toggle_theme
) -> ft.Container:
    return ft.Container(
        padding=ft.Padding.only(bottom=T.SPACE_LG),
        alignment=ft.Alignment.CENTER,
        content=ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=T.SPACE_SM,
            tight=True,
            controls=[
                ft.Row(
                    spacing=0,
                    tight=True,
                    alignment=ft.MainAxisAlignment.CENTER,
                    controls=[
                        widgets.icon_action(
                            ft.Icons.SYNC,
                            "刷新全部仓库状态（F5）",
                            lambda _: vm.request_refresh(),
                            disabled=state.loading,
                        ),
                        widgets.icon_action(
                            ft.Icons.LIGHT_MODE_OUTLINED if dark else ft.Icons.DARK_MODE_OUTLINED,
                            "切换到浅色模式" if dark else "切换到深色模式",
                            on_toggle_theme,
                        ),
                    ],
                ),
                T.text(
                    f"v{APP_VERSION}",
                    level=T.TextLevel.CAPTION,
                    size=10,
                    color=T.MUTED_TEXT,
                ),
            ],
        ),
    )


def _nav_target(event) -> Tab:
    """把导航栏事件翻成页签。

    事件数据是选中的下标，但这里仍然做了类型兜底：读不到就退回读控件属性，
    再不行就当没变（返回当前项由视图模型自己判等忽略）。
    """
    value = widgets.event_value(event)
    try:
        index = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        control = getattr(event, "control", None)
        fallback = getattr(control, "selected_index", None)
        index = fallback if isinstance(fallback, int) else 0
    if 0 <= index < len(_NAV_ITEMS):
        return _NAV_ITEMS[index][0]
    return Tab.PROJECTS


# --------------------------------------------------------------------------- 状态栏
def _status_item(icon: str, text: str, *, tone: Tone = Tone.NEUTRAL) -> ft.Row:
    return ft.Row(
        spacing=T.SPACE_XS,
        tight=True,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.Icon(icon, size=14, color=T.tone_style(tone).accent),
            T.text(text, level=T.TextLevel.CAPTION, size=11, color=T.MUTED_TEXT),
        ],
    )


def _status_bar(state: AppState, vm: AppViewModel) -> ft.Container:
    left = ft.Row(
        spacing=T.SPACE_LG,
        controls=[
            _status_item(
                ft.Icons.CHECK_CIRCLE_OUTLINE if state.git_ready else ft.Icons.ERROR_OUTLINE,
                "git 就绪" if state.git_ready else "未检测到 git",
                tone=Tone.SUCCESS if state.git_ready else Tone.DANGER,
            ),
            _status_item(ft.Icons.FOLDER_OUTLINED, f"{len(state.projects)} 个项目"),
            *(
                [
                    _status_item(
                        ft.Icons.FILE_PRESENT_OUTLINED,
                        f"{state.dirty_files} 个待提交文件",
                    )
                ]
                if state.dirty_files
                else []
            ),
            *(
                [
                    _status_item(
                        ft.Icons.WARNING_AMBER_ROUNDED,
                        f"{state.attention} 项需关注",
                        tone=Tone.WARNING,
                    )
                ]
                if state.attention
                else []
            ),
        ],
    )

    right = ft.Row(
        spacing=T.SPACE_MD,
        tight=True,
        controls=[
            T.text(
                state.progress
                or (f"更新于 {format_relative(state.refreshed_at)}" if state.refreshed_at else ""),
                level=T.TextLevel.CAPTION,
                size=11,
                color=T.MUTED_TEXT,
            ),
            widgets.key_hint(_SHORTCUT_HINT),
            widgets.icon_action(
                ft.Icons.REFRESH,
                "刷新全部",
                lambda _: vm.request_refresh(),
                disabled=state.loading,
            ),
        ],
    )

    return ft.Container(
        bgcolor=T.SHELL_COLOR,
        content=ft.Column(
            spacing=0,
            tight=True,
            controls=[
                # 进度条只在真正加载时出现，占满整条状态栏宽度，不挤压其他信息
                ft.ProgressBar(
                    visible=state.loading,
                    height=2,
                    border_radius=0,
                ),
                ft.Container(
                    padding=ft.Padding.symmetric(horizontal=T.SPACE_LG, vertical=T.SPACE_SM),
                    content=ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[ft.Container(expand=True, content=left), right],
                    ),
                ),
            ],
        ),
    )


# --------------------------------------------------------------------------- 根组件
@ft.component
def App(*, vm: AppViewModel) -> ft.Control:
    """根组件：装配页面级平台服务，再交给外壳渲染。"""
    page = ft.context.page
    clipboard = ft.use_ref(ft.Clipboard).current
    picker = ft.use_ref(ft.FilePicker).current
    platform = ft.use_ref(lambda: FletPlatform(page, clipboard, picker)).current

    return ft.SafeArea(expand=True, content=AppShell(vm=vm, platform=platform))
