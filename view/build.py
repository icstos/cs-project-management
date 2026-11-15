"""打包页：把项目文件夹里的 Flet 程序构建成 Windows 程序。

执行顺序刻意做成"先体检、再腾位置、后施工"（细节在视图模型里），界面负责把
当前阶段、将要执行的命令和实时输出如实呈现出来：

* 「将要执行的步骤」与真正跑的命令同源，看到的必然是真跑的；
* 控制台按固定间隔合并刷新，被截掉的部分在日志文件里有完整记录；
* 产物目录非空时旧版本会自动移入同级的「历史版本」文件夹（不删除），搬不动
  才弹框让用户决定。

控制台是这一页的视觉重心：它固定用深色底 + 等宽字体，和周围的浅卡片刻意拉开，
让人一眼分清"界面"与"机器输出"。
"""

from __future__ import annotations

import ui
from ui import (
    SPACE,
    Alignment,
    Border,
    Colors,
    Column,
    Container,
    CrossAxisAlignment,
    FontWeight,
    Icon,
    Icons,
    ListView,
    Padding,
    Row,
    Switch,
    Text,
    TextOverflow,
)

from models.dtos import Project, TreeStats
from models.enums import Tone
from view import design as T
from view import widgets
from view.dialogs import archive_failed_dialog
from view.guard import guarded
from view.view_platform import FletPlatform, use_notices, use_platform_requests
from viewmodel.build_vm import BuildState, BuildViewModel
from viewmodel.formatting import human_bytes

_PANE_WIDTH = 300


@guarded
def BuildView(*, vm: BuildViewModel, platform: FletPlatform) -> ui.Control:
    page = ui.context.page
    state = vm.state
    use_notices(page, vm)
    use_platform_requests(platform, vm)

    # 只探测一次工具链；换项目时重新统计产物目录
    ui.use_effect(lambda: page.run_task(vm.probe_tool), [])
    ui.use_effect(lambda: page.run_task(vm.load_output), [state.plan])

    ui.use_dialog(
        archive_failed_dialog(
            failure=state.failure,
            on_retry=lambda _: vm.retry_archive(),
            on_close=lambda _: vm.dismiss_failure(),
        )
        if state.failure is not None
        else None
    )

    if not state.projects:
        return widgets.page_shell(
            header=widgets.page_header(
                "打包发布", "把项目文件夹里的 Flet 程序构建成 Windows 程序并输出到发布目录"
            ),
            body=widgets.empty_state(
                Icons.ROCKET_LAUNCH_OUTLINED,
                "还没有可打包的项目",
                "请先在「项目」中添加本地 Flet 项目",
            ),
        )

    return widgets.page_shell(
        header=widgets.page_header(
            "打包发布",
            "先清理 build 目录再构建到发布目录；旧版本自动存入「历史版本」，命令与输出全程记录"
            if state.clean_build
            else "跳过清理，直接基于上一次的 build 目录增量构建；旧版本自动存入"
            "「历史版本」，命令与输出全程记录",
            # 两个互斥按钮**常驻**、只切 visible：打包结束那一刻如果在 actions
            # 列表里把「终止」整项换成「开始打包」，flet 的组件重渲染会按位置
            # 配对新旧控件，把 Expanded 父数据错配到别的控件上 —— Flutter 端
            # 只画出一个灰块（release 客户端不报错），整页被盖住。
            actions=[
                widgets.outlined(
                    "终止",
                    icon=Icons.STOP_CIRCLE_OUTLINED,
                    visible=state.running,
                    on_click=lambda _: vm.stop(),
                ),
                widgets.filled(
                    "开始打包",
                    icon=Icons.ROCKET_LAUNCH,
                    visible=not state.running,
                    disabled=not state.can_start,
                    on_click=lambda _: vm.request_start(),
                ),
                widgets.outlined(
                    "打开发布目录",
                    icon=Icons.FOLDER_OPEN,
                    disabled=state.running,
                    on_click=lambda _: page.run_task(vm.open_output_dir),
                ),
            ],
        ),
        body=Row(
            expand=True,
            spacing=T.GRID_GUTTER,
            vertical_alignment=CrossAxisAlignment.STRETCH,
            controls=[
                Container(width=_PANE_WIDTH, content=_project_pane(state, vm)),
                Container(
                    expand=True,
                    content=Column(
                        expand=True,
                        spacing=T.GRID_GUTTER,
                        controls=[
                            _target_panel(state, vm),
                            _command_panel(state),
                            *([_outcome_row(state, vm, page)] if state.outcome else []),
                            _console_panel(state),
                        ],
                    ),
                ),
            ],
        ),
    )


