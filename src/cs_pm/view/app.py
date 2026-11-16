"""应用外壳：侧边导航、全局状态栏与快捷键。

外壳只做一件事：**把状态翻译成布局**。当前页签、全局进度、状态栏统计全部来自
:class:`~cs_pm.viewmodel.app_vm.AppState`；任何点击都只调用视图模型的方法，视图本身
不保存业务数据，也不判断业务规则。

三个刻意的选择
--------------
1. **侧栏是自绘的，不是 ``NavigationRail``。** Material 的 rail 把标签压在图标
   下面，中文四个字在 96px 的宽度里会挤成两行；桌面端读的是"词"，所以这里是
   "图标 + 文字横排"的一列 —— 顺带也不再需要那一串"必须在控件上重写主题"的补丁。
2. **明暗由 cs-ui 的主题运行时管。** 外壳用 ``use_theme()`` 订阅主题，点击时调
   ``toggle_mode()`` —— 它永远切到与**当前可见**相反的那一档。整棵树重渲染，
   于是 :func:`cs_pm.view.design.card_color` 这类 Python 侧取色也跟着换。
3. **状态栏用 ``ui.StatusBar``。** 它只有 30px 高、只在左侧放状态点，不与内容抢
   注意力；进度条单独挂在它上面 2px，加载结束就消失。

平台能力（剪贴板、文件选择器）是**页面级服务**，构造即注册到 page，重复构造会
注册多份，所以在这里用 ``use_ref`` 各创建一次，交给 :class:`FletPlatform` 分派。
"""

from __future__ import annotations

import ui
from ui import (
    SPACE,
    Alignment,
    Border,
    BorderSide,
    Colors,
    Column,
    Container,
    CrossAxisAlignment,
    Divider,
    FontWeight,
    Icon,
    Icons,
    Padding,
    ProgressBar,
    Row,
    SafeArea,
    TextOverflow,
)

from cs_pm.models.enums import Tone
from cs_pm.models.settings import APP_NAME, APP_TAGLINE, APP_VERSION
from cs_pm.view import design as T
from cs_pm.view import widgets
from cs_pm.view.build import BuildView
from cs_pm.view.commit import CommitView
from cs_pm.view.guard import guarded
from cs_pm.view.projects import ProjectsView
from cs_pm.view.reports import ReportsView
from cs_pm.view.settings import SettingsView
from cs_pm.view.view_platform import FletPlatform, use_notices, use_shortcuts
from cs_pm.viewmodel.app_vm import AppState, AppViewModel, Tab
from cs_pm.viewmodel.formatting import format_relative

#: 导航项与页签一一对应：图标、选中态图标、标签。
_NAV_ITEMS: tuple[tuple[Tab, str, str, str], ...] = (
    (Tab.PROJECTS, Icons.FOLDER_OUTLINED, Icons.FOLDER, "项目"),
    (Tab.COMMIT, Icons.COMMIT_OUTLINED, Icons.COMMIT, "提交"),
    (Tab.REPORTS, Icons.ANALYTICS_OUTLINED, Icons.ANALYTICS, "统计"),
    (Tab.BUILD, Icons.ROCKET_LAUNCH_OUTLINED, Icons.ROCKET_LAUNCH, "打包"),
    (Tab.SETTINGS, Icons.SETTINGS_OUTLINED, Icons.SETTINGS, "设置"),
)

_SHORTCUT_HINT = "Ctrl+1~5 切换 · Ctrl+N 新建 · F5 刷新"


@guarded
def AppShell(*, vm: AppViewModel, platform: FletPlatform) -> ui.Control:
    page = ui.context.page
    state = vm.state

    # 订阅主题：模式一变本组件重渲染，整棵树的取色随之更新。
    theme = ui.use_theme()

    # 钩子的数量与顺序必须在每次渲染中保持一致，因此全部集中在顶部无条件调用。
    use_notices(page, vm)
    use_shortcuts(page, vm)
    ui.use_effect(lambda: page.run_task(vm.bootstrap), [])

    match state.tab:
        case Tab.COMMIT:
            current: ui.Control = CommitView(vm=vm.commit_vm, platform=platform)
        case Tab.REPORTS:
            current = ReportsView(vm=vm.reports_vm, platform=platform)
        case Tab.BUILD:
            current = BuildView(vm=vm.build_vm, platform=platform)
        case Tab.SETTINGS:
            current = SettingsView(vm=vm.settings_vm, platform=platform)
        case _:
            current = ProjectsView(
                vm=vm.projects_vm,
                platform=platform,
                on_refresh=vm.request_refresh,
            )

    return Row(
        spacing=0,
        expand=True,
        controls=[
            _sidebar(state=state, vm=vm, theme=theme),
            Column(
                expand=True,
                spacing=0,
                controls=[
                    Container(expand=True, content=current),
                    _status_bar(state, vm),
                ],
            ),
        ],
    )


