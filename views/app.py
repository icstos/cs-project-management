import flet as ft

from views.commit_view import CommitView
from views.projects_view import ProjectsView
from views.reports_view import ReportsView


@ft.component
def AppShell():
    page = ft.context.page
    tab_index, set_tab_index = ft.use_state(0)
    projects, set_projects = ft.use_state([])

    async def refresh_projects(refresh_git: bool = False):
        from services.project_service import ProjectService

        if refresh_git:
            set_projects(await ProjectService.refresh_all_git_status())
        else:
            set_projects(ProjectService.get_all())

    def bootstrap():
        page.run_task(refresh_projects, True)

    ft.use_effect(bootstrap, [])

    destinations = [
        ft.NavigationRailDestination(
            icon=ft.Icons.FOLDER_OUTLINED,
            selected_icon=ft.Icons.FOLDER,
            label="项目",
        ),
        ft.NavigationRailDestination(
            icon=ft.Icons.COMMIT_OUTLINED,
            selected_icon=ft.Icons.COMMIT,
            label="提交",
        ),
        ft.NavigationRailDestination(
            icon=ft.Icons.ANALYTICS_OUTLINED,
            selected_icon=ft.Icons.ANALYTICS,
            label="统计",
        ),
    ]

    content = [
        ProjectsView(on_projects_changed=refresh_projects),
        CommitView(projects=projects, on_projects_changed=refresh_projects),
        ReportsView(projects=projects),
    ][tab_index]

    return ft.Row(
        expand=True,
        controls=[
            ft.Container(
                bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
                content=ft.Column(
                    expand=True,
                    controls=[
                        ft.Container(
                            padding=ft.Padding.only(top=20, bottom=8),
                            content=ft.Column(
                                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                spacing=4,
                                controls=[
                                    ft.Container(
                                        width=44,
                                        height=44,
                                        border_radius=12,
                                        bgcolor=ft.Colors.PRIMARY,
                                        alignment=ft.Alignment.CENTER,
                                        content=ft.Icon(
                                            ft.Icons.CODE,
                                            color=ft.Colors.ON_PRIMARY,
                                            size=24,
                                        ),
                                    ),
                                    ft.Text(
                                        "CS PM",
                                        size=11,
                                        weight=ft.FontWeight.W_600,
                                        color=ft.Colors.ON_SURFACE_VARIANT,
                                    ),
                                ],
                            ),
                        ),
                        ft.NavigationRail(
                            expand=True,
                            selected_index=tab_index,
                            label_type=ft.NavigationRailLabelType.ALL,
                            min_width=88,
                            min_extended_width=160,
                            use_indicator=True,
                            destinations=destinations,
                            on_change=lambda e: set_tab_index(e.control.selected_index),
                            bgcolor=ft.Colors.TRANSPARENT,
                        ),
                    ],
                ),
            ),
            ft.VerticalDivider(width=1, color=ft.Colors.OUTLINE_VARIANT),
            ft.Container(expand=True, content=content),
        ],
    )


@ft.component
def App():
    return ft.SafeArea(
        expand=True,
        content=AppShell(),
    )
