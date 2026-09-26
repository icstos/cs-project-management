"""提交视图：选择项目、查看实时变更、提交并（可选）推送。

与项目管理视图不同，这里每次切换项目都会重新探测一次工作区，
让用户在按下提交前就能确认"到底会提交哪些文件"。

注意：组件体里**不能**复用上一次渲染留下的控件并回写属性 —— Flet 会把已经
下发过的控件标记为 frozen，再赋值就会抛 ``RuntimeError``，而该异常会终结
会话的更新调度器（界面整体失去响应）。因此这里所有控件都随状态重建。
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import flet as ft

from core import theme as T
from models.dto import Change, ChangeKind, GitStatus, Project
from services.project_service import ProjectService
from views import ui
from views.guard import guarded

logger = logging.getLogger(__name__)

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
    # 用户是否手动拨过推送开关：没拨过就让开关跟随最新探测结果。
    # 数据库里缓存的 has_remote 可能已过期（刚加过远程、或远程被删掉）。
    push_touched, set_push_touched = ft.use_state(False)
    notice, set_notice = ft.use_state(None)
    committing, set_committing = ft.use_state(False)
    preview, set_preview = ft.use_state(None)
    preview_error, set_preview_error = ft.use_state(None)
    loading_preview, set_loading_preview = ft.use_state(False)

    selected = next((item for item in projects if item.id == selected_id), None)
    has_remote = _has_remote(selected, preview)
    will_push = push and has_remote

    # ------------------------------------------------------------------ 选择
    def choose(project: Project) -> None:
        set_selected_id(project.id)
        set_push_touched(False)
        set_push(project.has_remote)
        set_preview_error(None)
        set_notice(None)

    def ensure_selection() -> None:
        if not projects:
            if selected_id is not None:
                set_selected_id(None)
            return
        if any(project.id == selected_id for project in projects):
            return
        preferred = next((p for p in projects if p.has_local_changes), projects[0])
        set_selected_id(preferred.id)
        set_push_touched(False)
        set_push(preferred.has_remote)
        set_notice(None)

    ft.use_effect(ensure_selection, [projects])

    def toggle_push(value: bool) -> None:
        set_push(value)
        set_push_touched(True)

    async def load_preview() -> None:
        if selected_id is None:
            set_preview(None)
            return
        set_loading_preview(True)
        try:
            status = await service.preview(selected_id)
            set_preview(status)
            set_preview_error(None)
            if not push_touched:
                set_push(status.has_remote)
        except (ValueError, RuntimeError) as exc:
            logger.warning("预览提交内容失败（project_id=%s）：%s", selected_id, exc)
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
        set_notice(None)
        try:
            outcome = await service.commit(selected.id, message, push=will_push)
            set_message("")
            tone = T.Tone.SUCCESS if outcome.pushed or not will_push else T.Tone.WARNING
            ui.toast(page, outcome.detail, tone=tone)
            # 推送失败的原文可能很长，3 秒的浮层看不完，所以在面板里留一份
            set_notice((outcome.detail, tone))
            await refresh()
            await load_preview()
        except (ValueError, RuntimeError) as exc:
            logger.warning(
                "提交失败（project「%s」，push=%s）：%s",
                selected.name,
                will_push,
                exc,
            )
            ui.toast(page, str(exc), tone=T.Tone.DANGER)
            set_notice((str(exc), T.Tone.DANGER))
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
                        will_push=will_push,
                        has_remote=has_remote,
                        on_push=toggle_push,
                        notice=notice,
                        committing=committing,
                    ),
                ),
            ],
        ),
    )


# --------------------------------------------------------------------------- 构件
def _has_remote(selected: Project | None, preview: GitStatus | None) -> bool:
    """是否配置了远程仓库，**以实时探测为准**。

    数据库里缓存的值可能已经过期：用户在仓库目录手工加过远程、或把远程删了。
    订阅缓存的后果是开关被永久锁死（明明有远程却推不了）。
    """
    if preview is not None:
        return preview.has_remote
    return bool(selected and selected.has_remote)


def _notice_row(text: str, tone: T.Tone) -> ft.Control:
    """最近一次提交/推送的结果。浮层只活 3 秒，失败原因得在界面上留一份。"""
    icon = ft.Icons.CHECK_CIRCLE_OUTLINE if tone is T.Tone.SUCCESS else ft.Icons.ERROR_OUTLINE
    return ui.surface(
        padding=T.SPACE_MD,
        content=ui.hint_row(icon, text, tone=tone),
    )


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
    will_push: bool,
    has_remote: bool,
    on_push,
    notice: tuple[str, T.Tone] | None,
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
            *([_notice_row(*notice)] if notice else []),
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
                                            label="推送到所有远程",
                                            value=will_push,
                                            on_change=lambda e: on_push(bool(ui.event_value(e))),
                                            disabled=committing or not has_remote,
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
                                            if not has_remote
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
                                            if will_push
                                            else "仅提交",
                                            icon=ft.Icons.UPLOAD,
                                            disabled=not can_submit,
                                            on_click=on_submit,
                                        ),
                                    ],
                                ),
                            ],
                        ),
                        *(
                            [
                                ui.hint_row(
                                    ft.Icons.CLOUD_OFF,
                                    "该仓库没有配置任何远程仓库，提交后无处可推。"
                                    "可在仓库目录执行 git remote add origin <地址>，"
                                    "再点右上角「重新探测」。",
                                    tone=T.Tone.WARNING,
                                )
                            ]
                            if not has_remote
                            else []
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
                            "已配置远程",
                            bool(status.has_remote if status else project.has_remote),
                            bad_label="未配置远程",
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
