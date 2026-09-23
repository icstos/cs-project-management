"""提交视图：选择项目、查看实时变更、提交并（可选）推送。

与项目管理视图不同，这里每次切换项目都会重新探测一次工作区，
让用户在按下提交前就能确认"到底会提交哪些文件"。

注意：组件体里**不能**复用上一次渲染留下的控件并回写属性 —— Flet 会把已经
下发过的控件标记为 frozen，再赋值就会抛 ``RuntimeError``，而该异常会终结
会话的更新调度器（界面整体失去响应）。因此这里所有控件都随状态重建。
"""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from core import theme as T
from models.dto import Change, ChangeKind, GitStatus, Project
from services.project_service import ProjectService
from views import ui
from views.guard import guarded

_PANE_WIDTH = 320
_CHANGE_ICON_TONES: dict[ChangeKind, T.Tone] = {
    ChangeKind.ADDED: T.Tone.SUCCESS,
    ChangeKind.UNTRACKED: T.Tone.SUCCESS,
    ChangeKind.DELETED: T.Tone.DANGER,
    ChangeKind.CONFLICT: T.Tone.DANGER,
    ChangeKind.MODIFIED: T.Tone.WARNING,
    ChangeKind.RENAMED: T.Tone.WARNING,
    ChangeKind.TYPE_CHANGED: T.Tone.WARNING,
}


@guarded
def CommitView(
    *,
    projects: list[Project],
    service: ProjectService,
    busy: bool,
    refresh: Callable[..., object],
):
    page = ft.context.page

    selected_id, set_selected_id = ft.use_state(None)
    message, set_message = ft.use_state("")
    push, set_push = ft.use_state(True)
    committing, set_committing = ft.use_state(False)
    preview, set_preview = ft.use_state(None)
    preview_error, set_preview_error = ft.use_state(None)
    loading_preview, set_loading_preview = ft.use_state(False)

    selected = next((item for item in projects if item.id == selected_id), None)

    # ------------------------------------------------------------------ 选择
    def choose(project: Project) -> None:
        set_selected_id(project.id)
        set_push(project.has_remote)
        set_preview_error(None)

    def ensure_selection() -> None:
        if not projects:
            if selected_id is not None:
                set_selected_id(None)
            return
        if any(project.id == selected_id for project in projects):
            return
        preferred = next((p for p in projects if p.has_local_changes), projects[0])
        set_selected_id(preferred.id)
        set_push(preferred.has_remote)

    ft.use_effect(ensure_selection, [projects])

    async def load_preview() -> None:
        if selected_id is None:
            set_preview(None)
            return
        set_loading_preview(True)
        try:
            set_preview(await service.preview(selected_id))
            set_preview_error(None)
        except (ValueError, RuntimeError) as exc:
            set_preview(None)
            set_preview_error(str(exc))
        finally:
            set_loading_preview(False)

    ft.use_effect(load_preview, [selected_id])

    # ------------------------------------------------------------------ 提交
    async def submit() -> None:
        if selected is None:
            ui.toast(page, "请先选择要提交的项目", tone=T.Tone.WARNING)
            return
        if not message.strip():
            ui.toast(page, "请填写提交说明", tone=T.Tone.WARNING)
            return

        set_committing(True)
        try:
            outcome = await service.commit(selected.id, message, push=push)
            set_message("")
            ui.toast(
                page,
                outcome.detail,
                tone=T.Tone.SUCCESS if outcome.pushed or not push else T.Tone.WARNING,
            )
            await refresh()
            await load_preview()
        except (ValueError, RuntimeError) as exc:
            ui.toast(page, str(exc), tone=T.Tone.DANGER)
        finally:
            set_committing(False)

    if not projects:
        return ui.page_shell(
            header=ui.page_header(
                "提交与推送",
                "暂存全部变更、生成提交，并按需推送到远程仓库",
            ),
            body=ui.empty_state(
                ft.Icons.INVENTORY_2_OUTLINED,
                "还没有可提交的项目",
                "请先在「项目」中添加本地 Git 仓库",
            ),
        )

    return ui.page_shell(
        header=ui.page_header(
            "提交与推送",
            "暂存全部变更、生成提交，并按需推送到远程仓库",
            actions=[
                ui.outlined(
                    "重新探测",
                    icon=ft.Icons.REFRESH,
                    disabled=loading_preview or selected is None,
                    on_click=lambda _: page.run_task(load_preview),
                ),
            ],
        ),
        body=ft.Row(
            expand=True,
            spacing=T.SPACE_MD,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[
                ft.Container(
                    width=_PANE_WIDTH, content=_project_pane(projects, selected_id, choose)
                ),
                ft.Container(
                    expand=True,
                    content=_commit_pane(
                        selected=selected,
                        preview=preview,
                        preview_error=preview_error,
                        loading=loading_preview,
                        message=message,
                        on_message=set_message,
                        on_submit=lambda _: page.run_task(submit),
                        push=push,
                        on_push=set_push,
                        committing=committing,
                    ),
                ),
            ],
        ),
    )


