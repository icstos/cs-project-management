"""提交页：选择项目、查看实时变更、提交并（可选）推送。

每次切换项目都会让视图模型重新探测一次工作区，因此在按下提交之前，
界面上显示的待提交清单就是**即将提交**的内容。
"""

from __future__ import annotations

import flet as ft

from models.dtos import Change, Project
from models.enums import ChangeKind, Tone
from view import design as T
from view import widgets
from view.guard import guarded
from view.view_platform import FletPlatform, use_notices, use_platform_requests
from viewmodel.commit_vm import CommitState, CommitViewModel

_PANE_WIDTH = 320
_CHANGE_TONES: dict[ChangeKind, Tone] = {
    ChangeKind.ADDED: Tone.SUCCESS,
    ChangeKind.UNTRACKED: Tone.SUCCESS,
    ChangeKind.DELETED: Tone.DANGER,
    ChangeKind.CONFLICT: Tone.DANGER,
    ChangeKind.MODIFIED: Tone.WARNING,
    ChangeKind.RENAMED: Tone.WARNING,
    ChangeKind.TYPE_CHANGED: Tone.WARNING,
}


@guarded
def CommitView(*, vm: CommitViewModel, platform: FletPlatform) -> ft.Control:
    page = ft.context.page
    state = vm.state
    use_notices(page, vm)
    use_platform_requests(platform, vm)

    # 换项目就重新探测：这是"提交前能看到真实待提交内容"的关键
    ft.use_effect(lambda: page.run_task(vm.load_preview), [state.selected_id])

    if not state.projects:
        return widgets.page_shell(
            header=widgets.page_header(
                "提交与推送", "暂存全部变更、生成提交，并按需推送到远程仓库"
            ),
            body=widgets.empty_state(
                ft.Icons.INVENTORY_2_OUTLINED,
                "还没有可提交的项目",
                "请先在「项目」中添加本地 Git 仓库",
            ),
        )

    return widgets.page_shell(
        header=widgets.page_header(
            "提交与推送",
            "暂存全部变更、生成提交，并按需推送到远程仓库",
            actions=[
                widgets.outlined(
                    "重新探测",
                    icon=ft.Icons.REFRESH,
                    disabled=state.loading_preview or state.selected is None,
                    on_click=lambda _: page.run_task(vm.load_preview),
                ),
            ],
        ),
        body=ft.Row(
            expand=True,
            spacing=T.SPACE_MD,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[
                ft.Container(width=_PANE_WIDTH, content=_project_pane(state, vm, page)),
                ft.Container(expand=True, content=_commit_pane(state, vm, page)),
            ],
        ),
    )


# --------------------------------------------------------------------------- 构件
def _project_pane(state: CommitState, vm: CommitViewModel, page: ft.Page) -> ft.Control:
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
                            project, active=project.id == state.selected_id, vm=vm, page=page
                        )
                        for project in state.projects
                    ],
                ),
            ],
        ),
    )


def _project_tile(
    project: Project, *, active: bool, vm: CommitViewModel, page: ft.Page
) -> ft.Container:
    tone = T.tone_style(Tone.PRIMARY)
    return ft.Container(
        key=f"commit-project-{project.id}",
        on_click=lambda _: page.run_task(vm.choose, project),
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
                            [
                                widgets.pill(
                                    f"{project.changed_files}", tone=Tone.WARNING, dense=True
                                )
                            ]
                            if project.changed_files
                            else []
                        ),
                    ],
                ),
                widgets.muted(project.branch or "—", size=11),
            ],
        ),
    )


def _commit_pane(state: CommitState, vm: CommitViewModel, page: ft.Page) -> ft.Control:
    selected = state.selected
    if selected is None:
        return widgets.surface(
            expand=True,
            content=widgets.empty_state(
                ft.Icons.TOUCH_APP,
                "请选择左侧的项目",
                "选中后可查看待提交文件并填写提交说明",
            ),
        )

    changes = state.changes
    return ft.Column(
        expand=True,
        spacing=T.SPACE_MD,
        controls=[
            _repo_panel(state, selected),
            *([_notice_row(state)] if state.result else []),
            widgets.surface(
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
                                widgets.pill(f"{len(changes)} 个文件", dense=True),
                                ft.Container(expand=True),
                                widgets.muted(
                                    " · ".join(item.label for item in state.summaries), size=11
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
                                    widgets.hint_row(
                                        ft.Icons.CHECK_CIRCLE_OUTLINE,
                                        "工作区干净，没有需要提交的变更",
                                        tone=Tone.SUCCESS,
                                    )
                                ],
                            ),
                        ),
                    ],
                ),
            ),
            _composer(state, vm, page),
        ],
    )


