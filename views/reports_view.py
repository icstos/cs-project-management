"""统计视图：趋势图、可排序明细表与 CSV 导出。

数据由 ``ProjectService.report`` 一次聚合完成（SQL 层面 group by），
本视图只做排序、渲染与导出。
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import date

import flet as ft
import flet_charts as fc

from core import theme as T
from models.dto import CommitRow, Project, Report, TrendPoint
from services.project_service import ProjectService
from views import ui
from views.guard import guarded

_RANGES: tuple[tuple[str, int | None], ...] = (
    ("7 天", 7),
    ("30 天", 30),
    ("90 天", 90),
    ("全部", None),
)
_COLUMNS = ("项目", "提交说明", "作者", "提交时间", "新增", "删除", "文件数")
_Y_LABEL_SIZE = 52  # 左侧读数区宽度，需容得下 "-10,000"


@guarded
def ReportsView(
    *,
    projects: list[Project],
    service: ProjectService,
    picker: ft.FilePicker,
    busy: bool,
):
    page = ft.context.page

    project_id, set_project_id = ft.use_state(None)
    days, set_days = ft.use_state(30)
    report, set_report = ft.use_state(None)
    loading, set_loading = ft.use_state(True)
    syncing, set_syncing = ft.use_state(False)
    sort_index, set_sort_index = ft.use_state(3)  # 默认按提交时间倒序
    sort_ascending, set_sort_ascending = ft.use_state(False)

    async def load() -> None:
        set_loading(True)
        try:
            set_report(await service.report(project_id=project_id, days=days))
        except Exception as exc:
            ui.toast(page, f"读取统计失败：{exc}", tone=T.Tone.DANGER)
        finally:
            set_loading(False)

    ft.use_effect(load, [project_id, days])

    async def sync_history(_) -> None:
        set_syncing(True)
        try:
            outcome = await service.sync_history(project_id)
            ui.toast(
                page,
                outcome.headline,
                tone=T.Tone.WARNING if outcome.failures else T.Tone.SUCCESS,
            )
            await load()
        except Exception as exc:
            ui.toast(page, f"同步失败：{exc}", tone=T.Tone.DANGER)
        finally:
            set_syncing(False)

    def on_sort(event: ft.DataColumnSortEvent) -> None:
        set_sort_index(event.column_index)
        set_sort_ascending(event.ascending)

    rows = ft.use_memo(
        lambda: _sort_rows(report.rows if report else (), sort_index, sort_ascending),
        [report, sort_index, sort_ascending],
    )

    async def export_csv(_) -> None:
        if not rows:
            ui.toast(page, "当前筛选没有任何提交记录", tone=T.Tone.WARNING)
            return
        try:
            saved = await picker.save_file(
                dialog_title="导出提交明细",
                file_name=f"commit-report-{date.today().isoformat()}.csv",
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["csv"],
                src_bytes=_to_csv(rows),
            )
        except Exception as exc:
            ui.toast(page, f"导出失败：{exc}", tone=T.Tone.DANGER)
            return
        if saved:
            ui.toast(page, f"已导出到 {saved}", tone=T.Tone.INFO)

    totals = report.totals if report else None

    return ui.page_shell(
        header=ui.page_header(
            "提交统计",
            "汇总各项目的提交量、代码行变化与每日趋势",
            actions=[
                ui.outlined(
                    "导出 CSV",
                    icon=ft.Icons.FILE_DOWNLOAD_OUTLINED,
                    disabled=not rows,
                    on_click=lambda _: page.run_task(export_csv),
                ),
                ui.filled(
                    "同步中…" if syncing else "同步历史",
                    icon=ft.Icons.CLOUD_SYNC,
                    disabled=syncing or not projects,
                    tooltip="从各仓库读取 git log 并写入本地统计库",
                    on_click=lambda _: page.run_task(sync_history, _),
                ),
            ],
        ),
        # 整页滚动：固定高度的图表 + 全量展开的明细表。
        # 若把明细表设成 expand 并让它内部滚动，小窗口下表格只剩一两行，
        # 反而是"能不能读完"的问题。
        body=ft.Column(
            key="reports-body",
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            spacing=T.SPACE_MD,
            controls=[
                _toolbar(
                    projects=projects,
                    project_id=project_id,
                    on_project=set_project_id,
                    days=days,
                    on_days=set_days,
                    report=report,
                ),
                ft.ResponsiveRow(
                    spacing=T.SPACE_MD,
                    run_spacing=T.SPACE_MD,
                    controls=[
                        ui.metric(
                            "提交数",
                            ui.format_count(totals.commits if totals else 0),
                            tone=T.Tone.PRIMARY,
                            icon=ft.Icons.COMMIT,
                            col={"xs": 6, "sm": 4, "md": 4, "lg": 2},
                        ),
                        ui.metric(
                            "新增行",
                            f"+{ui.format_count(totals.insertions if totals else 0)}",
                            tone=T.Tone.SUCCESS,
                            icon=ft.Icons.ADD,
                            col={"xs": 6, "sm": 4, "md": 4, "lg": 2},
                        ),
                        ui.metric(
                            "删除行",
                            f"-{ui.format_count(totals.deletions if totals else 0)}",
                            tone=T.Tone.DANGER,
                            icon=ft.Icons.REMOVE,
                            col={"xs": 6, "sm": 4, "md": 4, "lg": 2},
                        ),
                        ui.metric(
                            "净增行",
                            f"{(totals.net if totals else 0):+,}",
                            tone=T.Tone.INFO,
                            icon=ft.Icons.STACKED_LINE_CHART,
                            col={"xs": 6, "sm": 4, "md": 4, "lg": 2},
                        ),
                        ui.metric(
                            "变更文件",
                            ui.format_count(totals.files_changed if totals else 0),
                            tone=T.Tone.WARNING,
                            icon=ft.Icons.FILE_PRESENT_OUTLINED,
                            col={"xs": 6, "sm": 4, "md": 4, "lg": 2},
                        ),
                        ui.metric(
                            "活跃项目",
                            ui.format_count(totals.active_projects if totals else 0),
                            tone=T.Tone.NEUTRAL,
                            icon=ft.Icons.FOLDER_OUTLINED,
                            col={"xs": 6, "sm": 4, "md": 4, "lg": 2},
                        ),
                    ],
                ),
                _trend_card(report.trend if report else ()),
                _table_card(
                    rows=rows,
                    loading=loading,
                    sort_index=sort_index,
                    sort_ascending=sort_ascending,
                    on_sort=on_sort,
                ),
            ],
        ),
    )


# --------------------------------------------------------------------------- 构件
def _toolbar(
    *,
    projects: list[Project],
    project_id: int | None,
    on_project,
    days: int | None,
    on_days,
    report: Report | None,
) -> ft.Control:
    # Row(wrap=True) 的子项不能带 expand：这里把需要撑开的元素放在第一行
    def pick_project(event) -> None:
        value = ui.event_value(event)
        on_project(None if value in (None, "all") else int(value))

    return ft.Column(
        spacing=T.SPACE_SM,
        tight=True,
        controls=[
            ft.Row(
                spacing=T.SPACE_SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Container(
                        width=220,
                        content=ft.Dropdown(
                            dense=True,
                            border=T.field_border(),
                            value=str(project_id) if project_id is not None else "all",
                            options=[
                                ft.dropdown.Option("all", "全部项目"),
                                *[ft.dropdown.Option(str(p.id), p.name) for p in projects],
                            ],
                            on_select=pick_project,
                        ),
                    ),
                    ft.Container(expand=True),
                    *(
                        [
                            ui.muted(
                                f"共 {report.row_count} 条记录，展示最新 {len(report.rows)} 条",
                                size=11,
                            )
                        ]
                        if report and report.truncated
                        else []
                    ),
                ],
            ),
            ft.Row(
                spacing=T.SPACE_SM,
                run_spacing=T.SPACE_SM,
                wrap=True,
                controls=[
                    ft.Chip(
                        label=ft.Text(label),
                        selected=days == value,
                        show_checkmark=False,
                        on_select=lambda _, target=value: on_days(target),
                    )
                    for label, value in _RANGES
                ],
            ),
        ],
    )


def _trend_card(trend: tuple[TrendPoint, ...]) -> ft.Control:
    has_data = any(point.insertions or point.deletions for point in trend)

    legend = ft.Row(
        spacing=T.SPACE_LG,
        tight=True,
        controls=[
            _legend_item(T.ADDITION_COLOR, "新增行"),
            _legend_item(T.DELETION_COLOR, "删除行"),
        ],
    )

    return ui.surface(
        content=ft.Column(
            spacing=T.SPACE_SM,
            tight=True,
            controls=[
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Row(
                            spacing=T.SPACE_SM,
                            tight=True,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                ft.Text("每日代码增减", size=13, weight=ft.FontWeight.W_600),
                                ui.pill(f"最近 {len(trend)} 天", dense=True),
                            ],
                        ),
                        legend,
                    ],
                ),
                _bar_chart(trend)
                if has_data
                else ft.Container(
                    height=T.CHART_HEIGHT,
                    alignment=ft.Alignment.CENTER,
                    content=ui.muted("所选时间范围内没有提交记录", size=12),
                ),
            ],
        )
    )


def _legend_item(color: str, label: str) -> ft.Row:
    return ft.Row(
        spacing=T.SPACE_XS,
        tight=True,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.Container(width=10, height=10, border_radius=3, bgcolor=color),
            ui.muted(label, size=11),
        ],
    )


def _bar_chart(trend: tuple[TrendPoint, ...]) -> ft.Control:
    peak = max(
        (max(point.insertions, point.deletions) for point in trend),
        default=0,
    )
    low, high = (-peak * 1.2, peak * 1.15) if peak else (-1, 1)
    step = _nice_step(peak)
    label_step = max(1, len(trend) // 8)

    return fc.BarChart(
        height=T.CHART_HEIGHT,
        interactive=True,
        group_spacing=0.25,
        baseline_y=0,
        min_y=low,
        max_y=high,
        groups=[
            fc.BarChartGroup(
                x=index,
                group_vertically=True,
                rods=[
                    fc.BarChartRod(
                        from_y=0,
                        to_y=point.insertions,
                        width=7,
                        color=T.ADDITION_COLOR,
                        border_radius=2,
                        show_tooltip=True,
                        tooltip=(
                            f"{point.day.strftime('%m-%d')} 新增 {point.insertions} 行"
                            f" / {point.commits} 次提交"
                        ),
                    ),
                    fc.BarChartRod(
                        from_y=0,
                        to_y=-point.deletions,
                        width=7,
                        color=T.DELETION_COLOR,
                        border_radius=2,
                        show_tooltip=True,
                        tooltip=f"{point.day.strftime('%m-%d')} 删除 {point.deletions} 行",
                    ),
                ],
            )
            for index, point in enumerate(trend)
        ],
        bottom_axis=fc.ChartAxis(
            show_labels=True,
            label_size=18,
            labels=[
                fc.ChartAxisLabel(
                    value=index,
                    label=ui.chart_label(ui.format_day(point.day)),
                )
                for index, point in enumerate(trend)
                if index % label_step == 0 or index == len(trend) - 1
            ],
        ),
        # label_size 是"每个标签占用的空间"：左侧要放得下 "-10,000" 这样的读数，
        # 留 10px 会把标签压没，这里按最长读数的宽度预留。
        left_axis=fc.ChartAxis(
            show_labels=True,
            label_size=_Y_LABEL_SIZE,
            labels=[
                fc.ChartAxisLabel(
                    value=value,
                    label=ui.chart_label(ui.format_count(value)),
                )
                for value in _axis_values(low, high, step)
            ],
        ),
        horizontal_grid_lines=fc.ChartGridLines(
            interval=step,
            color=ft.Colors.with_opacity(0.5, T.BORDER_COLOR),
            width=1,
        ),
        border=ft.Border.all(0, ft.Colors.TRANSPARENT),
    )


def _nice_step(peak: int, *, divisions: int = 4) -> int:
    """刻度间隔取 1/2/5×10ⁿ，避免轴上出现 10,693 这类难以速读的读数。"""
    if peak <= 0:
        return 1
    rough = peak / divisions
    magnitude = 10 ** math.floor(math.log10(rough))
    for factor in (1, 2, 5):
        if factor * magnitude >= rough:
            return int(factor * magnitude)
    return int(10 * magnitude)


def _axis_values(low: float, high: float, step: int) -> list[int]:
    """落在可视范围内的刻度值（含 0 基线）。"""
    if step <= 0:
        return [0]
    value = math.ceil(low / step) * step
    ticks = []
    while value <= high:
        ticks.append(int(value))
        value += step
    return ticks


def _table_card(
    *,
    rows: list[CommitRow],
    loading: bool,
    sort_index: int,
    sort_ascending: bool,
    on_sort,
) -> ft.Control:
    if loading and not rows:
        return ui.surface(height=T.CHART_HEIGHT, content=ui.busy_block("正在汇总提交记录…"))
    if not rows:
        return ui.surface(
            height=T.CHART_HEIGHT,
            content=ui.empty_state(
                ft.Icons.QUERY_STATS,
                "暂无统计数据",
                "先添加项目，再点击右上角「同步历史」采集 git 提交记录",
            ),
        )

    return ui.surface(
        padding=T.SPACE_SM,
        content=ft.DataTable(
            columns=[
                ft.DataColumn(
                    ft.Text(label),
                    numeric=index >= 4,
                    on_sort=on_sort,
                )
                for index, label in enumerate(_COLUMNS)
            ],
            rows=[_table_row(row) for row in rows],
            sort_column_index=sort_index,
            sort_ascending=sort_ascending,
            border=ft.Border.all(0, ft.Colors.TRANSPARENT),
            border_radius=T.RADIUS_MD,
            column_spacing=20,
            data_row_max_height=44,
        ),
    )


def _table_row(row: CommitRow) -> ft.DataRow:
    commit = row.commit
    return ft.DataRow(
        cells=[
            ft.DataCell(
                ft.Text(row.project_name, size=12, weight=ft.FontWeight.W_500, max_lines=1)
            ),
            ft.DataCell(
                ft.Container(
                    width=340,
                    content=ft.Text(
                        commit.message,
                        size=12,
                        max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        tooltip=commit.message,
                    ),
                )
            ),
            ft.DataCell(ui.muted(commit.author or "—", size=12)),
            ft.DataCell(
                ft.Text(
                    ui.format_datetime(commit.committed_at),
                    size=12,
                    tooltip=f"提交 {commit.short_hash}",
                )
            ),
            ft.DataCell(
                ft.Text(
                    f"+{ui.format_count(commit.insertions)}",
                    size=12,
                    color=T.ADDITION_COLOR,
                    weight=ft.FontWeight.W_600,
                )
            ),
            ft.DataCell(
                ft.Text(
                    f"-{ui.format_count(commit.deletions)}",
                    size=12,
                    color=T.DELETION_COLOR,
                    weight=ft.FontWeight.W_600,
                )
            ),
            ft.DataCell(ft.Text(ui.format_count(commit.files_changed), size=12)),
        ]
    )


# --------------------------------------------------------------------------- 纯函数
_SORT_KEYS: tuple[Callable[[CommitRow], object], ...] = (
    lambda row: row.project_name.casefold(),
    lambda row: row.commit.message.casefold(),
    lambda row: (row.commit.author or "").casefold(),
    lambda row: row.commit.committed_at,
    lambda row: row.commit.insertions,
    lambda row: row.commit.deletions,
    lambda row: row.commit.files_changed,
)


def _sort_rows(rows: tuple[CommitRow, ...], index: int, ascending: bool) -> list[CommitRow]:
    if not 0 <= index < len(_SORT_KEYS):
        return list(rows)
    return sorted(rows, key=_SORT_KEYS[index], reverse=not ascending)


def _to_csv(rows: list[CommitRow]) -> bytes:
    """导出为带 BOM 的 UTF-8，Excel 打开不乱码。"""
    header = ["项目", "提交", "说明", "作者", "时间", "新增", "删除", "文件数"]
    lines = [",".join(header)]
    for row in rows:
        commit = row.commit
        lines.append(
            ",".join(
                _csv_cell(value)
                for value in (
                    row.project_name,
                    commit.short_hash,
                    commit.message,
                    commit.author,
                    ui.format_datetime(commit.committed_at),
                    commit.insertions,
                    commit.deletions,
                    commit.files_changed,
                )
            )
        )
    return ("\r\n".join(lines) + "\r\n").encode("utf-8-sig")


def _csv_cell(value: object) -> str:
    text = str(value)
    if any(char in text for char in ',"\n\r'):
        return '"' + text.replace('"', '""') + '"'
    return text