# --------------------------------------------------------------------------- 构件
def _project_pane(projects: list[Project], selected_id: int | None, choose) -> ft.Control:
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
                        _project_tile(project, active=project.id == selected_id, on_click=choose)
                        for project in projects
                    ],
                ),
            ],
        ),
    )


def _project_tile(project: Project, *, active: bool, on_click) -> ft.Container:
    tone = T.tone_style(T.Tone.PRIMARY)
    return ft.Container(
        key=f"commit-project-{project.id}",
        on_click=lambda _: on_click(project),
        border_radius=T.RADIUS_MD,
        padding=ft.Padding.symmetric(horizontal=T.SPACE_MD, vertical=T.SPACE_SM),
        bgcolor=tone.container if active else ft.Colors.TRANSPARENT,
        border=ft.Border.all(1, tone.accent if active else ft.Colors.TRANSPARENT),
        content=ft.Column(
            spacing=T.SPACE_XXS,
            tight=True,
            controls=[
                ft.Row(
                    spacing=T.SPACE_SM,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Text(
                            project.name,
                            size=13,
                            weight=ft.FontWeight.W_600 if active else ft.FontWeight.W_500,
                            expand=True,
                            max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                        *(
                            [ui.pill(f"{project.changed_files}", tone=T.Tone.WARNING, dense=True)]
                            if project.changed_files
                            else []
                        ),
                    ],
                ),
                ui.muted(project.branch or "—", size=11),
            ],
        ),
    )


def _commit_pane(
    *,
    selected: Project | None,
    preview: GitStatus | None,
    preview_error: str | None,
    loading: bool,
    message: str,
    on_message,
    on_submit,
    push: bool,
    on_push,
    committing: bool,
) -> ft.Control:
    if selected is None:
        return ui.surface(
            expand=True,
            content=ui.empty_state(
                ft.Icons.TOUCH_APP,
                "请选择左侧的项目",
                "选中后可查看待提交文件并填写提交说明",
            ),
        )

    changes = preview.changes if preview else ()
    can_submit = bool(message.strip()) and not committing and bool(changes)

    return ft.Column(
        expand=True,
        spacing=T.SPACE_MD,
        controls=[
            _repo_panel(selected, preview, loading=loading, error=preview_error),
            ui.surface(
                expand=True,
                content=ft.Column(
                    expand=True,
                    spacing=T.SPACE_SM,
                    controls=[
                        ft.Row(
                            spacing=T.SPACE_SM,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                ft.Text("待提交变更", size=13, weight=ft.FontWeight.W_600),
                                ui.pill(f"{len(changes)} 个文件", dense=True),
                                ft.Container(expand=True),
                                ui.muted(
                                    " · ".join(
                                        f"{kind.label} {count}"
                                        for kind, count in _summarize(changes)
                                    ),
                                    size=11,
                                ),
                            ],
                        ),
                        ft.Container(
                            expand=True,
                            content=ft.ListView(
                                spacing=T.SPACE_XXS,
                                padding=ft.Padding.symmetric(vertical=T.SPACE_XXS),
                                controls=[_change_row(change) for change in changes]
                                or [
                                    ui.hint_row(
                                        ft.Icons.CHECK_CIRCLE_OUTLINE,
                                        "工作区干净，没有需要提交的变更",
                                        tone=T.Tone.SUCCESS,
                                    )
                                ],
                            ),
                        ),
                    ],
                ),
            ),
            ui.surface(
                content=ft.Column(
                    spacing=T.SPACE_SM,
                    tight=True,
                    controls=[
                        # 受控输入：文案的唯一来源是 message 状态，
                        # 因此控件每次渲染重建、不在渲染后回写属性。
                        ft.TextField(
                            key="commit-message",
                            label="提交说明",
                            hint_text="例如：修复登录跳转异常",
                            value=message,
                            multiline=True,
                            min_lines=4,
                            max_lines=8,
                            border=T.field_border(),
                            shift_enter=True,
                            on_change=lambda e: on_message(ui.event_value(e) or ""),
                            on_submit=on_submit,
                        ),
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                ft.Row(
                                    spacing=T.SPACE_SM,
                                    tight=True,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                    controls=[
                                        ft.Switch(
                                            label="推送到远程",
                                            value=push,
                                            on_change=lambda e: on_push(bool(ui.event_value(e))),
                                            disabled=committing or not selected.has_remote,
                                        ),
                                        *(
                                            [
                                                ui.pill(
                                                    "该仓库未配置远程",
                                                    tone=T.Tone.WARNING,
                                                    icon=ft.Icons.CLOUD_OFF,
                                                    dense=True,
                                                )
                                            ]
                                            if not selected.has_remote
                                            else []
                                        ),
                                    ],
                                ),
                                ft.Row(
                                    spacing=T.SPACE_SM,
                                    tight=True,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                    controls=[
                                        # shift_enter=True：Enter 提交、Shift+Enter 换行。
                                        # 多行输入框不会触发 on_submit，必须靠它。
                                        ui.key_hint("Enter 提交 · Shift+Enter 换行"),
                                        ui.filled(
                                            "提交中…"
                                            if committing
                                            else "提交并推送"
                                            if push
                                            else "仅提交",
                                            icon=ft.Icons.UPLOAD,
                                            disabled=not can_submit,
                                            on_click=on_submit,
                                        ),
                                    ],
                                ),
                            ],
                        ),
                    ],
                )
            ),
        ],
    )


