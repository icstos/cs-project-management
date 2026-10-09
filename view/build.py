"""打包页：把项目文件夹里的 Flet 程序构建成 Windows 程序。

执行顺序刻意做成"先体检、再确认、后施工"（细节在视图模型里），界面负责把
当前阶段、将要执行的命令和实时输出如实呈现出来：

* 「将要执行的步骤」与真正跑的命令同源，看到的必然是真跑的；
* 控制台按固定间隔合并刷新，被截掉的部分在日志文件里有完整记录；
* 产物目录非空、删除被占用等需要用户决策的时刻，各弹各的框。
"""

from __future__ import annotations

import flet as ft

from models.dtos import Project, TreeStats
from models.enums import Tone
from view import design as T
from view import widgets
from view.dialogs import output_conflict_dialog, output_locked_dialog
from view.guard import guarded
from view.view_platform import FletPlatform, use_notices, use_platform_requests
from viewmodel.build_vm import BuildState, BuildViewModel
from viewmodel.formatting import human_bytes

_PANE_WIDTH = 320


@guarded
def BuildView(*, vm: BuildViewModel, platform: FletPlatform) -> ft.Control:
    page = ft.context.page
    state = vm.state
    use_notices(page, vm)
    use_platform_requests(platform, vm)

    # 只探测一次工具链；换项目时重新统计产物目录
    ft.use_effect(lambda: page.run_task(vm.probe_tool), [])
    ft.use_effect(lambda: page.run_task(vm.load_output), [state.plan])

    ft.use_dialog(
        output_conflict_dialog(
            conflict=state.conflict,
            on_confirm=lambda _: vm.confirm_remove(),
            on_cancel=lambda _: vm.cancel_conflict(),
        )
        if state.conflict is not None
        else None
    )
    ft.use_dialog(
        output_locked_dialog(
            failure=state.failure,
            on_retry=lambda _: vm.retry_remove(),
            on_close=lambda _: vm.update(failure=None),
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
                ft.Icons.ROCKET_LAUNCH_OUTLINED,
                "还没有可打包的项目",
                "请先在「项目」中添加本地 Flet 项目",
            ),
        )

    return widgets.page_shell(
        header=widgets.page_header(
            "打包发布",
            "先在项目目录执行 flet clean，再构建到发布目录；命令与输出全程记录",
            actions=[
                *(
                    [
                        widgets.outlined(
                            "终止",
                            icon=ft.Icons.STOP_CIRCLE_OUTLINED,
                            on_click=lambda _: vm.stop(),
                        )
                    ]
                    if state.running
                    else [
                        widgets.filled(
                            "开始打包",
                            icon=ft.Icons.ROCKET_LAUNCH,
                            disabled=not state.can_start,
                            on_click=lambda _: vm.request_start(),
                        )
                    ]
                ),
                widgets.outlined(
                    "打开发布目录",
                    icon=ft.Icons.FOLDER_OPEN,
                    disabled=state.running,
                    on_click=lambda _: page.run_task(vm.open_output_dir),
                ),
            ],
        ),
        body=ft.Row(
            expand=True,
            spacing=T.SPACE_MD,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[
                ft.Container(width=_PANE_WIDTH, content=_project_pane(state, vm)),
                ft.Container(
                    expand=True,
                    content=ft.Column(
                        expand=True,
                        spacing=T.SPACE_MD,
                        controls=[
                            _target_panel(state),
                            _command_panel(state.steps),
                            *([_outcome_row(state, vm, page)] if state.outcome else []),
                            _console_panel(state),
                        ],
                    ),
                ),
            ],
        ),
    )