# --------------------------------------------------------------------------- 左栏
def _project_pane(state: BuildState, vm: BuildViewModel) -> ui.Control:
    return widgets.surface(
        expand=True,
        padding=SPACE["3"],
        content=Column(
            expand=True,
            spacing=SPACE["2"],
            controls=[
                Row(
                    spacing=SPACE["2"],
                    vertical_alignment=CrossAxisAlignment.CENTER,
                    controls=[
                        T.text(
                            "选择项目",
                            level=T.TextLevel.LABEL,
                            weight=FontWeight.W_600,
                            color=T.MUTED_TEXT,
                        ),
                        Container(expand=True),
                        widgets.pill(str(len(state.projects)), dense=True),
                    ],
                ),
                ListView(
                    expand=True,
                    spacing=SPACE["1"],
                    controls=[
                        _project_tile(
                            project,
                            output_name=vm.output_name(project),
                            active=project.id == state.selected_id,
                            locked=state.running,
                            on_click=vm.select,
                        )
                        for project in state.projects
                    ],
                ),
            ],
        ),
    )


def _project_tile(
    project: Project,
    *,
    output_name: str,
    active: bool,
    locked: bool,
    on_click,
) -> Container:
    return Container(
        key=f"build-project-{project.id}",
        on_click=None if locked else lambda _: on_click(project),
        border_radius=T.RADIUS_MD,
        padding=Padding.symmetric(horizontal=SPACE["2"], vertical=SPACE["2"]),
        bgcolor=Colors.PRIMARY_CONTAINER if active else Colors.TRANSPARENT,
        border=Border.only(left=ui.BorderSide(3, Colors.PRIMARY if active else Colors.TRANSPARENT)),
        ink=not locked,
        ink_color=ui.overlay(0.06, role=Colors.PRIMARY),
        opacity=1.0 if not locked or active else 0.55,
        animate=T.animate(duration=T.DURATION_FAST),
        content=Column(
            spacing=SPACE["1"],
            tight=True,
            controls=[
                T.text(
                    project.name,
                    level=T.TextLevel.BODY,
                    weight=FontWeight.W_600 if active else FontWeight.W_500,
                    color=Colors.ON_PRIMARY_CONTAINER if active else None,
                    max_lines=1,
                    overflow=TextOverflow.ELLIPSIS,
                ),
                T.text(
                    output_name,
                    level=T.TextLevel.CAPTION,
                    color=Colors.ON_PRIMARY_CONTAINER if active else T.MUTED_TEXT,
                    max_lines=1,
                    overflow=TextOverflow.ELLIPSIS,
                ),
            ],
        ),
    )