def _repo_panel(
    project: Project,
    preview: GitStatus | None,
    *,
    loading: bool,
    error: str | None,
) -> ft.Control:
    status = preview
    branch = (status.branch if status else project.branch) or "—"

    return ui.surface(
        content=ft.Column(
            spacing=T.SPACE_SM,
            tight=True,
            controls=[
                ft.Row(
                    spacing=T.SPACE_SM,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Icon(ft.Icons.FOLDER, size=17, color=ft.Colors.PRIMARY),
                        ft.Text(project.name, size=14, weight=ft.FontWeight.W_600),
                        ui.permission_pill(project.permission),
                        ft.Container(expand=True),
                        ft.ProgressRing(width=16, height=16, stroke_width=2)
                        if loading
                        else ui.pill(
                            f"{status.change_count if status else project.changed_files} 个变更",
                            tone=(
                                T.Tone.WARNING
                                if (status.change_count if status else project.changed_files)
                                else T.Tone.SUCCESS
                            ),
                            dense=True,
                        ),
                    ],
                ),
                ui.muted(project.local_path, size=11, max_lines=1),
                ft.Row(
                    spacing=T.SPACE_SM,
                    wrap=True,
                    run_spacing=T.SPACE_SM,
                    controls=[
                        ui.pill(branch, icon=ft.Icons.ALT_ROUTE, dense=True),
                        *(
                            [ui.pill(status.upstream, icon=ft.Icons.CLOUD_DONE, dense=True)]
                            if status and status.upstream
                            else []
                        ),
                        *(
                            [
                                ui.pill(
                                    f"领先 {status.ahead}",
                                    tone=T.Tone.INFO,
                                    icon=ft.Icons.UPLOAD,
                                    dense=True,
                                )
                            ]
                            if status and status.ahead
                            else []
                        ),
                        *(
                            [
                                ui.pill(
                                    f"落后 {status.behind}",
                                    tone=T.Tone.WARNING,
                                    icon=ft.Icons.DOWNLOAD,
                                    dense=True,
                                )
                            ]
                            if status and status.behind
                            else []
                        ),
                        ui.flag_pill(
                            "已配置远程", bool(status.has_remote if status else project.has_remote)
                        ),
                    ],
                ),
                *([ui.inline_error(error)] if error else []),
            ],
        )
    )


def _change_row(change: Change) -> ft.Control:
    tone = _CHANGE_ICON_TONES.get(change.kind, T.Tone.NEUTRAL)
    style = T.tone_style(tone)
    return ft.Container(
        padding=ft.Padding.symmetric(horizontal=T.SPACE_SM, vertical=T.SPACE_XXS),
        border_radius=T.RADIUS_SM,
        content=ft.Row(
            spacing=T.SPACE_SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Container(
                    width=20,
                    height=20,
                    border_radius=T.RADIUS_SM,
                    bgcolor=style.container,
                    alignment=ft.Alignment.CENTER,
                    content=ft.Text(
                        change.kind.badge,
                        size=11,
                        weight=ft.FontWeight.BOLD,
                        color=style.on_container,
                    ),
                ),
                ft.Text(
                    change.path,
                    size=12,
                    expand=True,
                    max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS,
                    tooltip=change.path,
                ),
                ui.muted(change.kind.label, size=11),
            ],
        ),
    )


def _summarize(changes: tuple[Change, ...]) -> list[tuple[ChangeKind, int]]:
    counts: dict[ChangeKind, int] = {}
    for change in changes:
        counts[change.kind] = counts.get(change.kind, 0) + 1
    return sorted(counts.items(), key=lambda item: item[1], reverse=True)