# --------------------------------------------------------------------------- 构件
def _project_pane(state: BuildState, vm: BuildViewModel) -> ft.Control:
    return widgets.surface(
        expand=True,
        padding=T.SPACE_SM,
        content=ft.Column(
            expand=True,
            spacing=T.SPACE_XS,
            controls=[
                ft.Container(
                    padding=ft.Padding.only(left=T.SPACE_SM, top=T.SPACE_XS, bottom=T.SPACE_XS),
                    content=ft.Row(
                        controls=[
                            ft.Text("选择项目", size=13, weight=ft.FontWeight.W_600),
                            ft.Container(expand=True),
                            widgets.pill(str(len(state.projects)), dense=True),
                        ]
                    ),
                ),
                ft.ListView(
                    expand=True,
                    spacing=T.SPACE_XXS,
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
) -> ft.Container:
    tone = T.tone_style(Tone.PRIMARY)
    return ft.Container(
        key=f"build-project-{project.id}",
        on_click=None if locked else lambda _: on_click(project),
        border_radius=T.RADIUS_MD,
        padding=ft.Padding.symmetric(horizontal=T.SPACE_MD, vertical=T.SPACE_SM),
        bgcolor=tone.container if active else ft.Colors.TRANSPARENT,
        border=ft.Border.all(1, tone.accent if active else ft.Colors.TRANSPARENT),
        opacity=1.0 if not locked or active else 0.6,
        content=ft.Column(
            spacing=T.SPACE_XXS,
            tight=True,
            controls=[
                ft.Text(
                    project.name,
                    size=13,
                    weight=ft.FontWeight.W_600 if active else ft.FontWeight.W_500,
                    max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS,
                ),
                widgets.muted(output_name, size=11),
            ],
        ),
    )


def _target_panel(state: BuildState) -> ft.Control:
    plan = state.plan
    if plan is None:
        return widgets.surface(
            content=widgets.hint_row(ft.Icons.TOUCH_APP, "请选择左侧的项目", tone=Tone.NEUTRAL)
        )

    occupied = state.occupied
    notes: list[ft.Control] = []
    if state.readiness.issue:
        notes.append(widgets.inline_error(state.readiness.issue))
    notes.extend(
        widgets.hint_row(ft.Icons.WARNING_AMBER_ROUNDED, text, tone=Tone.WARNING)
        for text in state.readiness.warnings
    )
    if state.tool is not None and not state.tool.available:
        notes.append(
            widgets.hint_row(
                ft.Icons.ERROR_OUTLINE,
                f"未找到 flet 命令：{state.tool.detail}",
                tone=Tone.DANGER,
            )
        )
    if occupied:
        # 提示要点到"会先问一句"为止：具体问什么、删多少，留给弹窗说
        notes.append(
            widgets.hint_row(
                ft.Icons.INFO_OUTLINE,
                "产物目录里已有文件，点「开始打包」会先询问是否删除。",
                tone=Tone.WARNING,
            )
        )

    return widgets.surface(
        content=ft.Column(
            spacing=T.SPACE_XS,
            tight=True,
            controls=[
                ft.Row(
                    spacing=T.SPACE_SM,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Icon(ft.Icons.ROCKET_LAUNCH_OUTLINED, size=17, color=ft.Colors.PRIMARY),
                        ft.Text(plan.project_name, size=14, weight=ft.FontWeight.W_600),
                        ft.Container(expand=True),
                        _output_pill(state.output_state, occupied),
                    ],
                ),
                _path_row(ft.Icons.DESCRIPTION_OUTLINED, "源目录", plan.source),
                _path_row(
                    ft.Icons.INVENTORY_2_OUTLINED,
                    "产物目录",
                    plan.output,
                    tone=Tone.WARNING if occupied else Tone.NEUTRAL,
                ),
                ft.Row(
                    spacing=T.SPACE_SM,
                    wrap=True,
                    run_spacing=T.SPACE_SM,
                    controls=[
                        widgets.pill(
                            f"目标 {plan.target}", icon=ft.Icons.LAPTOP_WINDOWS, dense=True
                        ),
                        widgets.pill(
                            f"Python {plan.python_version}", icon=ft.Icons.CODE, dense=True
                        ),
                        widgets.pill(
                            f"artifact / product = {plan.project_name}",
                            icon=ft.Icons.LABEL_OUTLINE,
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


def _output_pill(stats: TreeStats | None, occupied: bool) -> ft.Control:
    if occupied and stats is not None:
        return widgets.pill(
            f"已有 {stats.files} 个文件（{human_bytes(stats.bytes)}）",
            tone=Tone.WARNING,
            icon=ft.Icons.FOLDER_OPEN,
            dense=True,
        )
    return widgets.pill(
        "产物目录为空" if stats is not None else "正在检查产物目录…",
        tone=Tone.SUCCESS if stats is not None else Tone.NEUTRAL,
        icon=ft.Icons.FOLDER_OPEN,
        dense=True,
    )


def _path_row(icon: str, label: str, value: str, *, tone: Tone = Tone.NEUTRAL) -> ft.Row:
    return ft.Row(
        spacing=T.SPACE_SM,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.Icon(icon, size=15, color=T.tone_style(tone).accent),
            ft.Text(label, size=12, color=T.MUTED_TEXT),
            ft.Text(
                value,
                size=12,
                expand=True,
                max_lines=1,
                overflow=ft.TextOverflow.ELLIPSIS,
                tooltip=value,
                selectable=True,
            ),
        ],
    )


def _command_panel(steps: tuple[str, ...]) -> ft.Control:
    if not steps:
        return widgets.surface(content=widgets.muted("选择项目后显示将要执行的命令", size=12))

    return widgets.surface(
        content=ft.Column(
            spacing=T.SPACE_XS,
            tight=True,
            controls=[
                ft.Row(
                    spacing=T.SPACE_SM,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Text("将要执行的步骤", size=13, weight=ft.FontWeight.W_600),
                        ft.Container(expand=True),
                        widgets.muted("可选中复制", size=11),
                    ],
                ),
                widgets.flat_panel(
                    ft.Column(
                        spacing=T.SPACE_XXS,
                        tight=True,
                        controls=[
                            ft.Text(
                                command,
                                size=11,
                                selectable=True,
                                font_family=T.FONT_FAMILY,
                                font_family_fallback=["Consolas", "monospace"],
                            )
                            for command in steps
                        ],
                    ),
                    padding=T.SPACE_MD,
                ),
            ],
        )
    )


def _outcome_row(state: BuildState, vm: BuildViewModel, page: ft.Page) -> ft.Control:
    outcome = state.outcome
    assert outcome is not None  # 由调用方保证
    return widgets.surface(
        padding=T.SPACE_MD,
        content=ft.Row(
            spacing=T.SPACE_SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                # hint_row 内部文本是 expand 的，必须套一层有界容器，
                # 否则在 Row 里拿到无界宽度约束会直接报渲染错误
                ft.Container(
                    expand=True,
                    content=widgets.hint_row(
                        ft.Icons.CHECK_CIRCLE_OUTLINE if outcome.ok else ft.Icons.ERROR_OUTLINE,
                        outcome.detail,
                        tone=Tone.SUCCESS if outcome.ok else Tone.DANGER,
                    ),
                ),
                *(
                    [
                        widgets.text_btn(
                            "打开产物目录",
                            icon=ft.Icons.FOLDER_OPEN,
                            on_click=lambda _: page.run_task(vm.reveal, outcome.output),
                            tone=Tone.PRIMARY,
                        )
                    ]
                    if outcome.output
                    else []
                ),
            ],
        ),
    )


def _console_panel(state: BuildState) -> ft.Control:
    return widgets.surface(
        expand=True,
        content=ft.Column(
            expand=True,
            spacing=T.SPACE_SM,
            controls=[
                ft.Row(
                    spacing=T.SPACE_SM,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Text("构建输出", size=13, weight=ft.FontWeight.W_600),
                        *(
                            [ft.ProgressRing(width=14, height=14, stroke_width=2)]
                            if state.running
                            else []
                        ),
                        ft.Container(expand=True),
                        *(
                            [widgets.pill(f"{state.console_lines} 行", dense=True)]
                            if state.console_lines
                            else []
                        ),
                        widgets.muted("! 开头的行来自 stderr；完整输出见日志", size=11),
                    ],
                ),
                *(
                    [widgets.hint_row(ft.Icons.PLAY_CIRCLE_OUTLINE, state.phase, tone=Tone.INFO)]
                    if state.phase
                    else []
                ),
                ft.Container(
                    expand=True,
                    border_radius=T.RADIUS_MD,
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
                    border=ft.Border.all(1, T.BORDER_COLOR),
                    padding=T.SPACE_MD,
                    content=ft.ListView(
                        expand=True,
                        auto_scroll=True,
                        controls=[
                            ft.Text(
                                state.console or "（等待输出…）",
                                size=11,
                                selectable=True,
                                font_family=T.FONT_FAMILY,
                                font_family_fallback=["Consolas", "monospace"],
                                color=T.MUTED_TEXT,
                            )
                        ],
                    ),
                ),
            ],
        ),
    )
