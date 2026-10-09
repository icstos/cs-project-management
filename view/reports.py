"""统计页：趋势图、可排序明细表与 CSV 导出。

图表刻度与轴标签宽度的取值理由见 :func:`_bar_chart` 的注释 —— 那些是踩过坑的教训，
改动前请先确认在深色/浅色主题下都仍然可读。
"""

from __future__ import annotations

import math

import flet as ft
import flet_charts as fc

from models.dtos import CommitRow, TrendPoint
from models.enums import Tone
from view import design as T
from view import widgets
from view.guard import guarded
from view.view_platform import FletPlatform, use_notices, use_platform_requests
from viewmodel.formatting import format_count, format_datetime, format_day
from viewmodel.reports_vm import COLUMNS, RANGES, ReportsState, ReportsViewModel

#: 左侧读数区宽度，需容得下 "-10,000"
_Y_LABEL_SIZE = 52


@guarded
def ReportsView(*, vm: ReportsViewModel, platform: FletPlatform) -> ft.Control:
    page = ft.context.page
    state = vm.state
    use_notices(page, vm)
    use_platform_requests(platform, vm)

    # 项目 / 时间范围一变就重新聚合
    ft.use_effect(lambda: page.run_task(vm.load), [state.project_id, state.days])

    return widgets.page_shell(
        header=widgets.page_header(
            "提交统计",
            "汇总各项目的提交量、代码行变化与每日趋势",
            actions=[
                widgets.outlined(
                    "导出 CSV",
                    icon=ft.Icons.FILE_DOWNLOAD_OUTLINED,
                    disabled=not state.can_export,
                    on_click=lambda _: vm.request_export(),
                ),
                widgets.filled(
                    "同步中…" if state.syncing else "同步历史",
                    icon=ft.Icons.CLOUD_SYNC,
                    disabled=state.syncing or not state.projects,
                    tooltip="从各仓库读取 git log 并写入本地统计库",
                    on_click=lambda _: page.run_task(vm.sync_history),
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
                _toolbar(state, vm),
                _metrics(state),
                _trend_card(state.trend),
                _table_card(state, vm),
            ],
        ),
    )


# --------------------------------------------------------------------------- 构件
def _toolbar(state: ReportsState, vm: ReportsViewModel) -> ft.Control:
    # Row(wrap=True) 的子项不能带 expand：这里把需要撑开的元素放在第一行
    def pick_project(event) -> None:
        value = widgets.event_value(event)
        vm.set_project(None if value in (None, "all") else int(value))

    report = state.report
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
                            value=str(state.project_id) if state.project_id is not None else "all",
                            options=[
                                ft.dropdown.Option("all", "全部项目"),
                                *[ft.dropdown.Option(str(p.id), p.name) for p in state.projects],
                            ],
                            on_select=pick_project,
                        ),
                    ),
                    ft.Container(expand=True),
                    *(
                        [
                            widgets.muted(
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
                        selected=state.days == value,
                        show_checkmark=False,
                        on_select=lambda _, target=value: vm.set_days(target),
                    )
                    for label, value in RANGES
                ],
            ),
        ],
    )


def _metrics(state: ReportsState) -> ft.Control:
    totals = state.totals
    cells = (
        ("提交数", format_count(totals.commits), Tone.PRIMARY, ft.Icons.COMMIT),
        ("新增行", f"+{format_count(totals.insertions)}", Tone.SUCCESS, ft.Icons.ADD),
        ("删除行", f"-{format_count(totals.deletions)}", Tone.DANGER, ft.Icons.REMOVE),
        ("净增行", f"{totals.net:+,}", Tone.INFO, ft.Icons.STACKED_LINE_CHART),
        (
            "变更文件",
            format_count(totals.files_changed),
            Tone.WARNING,
            ft.Icons.FILE_PRESENT_OUTLINED,
        ),
        ("活跃项目", format_count(totals.active_projects), Tone.NEUTRAL, ft.Icons.FOLDER_OUTLINED),
    )
    return ft.ResponsiveRow(
        spacing=T.SPACE_MD,
        run_spacing=T.SPACE_MD,
        controls=[
            widgets.metric(
                label, value, tone=tone, icon=icon, col={"xs": 6, "sm": 4, "md": 4, "lg": 2}
            )
            for label, value, tone, icon in cells
        ],
    )


def _trend_card(trend: tuple[TrendPoint, ...]) -> ft.Control:
    has_data = any(point.insertions or point.deletions for point in trend)

    return widgets.surface(
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
                                widgets.pill(f"最近 {len(trend)} 天", dense=True),
                            ],
                        ),
                        ft.Row(
                            spacing=T.SPACE_LG,
                            tight=True,
                            controls=[
                                _legend_item(T.ADDITION_COLOR, "新增行"),
                                _legend_item(T.DELETION_COLOR, "删除行"),
                            ],
                        ),
                    ],
                ),
                _bar_chart(trend)
                if has_data
                else ft.Container(
                    height=T.CHART_HEIGHT,
                    alignment=ft.Alignment.CENTER,
                    content=widgets.muted("所选时间范围内没有提交记录", size=12),
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
            widgets.muted(label, size=11),
        ],
    )


def _bar_chart(trend: tuple[TrendPoint, ...]) -> ft.Control:
    peak = max((max(point.insertions, point.deletions) for point in trend), default=0)
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
                fc.ChartAxisLabel(value=index, label=widgets.chart_label(format_day(point.day)))
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
                fc.ChartAxisLabel(value=value, label=widgets.chart_label(format_count(value)))
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


def _table_card(state: ReportsState, vm: ReportsViewModel) -> ft.Control:
    rows = state.rows
    if state.loading and not rows:
        return widgets.surface(
            height=T.CHART_HEIGHT, content=widgets.busy_block("正在汇总提交记录…")
        )
    if not rows:
        return widgets.surface(
            height=T.CHART_HEIGHT,
            content=widgets.empty_state(
                ft.Icons.QUERY_STATS,
                "暂无统计数据",
                "先添加项目，再点击右上角「同步历史」采集 git 提交记录",
            ),
        )

    return widgets.surface(
        padding=T.SPACE_SM,
        content=ft.DataTable(
            columns=[
                ft.DataColumn(
                    ft.Text(column.label),
                    numeric=column.numeric,
                    on_sort=lambda event: vm.sort_by(event.column_index, event.ascending),
                )
                for column in COLUMNS
            ],
            rows=[_table_row(row) for row in rows],
            sort_column_index=state.sort_index,
            sort_ascending=state.sort_ascending,
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
            ft.DataCell(widgets.muted(commit.author or "—", size=12)),
            ft.DataCell(
                ft.Text(
                    format_datetime(commit.committed_at),
                    size=12,
                    tooltip=f"提交 {commit.short_hash}",
                )
            ),
            ft.DataCell(
                ft.Text(
                    f"+{format_count(commit.insertions)}",
                    size=12,
                    color=T.ADDITION_COLOR,
                    weight=ft.FontWeight.W_600,
                )
            ),
            ft.DataCell(
                ft.Text(
                    f"-{format_count(commit.deletions)}",
                    size=12,
                    color=T.DELETION_COLOR,
                    weight=ft.FontWeight.W_600,
                )
            ),
            ft.DataCell(ft.Text(format_count(commit.files_changed), size=12)),
        ]
    )


# --------------------------------------------------------------------------- 纯函数
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
