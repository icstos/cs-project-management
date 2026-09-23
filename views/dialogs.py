"""对话框构件。

都是纯函数：接收当前状态、返回 ``ft.AlertDialog``。
由持有状态的视图通过 ``ft.use_dialog`` 渲染，因此对话框内容会随状态实时刷新。
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import flet as ft

from core import theme as T
from models.dto import Permission, Project
from views import ui

_PERMISSION_HINT = "公开项目会在报表中标注为可共享；私有项目仅本机可见。"


@dataclass(frozen=True, slots=True)
class ProjectDraft:
    """项目表单的草稿状态。不可变，靠 ``replace`` 更新单个字段。"""

    project_id: int | None = None
    name: str = ""
    local_path: str = ""
    permission: Permission = Permission.PRIVATE

    @property
    def is_edit(self) -> bool:
        return self.project_id is not None

    @classmethod
    def blank(cls) -> ProjectDraft:
        return cls()

    @classmethod
    def from_project(cls, project: Project) -> ProjectDraft:
        return cls(
            project_id=project.id,
            name=project.name,
            local_path=project.local_path,
            permission=project.permission,
        )

    def with_fields(self, **changes: object) -> ProjectDraft:
        return replace(self, **changes)


def project_form_dialog(
    *,
    draft: ProjectDraft,
    error: str | None,
    saving: bool,
    on_change,
    on_pick_path,
    on_cancel,
    on_save,
) -> ft.AlertDialog:
    """新增 / 编辑项目。"""
    can_save = bool(draft.name.strip() and draft.local_path.strip()) and not saving
    return ft.AlertDialog(
        modal=True,
        title=ft.Row(
            spacing=T.SPACE_SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Container(
                    width=34,
                    height=34,
                    border_radius=T.RADIUS_MD,
                    bgcolor=ft.Colors.PRIMARY_CONTAINER,
                    alignment=ft.Alignment.CENTER,
                    content=ft.Icon(
                        ft.Icons.EDIT_OUTLINED if draft.is_edit else ft.Icons.ADD,
                        size=18,
                        color=ft.Colors.ON_PRIMARY_CONTAINER,
                    ),
                ),
                ft.Column(
                    spacing=0,
                    tight=True,
                    controls=[
                        ft.Text(
                            "编辑项目" if draft.is_edit else "添加项目",
                            size=18,
                            weight=ft.FontWeight.W_600,
                        ),
                        ui.muted(
                            "修改配置后会自动重新探测仓库状态"
                            if draft.is_edit
                            else "选择一个本地 Git 仓库纳入管理",
                            size=12,
                        ),
                    ],
                ),
            ],
        ),
        content=ft.Column(
            width=T.DIALOG_WIDTH,
            tight=True,
            spacing=T.FIELD_GAP,
            controls=[
                ft.TextField(
                    key="project-name",
                    label="项目名称",
                    hint_text="例如：cs-project-management",
                    value=draft.name,
                    autofocus=True,
                    border=T.field_border(),
                    on_change=lambda e: on_change(name=ui.event_value(e) or ""),
                    on_submit=lambda _: on_save() if can_save else None,
                ),
                ft.Row(
                    spacing=T.SPACE_SM,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.TextField(
                            key="project-path",
                            label="本地路径",
                            value=draft.local_path,
                            read_only=True,
                            expand=True,
                            border=T.field_border(),
                            hint_text="点击右侧「浏览」选择目录",
                        ),
                        ui.outlined(
                            "浏览",
                            icon=ft.Icons.FOLDER_OPEN,
                            on_click=on_pick_path,
                            disabled=saving,
                        ),
                    ],
                ),
                ft.Dropdown(
                    key="project-permission",
                    label="可见性",
                    value=draft.permission.value,
                    border=T.field_border(),
                    options=[
                        ft.dropdown.Option(Permission.PUBLIC.value, Permission.PUBLIC.label),
                        ft.dropdown.Option(Permission.PRIVATE.value, Permission.PRIVATE.label),
                    ],
                    on_select=lambda e: on_change(permission=Permission.parse(ui.event_value(e))),
                ),
                ui.hint_row(ft.Icons.INFO_OUTLINE, _PERMISSION_HINT),
                *([ui.inline_error(error)] if error else []),
            ],
        ),
        actions=[
            ui.text_btn("取消", on_click=on_cancel, disabled=saving),
            ui.filled(
                "保存中…" if saving else "保存",
                icon=ft.Icons.SAVE,
                on_click=on_save,
                disabled=not can_save,
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )


def delete_project_dialog(
    *,
    project: Project,
    on_confirm,
    on_cancel,
) -> ft.AlertDialog:
    return ui.confirm_dialog(
        title_text="删除项目",
        message=f"确定要从列表中移除「{project.name}」吗？",
        confirm_label="删除",
        on_confirm=on_confirm,
        on_cancel=on_cancel,
        extra=ui.flat_panel(
            ft.Column(
                spacing=T.SPACE_XS,
                tight=True,
                controls=[
                    ui.muted("仅移除台账记录，不会删除本地仓库或远程仓库。", size=12, max_lines=2),
                    ui.muted(project.local_path, size=11, max_lines=2),
                ],
            )
        ),
    )