def _notice_row(state: CommitState) -> ft.Control:
    """最近一次提交 / 推送的结果。浮层只活 3 秒，失败原因得在界面上留一份。"""
    result = state.result
    assert result is not None  # 由调用方保证
    icon = ft.Icons.CHECK_CIRCLE_OUTLINE if result.tone is Tone.SUCCESS else ft.Icons.ERROR_OUTLINE
    return widgets.surface(
        padding=T.SPACE_MD,
        content=widgets.hint_row(icon, result.detail, tone=result.tone),
    )


def _repo_panel(state: CommitState, project: Project) -> ft.Control:
    status = state.preview
    branch = (status.branch if status else project.branch) or "—"

    return widgets.surface(
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
                        widgets.permission_pill(project.permission),
                        ft.Container(expand=True),
                        ft.ProgressRing(width=16, height=16, stroke_width=2)
                        if state.loading_preview
                        else widgets.pill(
                            f"{state.change_count} 个变更",
                            tone=Tone.WARNING if state.change_count else Tone.SUCCESS,
                            dense=True,
                        ),
                    ],
                ),
                widgets.muted(project.local_path, size=11, max_lines=1),
                ft.Row(
                    spacing=T.SPACE_SM,
                    wrap=True,
                    run_spacing=T.SPACE_SM,
                    controls=[
                        widgets.pill(branch, icon=ft.Icons.ALT_ROUTE, dense=True),
                        *(
                            [widgets.pill(status.upstream, icon=ft.Icons.CLOUD_DONE, dense=True)]
                            if status and status.upstream
                            else []
                        ),
                        *(
                            [
                                widgets.pill(
                                    f"领先 {status.ahead}",
                                    tone=Tone.INFO,
                                    icon=ft.Icons.UPLOAD,
                                    dense=True,
                                )
                            ]
                            if status and status.ahead
                            else []
                        ),
                        *(
                            [
                                widgets.pill(
                                    f"落后 {status.behind}",
                                    tone=Tone.WARNING,
                                    icon=ft.Icons.DOWNLOAD,
                                    dense=True,
                                )
                            ]
                            if status and status.behind
                            else []
                        ),
                        widgets.flag_pill("已配置远程", state.has_remote, bad_label="未配置远程"),
                    ],
                ),
                *([widgets.inline_error(state.preview_error)] if state.preview_error else []),
            ],
        )
    )


def _composer(state: CommitState, vm: CommitViewModel, page: ft.Page) -> ft.Control:
    return widgets.surface(
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
                    value=state.message,
                    multiline=True,
                    min_lines=4,
                    max_lines=8,
                    border=T.field_border(),
                    shift_enter=True,
                    on_change=lambda e: vm.set_message(widgets.event_value(e) or ""),
                    on_submit=lambda _: page.run_task(vm.submit),
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
                                    value=state.will_push,
                                    on_change=lambda e: vm.toggle_push(
                                        bool(widgets.event_value(e))
                                    ),
                                    disabled=state.committing or not state.has_remote,
                                ),
                                *(
                                    [
                                        widgets.pill(
                                            "该仓库未配置远程",
                                            tone=Tone.WARNING,
                                            icon=ft.Icons.CLOUD_OFF,
                                            dense=True,
                                        )
                                    ]
                                    if not state.has_remote
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
                                widgets.key_hint("Enter 提交 · Shift+Enter 换行"),
                                widgets.filled(
                                    "提交中…"
                                    if state.committing
                                    else "提交并推送"
                                    if state.will_push
                                    else "仅提交",
                                    icon=ft.Icons.UPLOAD,
                                    disabled=not state.can_submit,
                                    on_click=lambda _: page.run_task(vm.submit),
                                ),
                            ],
                        ),
                    ],
                ),
                *(
                    [
                        widgets.hint_row(
                            ft.Icons.CLOUD_OFF,
                            "该仓库没有配置任何远程仓库，提交后无处可推。"
                            "可在仓库目录执行 git remote add origin <地址>，"
                            "再点右上角「重新探测」。",
                            tone=Tone.WARNING,
                        )
                    ]
                    if not state.has_remote
                    else []
                ),
            ],
        )
    )


def _change_row(change: Change) -> ft.Control:
    style = T.tone_style(_CHANGE_TONES.get(change.kind, Tone.NEUTRAL))
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
                widgets.muted(change.kind.label, size=11),
            ],
        ),
    )
