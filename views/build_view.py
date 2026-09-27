"""打包视图：把项目文件夹里的 Flet 程序构建成 Windows 程序。

执行顺序刻意做成"先体检、再确认、后施工"：

1. 点开始 → 先统计产物目录，若已有文件就弹窗问是否删除；
2. 删除失败（文件被占用）单独弹窗，给出具体被阻塞的路径与处理建议；
3. 确认后先在源目录跑 ``flet clean`` 清掉上次构建的残留，再跑 ``flet build``；
4. 命令、退出码、耗时与完整输出全部落日志（见 ``core.proc``）。

控制台按固定间隔合并刷新：构建输出动辄上千行，每来一行就重渲染一次会把界面拖垮；
被截掉的部分在日志文件里有完整记录，控制台只负责"看得见正在发生什么"。

注意：组件体里不能复用上一次渲染留下的控件并回写属性（Flet 会把已下发的控件
标记为 frozen），所以这里所有控件都随状态重建。切页签会卸载本组件，正在进行的
构建不会中断（它跑在会话级任务里），但控制台内容会丢失。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import flet as ft

from core import fs
from core import theme as T
from core.config import BUILD_OUTPUT_ROOT
from models.dto import BuildOutcome, BuildPlan, Project
from services.build_service import BuildService, Readiness, describe
from views import ui
from views.dialogs import OutputConflict, output_conflict_dialog, output_locked_dialog
from views.guard import guarded

logger = logging.getLogger(__name__)

_PANE_WIDTH = 320
#: 控制台保留的行数。再多就开始拖慢重绘，完整输出以日志文件为准。
_CONSOLE_KEEP = 250
#: 输出合并刷新的间隔（秒）
_FLUSH_SECONDS = 0.4


@guarded
def BuildView(
    *,
    projects: list[Project],
    service: BuildService,
    busy: bool,
):
    page = ft.context.page

    selected_id, set_selected_id = ft.use_state(None)
    phase, set_phase = ft.use_state("")
    console, set_console = ft.use_state("")
    running, set_running = ft.use_state(False)
    outcome, set_outcome = ft.use_state(None)
    conflict, set_conflict = ft.use_state(None)
    failure, set_failure = ft.use_state(None)
    flet_info, set_flet_info = ft.use_state(None)
    output_state, set_output_state = ft.use_state(None)

    # 缓冲与节流标志不能进 state：它们的每次变化都会触发重渲染，正是要避免的事
    buffer = ft.use_ref(list).current
    gate = ft.use_ref(lambda: {"pending": False, "task": None}).current

    selected = next((item for item in projects if item.id == selected_id), None)
    plan = service.plan(selected) if selected is not None else None
    readiness = service.precheck(plan) if plan is not None else Readiness()
    flet_ok = True if flet_info is None else bool(flet_info[0])
    can_start = (
        plan is not None and readiness.issue is None and flet_ok and not running and not busy
    )

    # ------------------------------------------------------------------ 选择
    def ensure_selection() -> None:
        if not projects:
            if selected_id is not None:
                set_selected_id(None)
            return
        if any(item.id == selected_id for item in projects):
            return
        set_selected_id(projects[0].id)

    ft.use_effect(ensure_selection, [projects])

    def choose(project: Project) -> None:
        if running or project.id == selected_id:
            return
        logger.debug("打包页切换到项目「%s」", project.name)
        set_selected_id(project.id)
        set_outcome(None)
        set_conflict(None)
        set_failure(None)
        set_phase("")
        buffer.clear()
        set_console("")

    # ------------------------------------------------------------------ 探测
    async def probe_flet() -> None:
        try:
            set_flet_info(await service.probe())
        except Exception as exc:  # 探测本身失败也不该让整页渲染不出来
            logger.exception("探测 flet CLI 失败")
            set_flet_info((False, str(exc)))

    ft.use_effect(probe_flet, [])

    async def load_output() -> None:
        if plan is None:
            set_output_state(None)
            return
        try:
            set_output_state(await service.inspect(plan.output))
        except Exception:
            logger.exception("统计产物目录失败：%s", plan.output)
            set_output_state(None)

    ft.use_effect(load_output, [selected_id])

    # ------------------------------------------------------------------ 控制台
    def console_text() -> str:
        if not buffer:
            return "（等待输出…）"
        return "\n".join(f"! {line}" if stream == "err" else line for stream, line in buffer)

    async def flush_console() -> None:
        await asyncio.sleep(_FLUSH_SECONDS)
        gate["pending"] = False
        set_console(console_text())

    def append_line(stream: str, line: str) -> None:
        buffer.append((stream, line))
        if len(buffer) > _CONSOLE_KEEP:
            del buffer[: len(buffer) - _CONSOLE_KEEP]
        if not gate["pending"]:
            gate["pending"] = True
            page.run_task(flush_console)

    # ------------------------------------------------------------------ 主流程
    def start(_=None) -> None:
        if not can_start:
            if readiness.issue:
                ui.toast(page, readiness.issue, tone=T.Tone.DANGER)
            return
        set_conflict(None)
        set_failure(None)
        set_outcome(None)
        set_phase("检查产物目录…")
        page.run_task(inspect_then_start)

    async def inspect_then_start() -> None:
        if plan is None:
            return
        try:
            stats = await service.inspect(plan.output)
        except Exception as exc:
            logger.exception("统计产物目录失败：%s", plan.output)
            set_phase("")
            ui.toast(page, f"无法读取产物目录：{exc}", tone=T.Tone.DANGER)
            return

        set_output_state(stats)
        if stats.empty:
            launch_task()
            return

        logger.info(
            "产物目录已有 %d 个文件（%s），等待确认删除：%s",
            stats.files,
            fs.human_bytes(stats.bytes),
            plan.output,
        )
        set_phase("产物目录非空，等待确认…")
        set_conflict(
            OutputConflict(
                path=plan.output,
                files=stats.files,
                size=fs.human_bytes(stats.bytes),
                top=stats.top,
            )
        )

    def launch_task() -> None:
        gate["task"] = page.run_task(launch)

    async def launch() -> None:
        if plan is None:
            return
        set_conflict(None)
        set_running(True)
        set_outcome(None)
        set_failure(None)
        buffer.clear()
        set_console("")
        set_phase("准备打包…")

        result: BuildOutcome
        try:
            result = await service.run(plan, on_line=append_line, on_phase=set_phase)
        except asyncio.CancelledError:
            # 是我们自己发起的终止，子进程已在 core.proc 里被杀掉，这里只做收尾
            logger.warning("打包被终止：%s", plan.source)
            result = BuildOutcome(
                ok=False, detail="已终止打包（构建进程已结束）", output=plan.output
            )
        except Exception as exc:
            logger.exception("打包过程中出现未预期异常（%s）", plan.source)
            result = BuildOutcome(ok=False, detail=f"打包异常：{exc}", output=plan.output)
        finally:
            set_running(False)
            gate["pending"] = False
            set_console(console_text())

        set_phase("")
        set_outcome(result)
        ui.toast(page, result.detail, tone=T.Tone.SUCCESS if result.ok else T.Tone.DANGER)
        if result.ok:
            set_output_state(await service.inspect(plan.output))

    def stop(_=None) -> None:
        handle = gate.get("task")
        if handle is not None and not handle.done():
            logger.info("用户请求终止打包")
            handle.cancel()

    async def remove_then_build() -> None:
        if plan is None:
            return
        set_phase("删除已有产物…")
        try:
            report = await service.purge(plan.output)
        except Exception as exc:
            logger.exception("删除产物目录异常：%s", plan.output)
            set_phase("")
            ui.toast(page, f"删除失败：{exc}", tone=T.Tone.DANGER)
            return

        if not report.ok:
            blocker = report.first_blocker
            logger.warning(
                "产物目录未能删净：%s（剩余 %d 个文件，首个阻塞 %s）",
                plan.output,
                report.total - report.removed,
                blocker.path if blocker else "未知",
            )
            set_phase("")
            set_failure(
                (
                    plan.output,
                    blocker.reason if blocker else "目录仍然存在，可能被其他程序占用",
                    blocker.path if blocker else "",
                    max(report.total - report.removed, 0),
                )
            )
            return

        set_output_state(await service.inspect(plan.output))
        launch_task()

    def confirm_remove(_=None) -> None:
        page.run_task(remove_then_build)

    def retry_remove(_=None) -> None:
        set_failure(None)
        page.run_task(remove_then_build)

    def cancel_conflict(_=None) -> None:
        set_conflict(None)
        set_phase("")

    def open_dir(path: str) -> None:
        ok, reason = service.open_target(path)
        if not ok:
            ui.toast(page, reason, tone=T.Tone.DANGER)

    # ------------------------------------------------------------------ 弹窗
    ft.use_dialog(
        output_conflict_dialog(
            conflict=conflict,
            on_confirm=confirm_remove,
            on_cancel=cancel_conflict,
        )
        if conflict is not None
        else None
    )
    ft.use_dialog(
        output_locked_dialog(
            path=failure[0],
            reason=failure[1],
            blocked_path=failure[2],
            remaining=failure[3],
            on_retry=retry_remove,
            on_close=lambda _=None: set_failure(None),
        )
        if failure is not None
        else None
    )

    # ------------------------------------------------------------------ 渲染
    if not projects:
        return ui.page_shell(
            header=ui.page_header(
                "打包发布",
                "把项目文件夹里的 Flet 程序构建成 Windows 程序并输出到发布目录",
            ),
            body=ui.empty_state(
                ft.Icons.ROCKET_LAUNCH_OUTLINED,
                "还没有可打包的项目",
                "请先在「项目」中添加本地 Flet 项目",
            ),
        )

    return ui.page_shell(
        header=ui.page_header(
            "打包发布",
            "先在项目目录执行 flet clean，再构建到发布目录；命令与输出全程记录",
            actions=[
                *(
                    [
                        ui.outlined(
                            "终止",
                            icon=ft.Icons.STOP_CIRCLE_OUTLINED,
                            on_click=stop,
                        )
                    ]
                    if running
                    else [
                        ui.filled(
                            "开始打包",
                            icon=ft.Icons.ROCKET_LAUNCH,
                            disabled=not can_start,
                            on_click=start,
                        )
                    ]
                ),
                ui.outlined(
                    "打开发布目录",
                    icon=ft.Icons.FOLDER_OPEN,
                    disabled=running,
                    on_click=lambda _=None: open_dir(str(BUILD_OUTPUT_ROOT)),
                ),
            ],
        ),
        body=ft.Row(
            expand=True,
            spacing=T.SPACE_MD,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[
                ft.Container(
                    width=_PANE_WIDTH,
                    content=_project_pane(projects, selected_id, service, choose, locked=running),
                ),
                ft.Container(
                    expand=True,
                    content=ft.Column(
                        expand=True,
                        spacing=T.SPACE_MD,
                        controls=[
                            _target_panel(
                                plan=plan,
                                readiness=readiness,
                                output_state=output_state,
                                flet_info=flet_info,
                            ),
                            _command_panel(plan),
                            *(
                                [_outcome_row(outcome, on_open=open_dir)]
                                if outcome is not None
                                else []
                            ),
                            _console_panel(
                                console=console,
                                phase=phase,
                                running=running,
                                lines=len(buffer),
                            ),
                        ],
                    ),
                ),
            ],
        ),
    )


# --------------------------------------------------------------------------- 构件
def _project_pane(
    projects: list[Project],
    selected_id: int | None,
    service: BuildService,
    choose,
    *,
    locked: bool,
) -> ft.Control:
    return ui.surface(
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
                            ui.pill(str(len(projects)), dense=True),
                        ]
                    ),
                ),
                ft.ListView(
                    expand=True,
                    spacing=T.SPACE_XXS,
                    controls=[
                        _project_tile(
                            project,
                            service.plan(project),
                            active=project.id == selected_id,
                            on_click=choose,
                            locked=locked,
                        )
                        for project in projects
                    ],
                ),
            ],
        ),
    )


def _project_tile(
    project: Project,
    plan: BuildPlan,
    *,
    active: bool,
    on_click,
    locked: bool,
) -> ft.Container:
    tone = T.tone_style(T.Tone.PRIMARY)
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
                ui.muted(plan.output_name, size=11),
            ],
        ),
    )


def _target_panel(
    *,
    plan: BuildPlan | None,
    readiness: Readiness,
    output_state: fs.TreeStats | None,
    flet_info: tuple[bool, str] | None,
) -> ft.Control:
    if plan is None:
        return ui.surface(
            content=ui.hint_row(ft.Icons.TOUCH_APP, "请选择左侧的项目", tone=T.Tone.NEUTRAL)
        )

    occupied = output_state is not None and not output_state.empty
    template_ok = Path(plan.template).is_dir()

    notes: list[ft.Control] = []
    if readiness.issue:
        notes.append(ui.inline_error(readiness.issue))
    notes.extend(
        ui.hint_row(ft.Icons.WARNING_AMBER_ROUNDED, text, tone=T.Tone.WARNING)
        for text in readiness.warnings
    )
    if flet_info is not None and not flet_info[0]:
        notes.append(
            ui.hint_row(
                ft.Icons.ERROR_OUTLINE, f"未找到 flet 命令：{flet_info[1]}", tone=T.Tone.DANGER
            )
        )
    if occupied:
        # 提示要点到"会先问一句"为止：具体问什么、删多少，留给弹窗说
        notes.append(
            ui.hint_row(
                ft.Icons.INFO_OUTLINE,
                "产物目录里已有文件，点「开始打包」会先询问是否删除。",
                tone=T.Tone.WARNING,
            )
        )

    return ui.surface(
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
                        *(
                            [
                                ui.pill(
                                    f"已有 {output_state.files} 个文件"
                                    f"（{fs.human_bytes(output_state.bytes)}）",
                                    tone=T.Tone.WARNING,
                                    icon=ft.Icons.FOLDER_OPEN,
                                    dense=True,
                                )
                            ]
                            if occupied
                            else [
                                ui.pill(
                                    "产物目录为空"
                                    if output_state is not None
                                    else "正在检查产物目录…",
                                    tone=(
                                        T.Tone.SUCCESS
                                        if output_state is not None
                                        else T.Tone.NEUTRAL
                                    ),
                                    icon=ft.Icons.FOLDER_OPEN,
                                    dense=True,
                                )
                            ]
                        ),
                    ],
                ),
                _path_row(ft.Icons.DESCRIPTION_OUTLINED, "源目录", plan.source),
                _path_row(
                    ft.Icons.INVENTORY_2_OUTLINED,
                    "产物目录",
                    plan.output,
                    tone=T.Tone.WARNING if occupied else T.Tone.NEUTRAL,
                ),
                ft.Row(
                    spacing=T.SPACE_SM,
                    wrap=True,
                    run_spacing=T.SPACE_SM,
                    controls=[
                        ui.pill(f"目标 {plan.target}", icon=ft.Icons.LAPTOP_WINDOWS, dense=True),
                        ui.pill(f"Python {plan.python_version}", icon=ft.Icons.CODE, dense=True),
                        ui.pill(
                            f"artifact / product = {plan.project_name}",
                            icon=ft.Icons.LABEL_OUTLINE,
                            dense=True,
                        ),
                        ui.flag_pill(
                            "模板目录就绪",
                            template_ok,
                            bad_label="模板目录缺失",
                            bad_tone=T.Tone.DANGER,
                        ),
                    ],
                ),
                *notes,
            ],
        )
    )


def _path_row(icon: str, label: str, value: str, *, tone: T.Tone = T.Tone.NEUTRAL) -> ft.Row:
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


def _command_panel(plan: BuildPlan | None) -> ft.Control:
    if plan is None:
        return ui.surface(content=ui.muted("选择项目后显示将要执行的命令", size=12))

    steps = [
        # 第 0 步不是命令，却是"残留为什么能被清掉"的关键：flet 会连 .git 一起复制进
        # build/，那些只读 object 靠 flet clean 的裸 rmtree 删不掉（WinError 5），
        # 所以先由程序自己删一遍。列出来，界面才和实际流程对得上。
        f"0) 删除 {plan.build_dir}（内置步骤，只读文件也删得掉）",
        "1) " + " ".join(plan.clean_command()),
        "2) " + describe(plan),
    ]
    return ui.surface(
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
                        ui.muted("可选中复制", size=11),
                    ],
                ),
                ui.flat_panel(
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


def _outcome_row(outcome: BuildOutcome, *, on_open) -> ft.Control:
    tone = T.Tone.SUCCESS if outcome.ok else T.Tone.DANGER
    return ui.surface(
        padding=T.SPACE_MD,
        content=ft.Row(
            spacing=T.SPACE_SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                # hint_row 内部文本是 expand 的，必须套一层有界容器，
                # 否则在 Row 里拿到无界宽度约束会直接报渲染错误
                ft.Container(
                    expand=True,
                    content=ui.hint_row(
                        ft.Icons.CHECK_CIRCLE_OUTLINE if outcome.ok else ft.Icons.ERROR_OUTLINE,
                        outcome.detail,
                        tone=tone,
                    ),
                ),
                *(
                    [
                        ui.text_btn(
                            "打开产物目录",
                            icon=ft.Icons.FOLDER_OPEN,
                            on_click=lambda _=None: on_open(outcome.output),
                            tone=T.Tone.PRIMARY,
                        )
                    ]
                    if outcome.output
                    else []
                ),
            ],
        ),
    )


def _console_panel(*, console: str, phase: str, running: bool, lines: int) -> ft.Control:
    return ui.surface(
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
                            if running
                            else []
                        ),
                        ft.Container(expand=True),
                        *([ui.pill(f"{lines} 行", dense=True)] if lines else []),
                        ui.muted("! 开头的行来自 stderr；完整输出见日志", size=11),
                    ],
                ),
                *(
                    [ui.hint_row(ft.Icons.PLAY_CIRCLE_OUTLINE, phase, tone=T.Tone.INFO)]
                    if phase
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
                                console or "（等待输出…）",
                                size=11,
                                selectable=True,
                                font_family=T.FONT_FAMILY,
                                font_family_fallback=["Consolas", "monospace"],
                                color=ft.Colors.ON_SURFACE_VARIANT,
                            )
                        ],
                    ),
                ),
            ],
        ),
    )
