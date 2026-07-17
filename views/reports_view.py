import flet as ft

from models.database import Project
from services.project_service import ProjectService
from views.ui_helpers import (
    empty_state,
    format_datetime,
    page_container,
    primary_button,
    section_header,
    show_snack,
    stat_card,
    surface_card,
)


@ft.component
def ReportsView(projects: list[Project]):
    page = ft.context.page
    filter_id, set_filter_id = ft.use_state(None)
    records, set_records = ft.use_state([])
    loading, set_loading = ft.use_state(False)
    collecting, set_collecting = ft.use_state(False)

    async def load_records():
        set_loading(True)
        try:
            rows = ProjectService.get_commit_records_with_projects(filter_id)
            set_records(rows)
        except Exception as exc:
            show_snack(page, str(exc), error=True)
        finally:
            set_loading(False)

    ft.use_effect(lambda: page.run_task(load_records), [filter_id])

    async def collect_statistics():
        set_collecting(True)
        try:
            saved = await ProjectService.collect_statistics(filter_id)
            show_snack(page, f"统计完成，已保存 {saved} 条提交记录")
            await load_records()
        except Exception as exc:
            show_snack(page, str(exc), error=True)
        finally:
            set_collecting(False)

    total_insertions = sum(record.insertions for record, _ in records)
    total_deletions = sum(record.deletions for record, _ in records)
    total_files = sum(record.files_changed for record, _ in records)

    summary_cards = ft.ResponsiveRow(
        spacing=12,
        run_spacing=12,
        controls=[
            stat_card(
                "提交数",
                str(len(records)),
                icon=ft.Icons.COMMIT,
                bgcolor=ft.Colors.PRIMARY_CONTAINER,
                fgcolor=ft.Colors.ON_PRIMARY_CONTAINER,
            ),
            stat_card(
                "新增 / 删除行",
                f"+{total_insertions} / -{total_deletions}",
                icon=ft.Icons.CODE,
                bgcolor=ft.Colors.TERTIARY_CONTAINER,
                fgcolor=ft.Colors.ON_TERTIARY_CONTAINER,
            ),
            stat_card(
                "变更文件数",
                str(total_files),
                icon=ft.Icons.INSERT_DRIVE_FILE_OUTLINED,
                bgcolor=ft.Colors.SECONDARY_CONTAINER,
                fgcolor=ft.Colors.ON_SECONDARY_CONTAINER,
            ),
        ],
    )

    table = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("项目")),
            ft.DataColumn(ft.Text("提交说明")),
            ft.DataColumn(ft.Text("提交时间")),
            ft.DataColumn(ft.Text("新增"), numeric=True),
            ft.DataColumn(ft.Text("删除"), numeric=True),
            ft.DataColumn(ft.Text("文件数"), numeric=True),
        ],
        rows=[
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(project.name, weight=ft.FontWeight.W_500)),
                    ft.DataCell(
                        ft.Text(
                            record.message,
                            max_lines=2,
                            overflow=ft.TextOverflow.ELLIPSIS,
                            tooltip=record.message,
                        )
                    ),
                    ft.DataCell(ft.Text(format_datetime(record.committed_at))),
                    ft.DataCell(
                        ft.Text(
                            f"+{record.insertions}",
                            color=ft.Colors.GREEN_700,
                            weight=ft.FontWeight.W_500,
                        )
                    ),
                    ft.DataCell(
                        ft.Text(
                            f"-{record.deletions}",
                            color=ft.Colors.RED_700,
                            weight=ft.FontWeight.W_500,
                        )
                    ),
                    ft.DataCell(ft.Text(str(record.files_changed))),
                ]
            )
            for record, project in records
        ],
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=12,
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
                            "提交统计", "汇总各项目的提交内容与代码行数变化"
                        ),
                        primary_button(
                            "统计中..." if collecting else "统计",
                            icon=ft.Icons.ANALYTICS,
                            disabled=collecting or not projects,
                            on_click=lambda _: page.run_task(collect_statistics),
                        ),
                    ],
                ),
                ft.Dropdown(
                    label="筛选项目",
                    width=320,
                    border_radius=10,
                    value=str(filter_id) if filter_id else "all",
                    options=[
                        ft.dropdown.Option("all", "全部项目"),
                        *[
                            ft.dropdown.Option(str(item.id), item.name)
                            for item in projects
                        ],
                    ],
                    on_select=lambda e: set_filter_id(
                        None if e.control.value == "all" else int(e.control.value)
                    ),
                ),
                summary_cards,
                ft.ProgressRing(visible=loading)
                if loading
                else empty_state(
                    ft.Icons.QUERY_STATS,
                    "暂无统计数据",
                    "添加项目后点击「统计」采集 Git 提交记录",
                )
                if not records
                else surface_card(
                    ft.ListView(
                        expand=True,
                        controls=[table],
                    ),
                    padding=0,
                    expand=True,
                ),
            ],
        ),
    )