# --------------------------------------------------------------------------- 侧栏
def _sidebar(*, state: AppState, vm: AppViewModel, theme) -> Container:
    """侧栏与页面同色、只用一条发丝线分隔：视觉上"通透"，注意力留给内容。"""
    return Container(
        width=T.SIDEBAR_WIDTH,
        bgcolor=T.SHELL_COLOR,
        border=Border.only(right=BorderSide(1, T.BORDER_COLOR)),
        content=Column(
            expand=True,
            spacing=0,
            controls=[
                _brand(),
                Container(
                    padding=Padding.symmetric(horizontal=SPACE["2"]),
                    content=Column(
                        spacing=SPACE["1"],
                        tight=True,
                        controls=[
                            _nav_item(
                                tab,
                                icon,
                                selected_icon,
                                label,
                                active=state.tab is tab,
                                on_click=lambda _, target=tab: vm.select_tab(target),
                            )
                            for tab, icon, selected_icon, label in _NAV_ITEMS
                        ],
                    ),
                ),
                Container(expand=True),
                _sidebar_footer(state=state, vm=vm, theme=theme),
            ],
        ),
    )


def _brand() -> Container:
    """品牌区：微渐变圆角标 + 产品名 + 一句话定位。"""
    return Container(
        padding=Padding.only(top=SPACE["4"], bottom=SPACE["4"], left=SPACE["3"], right=SPACE["3"]),
        content=Row(
            spacing=SPACE["2"],
            vertical_alignment=CrossAxisAlignment.CENTER,
            controls=[
                Container(
                    width=32,
                    height=32,
                    border_radius=T.RADIUS_MD,
                    gradient=T.brand_gradient(),
                    alignment=Alignment.CENTER,
                    content=Icon(Icons.TERMINAL, color="#FFFFFF", size=T.ICON_MD),
                ),
                Column(
                    spacing=0,
                    tight=True,
                    expand=True,
                    controls=[
                        T.text(
                            APP_NAME,
                            level=T.TextLevel.TITLE,
                            size=14,
                            weight=FontWeight.W_600,
                            max_lines=1,
                            overflow=TextOverflow.ELLIPSIS,
                        ),
                        widgets.muted(APP_TAGLINE, size=10, max_lines=1),
                    ],
                ),
            ],
        ),
    )


@ui.component
def _nav_item(
    tab: Tab,
    icon: str,
    selected_icon: str,
    label: str,
    *,
    active: bool,
    on_click,
) -> ui.Control:
    """一个导航项：选中用主色浅底 + 主色文字，悬停时浮出一层薄底。

    这里**不用** ``ui.Button``：Material 的按钮自带底色与投影，即使只给文字
    也会渲染成一块浮起的灰砖，和"侧栏里的一行"完全不是一种东西。也别写
    ``bgcolor=Colors.TRANSPARENT`` 想把它压平 —— 客户端解析不出这个色名时会退回
    默认填充，四个导航项里三个变灰。所以悬停状态自己管（``use_state``），
    底色只在"选中"和"悬停"两种情况下出现。
    """
    hovered, set_hovered = ui.use_state(False)
    fg = Colors.ON_PRIMARY_CONTAINER if active else T.MUTED_TEXT
    if active:
        bg = Colors.PRIMARY_CONTAINER
    elif hovered:
        bg = ui.overlay(0.05)
    else:
        bg = None

    def handle_hover(event) -> None:
        hovering = bool(getattr(event, "data", False))
        if hovering != hovered:
            set_hovered(hovering)

    return Container(
        key=f"nav-{tab.value}",
        height=40,
        on_click=on_click,
        on_hover=handle_hover,
        border_radius=T.RADIUS_MD,
        padding=Padding.symmetric(horizontal=SPACE["2"]),
        bgcolor=bg,
        ink=True,
        ink_color=ui.overlay(0.06),
        animate=T.animate(duration=T.DURATION_FAST),
        content=Row(
            spacing=SPACE["2"],
            vertical_alignment=CrossAxisAlignment.CENTER,
            controls=[
                Icon(selected_icon if active else icon, size=T.ICON_MD, color=fg),
                T.text(
                    label,
                    level=T.TextLevel.BODY,
                    weight=FontWeight.W_600 if active else FontWeight.W_500,
                    color=fg,
                    expand=True,
                ),
            ],
        ),
    )


