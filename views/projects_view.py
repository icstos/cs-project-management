import flet as ft

from models.database import Permission, Project
from services.project_service import ProjectService
from views.ui_helpers import (
    danger_button,
    empty_state,
    format_datetime,
    icon_action_button,
    page_container,
    permission_badge,
    primary_button,
    secondary_button,
    section_header,
    show_snack,
    local_changes_chip,
    status_chip,
    surface_card,
    text_button,
)


@ft.component
def ProjectCard(project: Project, on_edit, on_delete, on_refresh):
    return surface_card(
        ft.Column(
            spacing=12,
            controls=[
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Column(
                            spacing=4,
                            expand=True,
                            controls=[
                                ft.Text(
                                    project.name,
                                    size=18,
                                    weight=ft.FontWeight.W_600,
                                ),
                                ft.Text(
                                    project.local_path,
                                    size=12,
                                    color=ft.Colors.ON_SURFACE_VARIANT,
                                    max_lines=2,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                ),
                            ],
                        ),
                        permission_badge(project.permission),
                    ],
                ),
                ft.Row(
                    spacing=8,
                    wrap=True,
                    run_spacing=8,
                    controls=[
                        status_chip("已配置远程", project.has_remote),
                        local_changes_chip(project.has_local_changes),
                        status_chip("含 .gitignore", project.has_gitignore),
                    ],
                ),
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Text(
                            f"更新于 {format_datetime(project.updated_at)}",
                            size=11,
                            color=ft.Colors.OUTLINE,
                        ),
                        ft.Row(
                            spacing=4,
                            controls=[
                                icon_action_button(
                                    ft.Icons.REFRESH,
                                    "刷新 Git 状态",
                                    lambda _: on_refresh(project),
                                ),
                                icon_action_button(
                                    ft.Icons.EDIT_OUTLINED,
                                    "编辑",
                                    lambda _: on_edit(project),
                                ),
                                icon_action_button(
                                    ft.Icons.DELETE_OUTLINE,
                                    "删除",
                                    lambda _: on_delete(project),
                                    danger=True,
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        ),
        key=f"project-{project.id}",
    )


@ft.component
def ProjectsView(on_projects_changed):
    page = ft.context.page
    projects, set_projects = ft.use_state([])
    loading, set_loading = ft.use_state(True)
    refreshing, set_refreshing = ft.use_state(False)
    dialog_mode, set_dialog_mode = ft.use_state(None)
    deleting_project, set_deleting_project = ft.use_state(None)

    name, set_name = ft.use_state("")
    local_path, set_local_path = ft.use_state("")
    permission, set_permission = ft.use_state(Permission.PRIVATE.value)
    saving, set_saving = ft.use_state(False)

    editing = dialog_mode if isinstance(dialog_mode, Project) else None
    form_open = dialog_mode is not None

    def sync_form_from_mode():
        if dialog_mode == "create":
            set_name("")
            set_local_path("")
            set_permission(Permission.PRIVATE.value)
        elif isinstance(dialog_mode, Project):
            set_name(dialog_mode.name)
            set_local_path(dialog_mode.local_path)
            set_permission(dialog_mode.permission)

    ft.use_effect(sync_form_from_mode, [dialog_mode])

    async def load_projects(refresh_git: bool = True):
        set_loading(True)
        try:
            if refresh_git:
                updated = await ProjectService.refresh_all_git_status()
                set_projects(updated)
            else:
                set_projects(ProjectService.get_all())
        except Exception as exc:
            set_projects(ProjectService.get_all())
            show_snack(page, f"刷新状态失败: {exc}", error=True)
        finally:
            set_loading(False)
            await on_projects_changed(refresh_git=False)

    def bootstrap():
        page.run_task(load_projects)

    ft.use_effect(bootstrap, [])

    async def pick_directory(_):
        picker = ft.FilePicker()
        page.services.append(picker)
        page.update()
        selected = await picker.get_directory_path(dialog_title="选择项目目录")
        if selected:
            set_local_path(selected)

    async def handle_save(_):
        if not name.strip():
            show_snack(page, "请填写项目名称", error=True)
            return
        if not local_path.strip():
            show_snack(page, "请选择本地路径", error=True)
            return

        set_saving(True)
        try:
            perm = Permission(permission)
            if editing:
                ProjectService.update(editing.id, name, local_path, perm)
                show_snack(page, "项目已更新")
            else:
                ProjectService.create(name, local_path, perm)
                show_snack(page, "项目已添加")
            await load_projects()
            set_dialog_mode(None)
        except Exception as exc:
            show_snack(page, str(exc), error=True)
        finally:
            set_saving(False)

    async def refresh_one(project: Project):
        set_refreshing(True)
        try:
            updated = await ProjectService.refresh_git_status(project)
            set_projects(
                lambda items: [
                    updated if item.id == updated.id else item for item in items
                ]
            )
            show_snack(page, f"已刷新 {project.name}")
            await on_projects_changed(refresh_git=False)
        except Exception as exc:
            show_snack(page, str(exc), error=True)
        finally:
            set_refreshing(False)

    async def confirm_delete(_):
        if not deleting_project:
            return
        try:
            ProjectService.remove(deleting_project.id)
            set_projects(
                lambda items: [item for item in items if item.id != deleting_project.id]
            )
            show_snack(page, "项目已删除")
            set_deleting_project(None)
            await on_projects_changed(refresh_git=False)
        except Exception as exc:
            show_snack(page, str(exc), error=True)

    ft.use_dialog(
        ft.AlertDialog(
            modal=True,
            shape=ft.RoundedRectangleBorder(radius=16),
            title=ft.Text("编辑项目" if editing else "添加项目"),
            content=ft.Container(
                width=460,
                content=ft.Column(
                    tight=True,
                    spacing=14,
                    controls=[
                        ft.TextField(
                            label="项目名称",
                            value=name,
                            border_radius=10,
                            on_change=lambda e: set_name(e.control.value),
                        ),
                        ft.Row(
                            spacing=8,
                            controls=[
                                ft.TextField(
                                    label="本地路径",
                                    value=local_path,
                                    expand=True,
                                    read_only=True,
                                    border_radius=10,
                                ),
                                secondary_button(
                                    "浏览",
                                    icon=ft.Icons.FOLDER_OPEN,
                                    on_click=pick_directory,
                                ),
                            ],
                        ),
                        ft.Dropdown(
                            label="权限",
                            value=permission,
                            border_radius=10,
                            options=[
                                ft.dropdown.Option(
                                    Permission.PUBLIC.value, Permission.PUBLIC.label
                                ),
                                ft.dropdown.Option(
                                    Permission.PRIVATE.value, Permission.PRIVATE.label
                                ),
                            ],
                            on_select=lambda e: set_permission(e.control.value),
                        ),
                    ],
                ),
            ),
            actions=[
                text_button("取消", on_click=lambda _: set_dialog_mode(None)),
                primary_button(
                    "保存中..." if saving else "保存",
                    icon=ft.Icons.SAVE,
                    disabled=saving,
                    on_click=handle_save,
                ),
            ],
        )
        if form_open
        else None
    )

    ft.use_dialog(
        ft.AlertDialog(
            modal=True,
            shape=ft.RoundedRectangleBorder(radius=16),
            title=ft.Text("确认删除"),
            content=ft.Text(f"确定删除项目「{deleting_project.name}」吗？"),
            actions=[
                text_button("取消", on_click=lambda _: set_deleting_project(None)),
                danger_button(
                    "删除", icon=ft.Icons.DELETE_OUTLINE, on_click=confirm_delete
                ),
            ],
        )
        if deleting_project
        else None
    )

    return page_container(
        ft.Column(
            expand=True,
            spacing=20,
            controls=[
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    controls=[
                        section_header(
                            "项目管理", "维护本地 Git 项目，自动检测远程配置与变更状态"
                        ),
                        ft.Row(
                            spacing=10,
                            controls=[
                                secondary_button(
                                    "刷新全部",
                                    icon=ft.Icons.SYNC,
                                    disabled=loading or refreshing,
                                    on_click=lambda _: page.run_task(
                                        load_projects, True
                                    ),
                                ),
                                primary_button(
                                    "添加项目",
                                    icon=ft.Icons.ADD,
                                    on_click=lambda _: set_dialog_mode("create"),
                                ),
                            ],
                        ),
                    ],
                ),
                ft.ProgressRing(visible=loading)
                if loading
                else empty_state(
                    ft.Icons.FOLDER_OFF,
                    "暂无项目",
                    "点击「添加项目」开始管理你的 Git 仓库",
                )
                if not loading and not projects
                else ft.ListView(
                    expand=True,
                    spacing=12,
                    controls=[
                        ProjectCard(
                            project=project,
                            on_edit=lambda p: set_dialog_mode(p),
                            on_delete=lambda p: set_deleting_project(p),
                            on_refresh=lambda p: page.run_task(refresh_one, p),
                        )
                        for project in projects
                    ],
                ),
            ],
        ),
    )
