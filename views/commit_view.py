import flet as ft

from models.database import Project
from services.project_service import ProjectService
from views.ui_helpers import (
    empty_state,
    info_panel,
    page_container,
    primary_button,
    section_header,
    show_snack,
    local_changes_chip,
    status_chip,
)


@ft.component
def CommitView(projects: list[Project], on_projects_changed):
    page = ft.context.page
    selected_id, set_selected_id = ft.use_state(None)
    message, set_message = ft.use_state("")
    committing, set_committing = ft.use_state(False)

    selected = next((item for item in projects if item.id == selected_id), None)

    async def handle_commit():
        if selected_id is None:
            show_snack(page, "请先选择项目", error=True)
            return
        if not message.strip():
            show_snack(page, "请填写提交说明", error=True)
            return

        set_committing(True)
        try:
            await ProjectService.commit(selected_id, message.strip())
            set_message("")
            show_snack(page, "提交并推送成功")
            await on_projects_changed(refresh_git=True)
        except Exception as exc:
            show_snack(page, str(exc), error=True)
        finally:
            set_committing(False)

    return page_container(
        ft.Column(
            expand=True,
            spacing=20,
            controls=[
                section_header(
                    "项目提交",
                    "依次执行 git add .、git commit 与 git push-all，完成后自动更新变更状态",
                ),
                empty_state(
                    ft.Icons.INVENTORY_2_OUTLINED,
                    "还没有可提交的项目",
                    "请先在「项目管理」中添加 Git 仓库",
                )
                if not projects
                else ft.Container(
                    expand=True,
                    content=ft.Column(
                        spacing=18,
                        controls=[
                            ft.Dropdown(
                                label="选择项目",
                                value=str(selected_id) if selected_id else None,
                                border_radius=10,
                                options=[
                                    ft.dropdown.Option(str(item.id), item.name)
                                    for item in projects
                                ],
                                on_select=lambda e: set_selected_id(int(e.control.value)),
                            ),
                            ft.TextField(
                                label="提交说明",
                                hint_text="例如：修复登录问题、更新依赖版本",
                                value=message,
                                min_lines=3,
                                max_lines=5,
                                border_radius=10,
                                on_change=lambda e: set_message(e.control.value),
                            ),
                            info_panel(
                                ft.Column(
                                    spacing=10,
                                    controls=[
                                        ft.Row(
                                            spacing=8,
                                            controls=[
                                                ft.Icon(
                                                    ft.Icons.FOLDER,
                                                    size=16,
                                                    color=ft.Colors.PRIMARY,
                                                ),
                                                ft.Text(
                                                    selected.local_path if selected else "",
                                                    size=12,
                                                    color=ft.Colors.ON_SURFACE_VARIANT,
                                                    expand=True,
                                                ),
                                            ],
                                        ),
                                        ft.Row(
                                            spacing=8,
                                            wrap=True,
                                            run_spacing=8,
                                            controls=[
                                                status_chip(
                                                    "已配置远程",
                                                    selected.has_remote if selected else False,
                                                ),
                                                local_changes_chip(
                                                    selected.has_local_changes if selected else False
                                                ),
                                                status_chip(
                                                    "含 .gitignore",
                                                    selected.has_gitignore if selected else False,
                                                ),
                                            ],
                                        ),
                                    ],
                                ),
                            )
                            if selected is not None
                            else ft.Container(),
                            ft.Row(
                                controls=[
                                    primary_button(
                                        "提交中..." if committing else "提交并推送",
                                        icon=ft.Icons.UPLOAD,
                                        disabled=committing or selected_id is None,
                                        on_click=lambda _: page.run_task(handle_commit),
                                    ),
                                ]
                            ),
                        ],
                    ),
                ),
            ],
        ),
    )