def _toggle_theme(theme) -> None:
    """明暗互切：先改主题状态，再把新的一档下发到页面。

    两步都要做 —— ``toggle_mode()`` 只改状态并通知订阅者（组件会重渲染），
    但 ``page.theme_mode`` 得靠 ``apply_theme`` 才落到 Flutter 侧；少了后者，
    Python 侧已经按深色取色、画面却还停在浅色，是最难查的一种"半生效"。
    """
    theme.toggle_mode()
    ui.apply_theme(ui.context.page, theme)


def _sidebar_footer(*, state: AppState, vm: AppViewModel, theme) -> Container:
    return Container(
        padding=Padding.only(bottom=SPACE["3"], top=SPACE["2"], left=SPACE["2"], right=SPACE["2"]),
        content=Column(
            spacing=SPACE["1"],
            tight=True,
            controls=[
                Row(
                    spacing=0,
                    tight=True,
                    controls=[
                        widgets.icon_action(
                            Icons.SYNC,
                            "刷新全部仓库状态（F5）",
                            lambda _: vm.request_refresh(),
                            disabled=state.loading,
                        ),
                        widgets.icon_action(
                            Icons.LIGHT_MODE_OUTLINED
                            if theme.is_dark
                            else Icons.DARK_MODE_OUTLINED,
                            "切换到浅色模式" if theme.is_dark else "切换到深色模式",
                            lambda _: _toggle_theme(theme),
                        ),
                        Container(expand=True),
                        widgets.muted(f"v{APP_VERSION}", size=10),
                    ],
                ),
            ],
        ),
    )


# --------------------------------------------------------------------------- 状态栏
def _status_item(icon: str, text: str, *, tone: Tone = Tone.NEUTRAL) -> Row:
    return Row(
        spacing=SPACE["1"],
        tight=True,
        vertical_alignment=CrossAxisAlignment.CENTER,
        controls=[
            Icon(icon, size=T.ICON_SM, color=T.tone_style(tone).accent),
            T.text(text, level=T.TextLevel.CAPTION, color=T.MUTED_TEXT),
        ],
    )


def _status_bar(state: AppState, vm: AppViewModel) -> Container:
    left = Row(
        spacing=SPACE["4"],
        vertical_alignment=CrossAxisAlignment.CENTER,
        controls=[
            _status_item(
                Icons.CHECK_CIRCLE_OUTLINE if state.git_ready else Icons.ERROR_OUTLINE,
                "git 就绪" if state.git_ready else "未检测到 git",
                tone=Tone.SUCCESS if state.git_ready else Tone.DANGER,
            ),
            _status_item(Icons.FOLDER_OUTLINED, f"{len(state.projects)} 个项目"),
            *(
                [
                    _status_item(
                        Icons.FILE_PRESENT_OUTLINED,
                        f"{state.dirty_files} 个待提交文件",
                    )
                ]
                if state.dirty_files
                else []
            ),
            *(
                [
                    _status_item(
                        Icons.WARNING_AMBER_ROUNDED,
                        f"{state.attention} 项需关注",
                        tone=Tone.WARNING,
                    )
                ]
                if state.attention
                else []
            ),
        ],
    )

    status = state.progress or (
        f"更新于 {format_relative(state.refreshed_at)}" if state.refreshed_at else ""
    )

    return Container(
        bgcolor=T.SHELL_COLOR,
        content=Column(
            spacing=0,
            tight=True,
            controls=[
                # 进度条只在真正加载时出现，占满整条宽度，不挤压其他信息
                ProgressBar(visible=state.loading, height=2, border_radius=0),
                Divider(height=1, thickness=1, color=T.BORDER_COLOR),
                ui.StatusBar(
                    summary=left,
                    status=status,
                    show_dot=False,
                    divider=False,
                    actions=[
                        widgets.key_hint(_SHORTCUT_HINT),
                        widgets.icon_action(
                            Icons.REFRESH,
                            "刷新全部",
                            lambda _: vm.request_refresh(),
                            disabled=state.loading,
                        ),
                    ],
                ),
            ],
        ),
    )


# --------------------------------------------------------------------------- 根组件
@ui.component
def App(*, vm: AppViewModel) -> ui.Control:
    """根组件：装配页面级平台服务，再交给外壳渲染。"""
    page = ui.context.page
    clipboard = ui.use_ref(ui.Clipboard).current
    # 命令式系统对话框：渲染期构造即注册到当前页，一个会话只建一份
    dialog = ui.use_ref(ui.FileDialog).current
    platform = ui.use_ref(lambda: FletPlatform(page, clipboard, dialog)).current

    return SafeArea(expand=True, content=AppShell(vm=vm, platform=platform))