# --------------------------------------------------------------------------- 右栏
def _target_panel(state: BuildState, vm: BuildViewModel) -> ui.Control:
    plan = state.plan
    if plan is None:
        return widgets.surface(
            content=widgets.hint_row(Icons.TOUCH_APP, "请选择左侧的项目", tone=Tone.NEUTRAL)
        )

    occupied = state.occupied
    notes: list[ui.Control] = []
    if state.readiness.issue:
        notes.append(widgets.inline_error(state.readiness.issue))
    notes.extend(
        widgets.hint_row(Icons.WARNING_AMBER_ROUNDED, text, tone=Tone.WARNING)
        for text in state.readiness.warnings
    )
    if state.tool is not None and not state.tool.available:
        notes.append(
            widgets.hint_row(
                Icons.ERROR_OUTLINE,
                f"未找到 flet 命令：{state.tool.detail}",
                tone=Tone.DANGER,
            )
        )
    if occupied:
        # 说清"会先搬走、不会删"，并把存档目录直接摆出来，用户不必猜去了哪
        stats = state.output_state
        size = f"{stats.files} 个文件（{human_bytes(stats.bytes)}）" if stats else "文件"
        notes.append(
            widgets.hint_row(
                Icons.INFO_OUTLINE,
                f"产物目录里已有 {size}：开始打包时会先整体移入历史版本（不删除，"
                "目录名追加 -before-时间）",
                tone=Tone.WARNING,
            )
        )
        notes.append(_path_row(Icons.HISTORY, "历史版本", str(plan.history_dir)))
    if state.archived:
        notes.append(
            widgets.hint_row(Icons.CHECK_CIRCLE_OUTLINE, "上一次的产物已存档", tone=Tone.SUCCESS)
        )
        notes.append(_path_row(Icons.INVENTORY_2_OUTLINED, "已移入", state.archived))

    return widgets.surface(
        content=Column(
            spacing=T.FIELD_GAP,
            tight=True,
            controls=[
                Row(
                    spacing=SPACE["2"],
                    vertical_alignment=CrossAxisAlignment.CENTER,
                    controls=[
                        Container(
                            width=28,
                            height=28,
                            border_radius=T.RADIUS_SM,
                            bgcolor=T.tone_style(Tone.PRIMARY).container,
                            alignment=Alignment.CENTER,
                            content=Icon(
                                Icons.ROCKET_LAUNCH_OUTLINED,
                                size=16,
                                color=T.tone_style(Tone.PRIMARY).accent,
                            ),
                        ),
                        T.text(
                            plan.project_name,
                            level=T.TextLevel.TITLE,
                            weight=FontWeight.W_600,
                        ),
                        Container(expand=True),
                        _output_pill(state.output_state, occupied),
                    ],
                ),
                Column(
                    spacing=SPACE["1"],
                    tight=True,
                    controls=[
                        _path_row(Icons.DESCRIPTION_OUTLINED, "源目录", plan.source),
                        _path_row(
                            Icons.INVENTORY_2_OUTLINED,
                            "产物目录",
                            plan.output,
                            tone=Tone.WARNING if occupied else Tone.NEUTRAL,
                        ),
                    ],
                ),
                _clean_row(state, vm),
                Row(
                    spacing=SPACE["2"],
                    wrap=True,
                    run_spacing=SPACE["2"],
                    controls=[
                        widgets.pill(f"目标 {plan.target}", icon=Icons.LAPTOP_WINDOWS, dense=True),
                        widgets.pill(f"Python {plan.python_version}", icon=Icons.CODE, dense=True),
                        widgets.pill(
                            f"artifact / product = {plan.project_name}",
                            icon=Icons.LABEL_OUTLINE,
                            dense=True,
                        ),
                        widgets.flag_pill(
                            "模板目录就绪",
                            state.readiness.template_ok,
                            bad_label="模板目录缺失",
                            bad_tone=Tone.DANGER,
                        ),
                    ],
                ),
                *notes,
            ],
        )
    )


def _output_pill(stats: TreeStats | None, occupied: bool) -> ui.Control:
    if occupied and stats is not None:
        return widgets.pill(
            f"已有 {stats.files} 个文件（{human_bytes(stats.bytes)}）",
            tone=Tone.WARNING,
            icon=Icons.FOLDER_OPEN,
            dense=True,
        )
    # 空目录是**常态**不是成绩：用中性色播报，绿色留给"刚刚打包成功"这类
    # 真正的事件。否则每张卡片都挂着一枚绿标，"成功"就失去了意义。
    return widgets.pill(
        "产物目录为空" if stats is not None else "正在检查产物目录…",
        tone=Tone.NEUTRAL,
        icon=Icons.FOLDER_OPEN,
        dense=True,
    )


def _path_row(icon: str, label: str, value: str, *, tone: Tone = Tone.NEUTRAL) -> Row:
    return Row(
        spacing=SPACE["2"],
        vertical_alignment=CrossAxisAlignment.CENTER,
        controls=[
            Icon(icon, size=T.ICON_SM, color=T.tone_style(tone).accent),
            T.text(
                label,
                level=T.TextLevel.CAPTION,
                color=T.MUTED_TEXT,
                width=64,
            ),
            Text(
                value,
                size=12,
                expand=True,
                max_lines=1,
                overflow=TextOverflow.ELLIPSIS,
                tooltip=value,
                selectable=True,
            ),
        ],
    )


def _clean_row(state: BuildState, vm: BuildViewModel) -> ui.Control:
    """「清理 build 目录」开关：一行把开与不开的后果都写清楚。

    关掉不只是少删一次：``flet clean`` 也一并跳过（它删的正是同一个 ``build/``，
    留着它只会因为只读文件直接失败），于是变成增量构建。代价必须在开关旁边说完，
    别等构建出了怪结果再回头解释。
    """
    enabled = state.clean_build
    return Row(
        spacing=SPACE["2"],
        vertical_alignment=CrossAxisAlignment.CENTER,
        controls=[
            Icon(Icons.CLEANING_SERVICES_OUTLINED, size=T.ICON_SM, color=T.MUTED_TEXT),
            Column(
                expand=True,
                spacing=1,
                tight=True,
                controls=[
                    T.text(
                        "打包前清理 build 目录",
                        level=T.TextLevel.BODY,
                        weight=FontWeight.W_500,
                    ),
                    T.text(
                        "删除源目录下的 build/，从零开始构建"
                        if enabled
                        else "跳过清理：沿用上一次的 build/，构建更快，旧文件可能残留",
                        level=T.TextLevel.CAPTION,
                        color=T.MUTED_TEXT,
                    ),
                ],
            ),
            Switch(
                value=enabled,
                on_toggle=vm.set_clean_build,
                disabled=state.running,
            ).ui(),
        ],
    )


def _command_panel(state: BuildState) -> ui.Control:
    if not state.steps:
        return widgets.surface(content=widgets.muted("选择项目后显示将要执行的命令", size=12))

    return widgets.surface(
        content=Column(
            spacing=T.FIELD_GAP,
            tight=True,
            controls=[
                Row(
                    spacing=SPACE["2"],
                    vertical_alignment=CrossAxisAlignment.CENTER,
                    controls=[
                        T.text(
                            "将要执行的步骤",
                            level=T.TextLevel.TITLE,
                            weight=FontWeight.W_600,
                        ),
                        Container(expand=True),
                        widgets.muted("可选中复制", size=11),
                    ],
                ),
                *(
                    []
                    if state.clean_build
                    else [
                        widgets.hint_row(
                            Icons.INFO_OUTLINE,
                            "已关闭清理：本次只执行 flet build，沿用上一次的 build/ 目录，"
                            "旧文件与缓存可能留在里面",
                            tone=Tone.WARNING,
                        )
                    ]
                ),
                widgets.command_steps(state.steps),
            ],
        )
    )


def _outcome_row(state: BuildState, vm: BuildViewModel, page: ui.Page) -> ui.Control:
    outcome = state.outcome
    assert outcome is not None  # 由调用方保证
    return widgets.surface(
        padding=SPACE["3"],
        content=Row(
            spacing=SPACE["2"],
            vertical_alignment=CrossAxisAlignment.CENTER,
            controls=[
                # hint_row 内部文本是 expand 的，必须套一层有界容器，
                # 否则在 Row 里拿到无界宽度约束会直接报渲染错误
                Container(
                    expand=True,
                    content=widgets.hint_row(
                        Icons.CHECK_CIRCLE_OUTLINE if outcome.ok else Icons.ERROR_OUTLINE,
                        outcome.detail,
                        tone=Tone.SUCCESS if outcome.ok else Tone.DANGER,
                    ),
                ),
                *(
                    [
                        widgets.text_btn(
                            "打开产物目录",
                            icon=Icons.FOLDER_OPEN,
                            on_click=lambda _: page.run_task(vm.reveal, outcome.output),
                        )
                    ]
                    if outcome.output
                    else []
                ),
            ],
        ),
    )


def _console_panel(state: BuildState) -> ui.Control:
    """构建控制台：固定深底 + 等宽字体，与周围的卡片刻意拉开。

    这一行里有 expand 的占位块，因此**不能**用 ``wrap=True``：Wrap 不是 Flex，
    子项带 expand 会被 Flutter 判为 ParentDataWidget 错误，release 客户端只会
    画出一个灰块，什么错误都看不到。
    """
    return widgets.surface(
        expand=True,
        content=Column(
            expand=True,
            spacing=T.FIELD_GAP,
            controls=[
                Row(
                    spacing=SPACE["2"],
                    vertical_alignment=CrossAxisAlignment.CENTER,
                    controls=[
                        T.text(
                            "构建输出",
                            level=T.TextLevel.TITLE,
                            weight=FontWeight.W_600,
                        ),
                        *([ui.Loading(size_name="small")] if state.running else []),
                        Container(expand=True),
                        *(
                            [widgets.pill(f"{state.console_lines} 行", dense=True)]
                            if state.console_lines
                            else []
                        ),
                        widgets.muted("! 开头的行来自 stderr；完整输出见日志", size=11),
                    ],
                ),
                *(
                    [widgets.hint_row(Icons.PLAY_CIRCLE_OUTLINE, state.phase, tone=Tone.INFO)]
                    if state.phase
                    else []
                ),
                Container(
                    expand=True,
                    border_radius=T.RADIUS_MD,
                    bgcolor=T.CONSOLE_BG,
                    border=T.hairline(),
                    padding=SPACE["3"],
                    content=ListView(
                        expand=True,
                        auto_scroll=True,
                        controls=[
                            Text(
                                state.console or "（等待输出…）",
                                size=11,
                                selectable=True,
                                font_family=T.MONO_FONTS[0],
                                font_family_fallback=T.MONO_FONTS,
                                color=T.CONSOLE_TEXT if state.console else T.CONSOLE_DIM,
                                style=ui.TextStyle(height=1.6),
                            )
                        ],
                    ),
                ),
            ],
        ),
    )
