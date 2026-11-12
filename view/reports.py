"""统计页：趋势图、可排序明细表与 CSV 导出。

版式按"概览 → 趋势 → 明细"三层递进：先给六个指标卡，再给趋势图，最后给可排序
的明细表，信息密度从低到高，符合"先扫一眼结论、再逐行核对"的阅读顺序。

图表用 cs-ui 的 :class:`ui.BarChart`（继承自 flet-charts，配色与网格由框架按
语义色派生），因此换主色 / 切明暗时曲线与网格会一起变，不需要在这里写色值。
"""

from __future__ import annotations

import ui
from ui import (
    SPACE,
    Alignment,
    BarChart,
    Column,
    Container,
    CrossAxisAlignment,
    DataCell,
    DataColumn,
    DataRow,
    DataTable,
    FontWeight,
    Icon,
    Icons,
    MainAxisAlignment,
    ResponsiveRow,
    Row,
    ScrollMode,
    SelectBox,
    Table,
    Text,
    TextOverflow,
)

from models.dtos import CommitRow, TrendPoint
from models.enums import Tone
from view import design as T
from view import widgets
from view.guard import guarded
from view.view_platform import FletPlatform, use_notices, use_platform_requests
from viewmodel.formatting import format_count, format_datetime, format_day
from viewmodel.reports_vm import COLUMNS, RANGES, ReportsState, ReportsViewModel


@guarded
def ReportsView(*, vm: ReportsViewModel, platform: FletPlatform) -> ui.Control:
    page = ui.context.page
    state = vm.state
    use_notices(page, vm)
    use_platform_requests(platform, vm)

    # 项目 / 时间范围一变就重新聚合
    ui.use_effect(lambda: page.run_task(vm.load), [state.project_id, state.days])

    return widgets.page_shell(
        header=widgets.page_header(
            "提交统计",
            "汇总各项目的提交量、代码行变化与每日趋势",
            actions=[
                widgets.outlined(
                    "导出 CSV",
                    icon=Icons.FILE_DOWNLOAD_OUTLINED,
                    disabled=not state.can_export,
                    on_click=lambda _: vm.request_export(),
                ),
                widgets.filled(
                    "同步中…" if state.syncing else "同步历史",
                    icon=Icons.CLOUD_SYNC,
                    disabled=state.syncing or not state.projects,
                    tooltip="从各仓库读取 git log 并写入本地统计库",
                    on_click=lambda _: page.run_task(vm.sync_history),
                ),
            ],
        ),
        # 整页滚动：固定高度的图表 + 全量展开的明细表。
        # 若把明细表设成 expand 并让它内部滚动，小窗口下表格只剩一两行，
        # 反而是"能不能读完"的问题。
        body=Column(
            key="reports-body",
            expand=True,
            scroll=ScrollMode.AUTO,
            spacing=T.SECTION_GAP,
            controls=[
                _toolbar(state, vm),
                _metrics(state),
                *_report_body(state, vm),
            ],
        ),
    )


def _report_body(state: ReportsState, vm: ReportsViewModel) -> list[ui.Control]:
    """图表 + 明细；**一条记录都没有**时合成一块空态。

    两块都空着会出现上下两张大白板、各写一句"没有数据"，用户还得自己判断
    哪一块才是"下一步"。空态只留一份，并给出具体的下一步动作。
    """
    if state.rows or state.loading:
        return [_trend_card(state.trend), _table_card(state, vm)]
    return [
        widgets.surface(
            height=260,
            content=widgets.empty_state(
                Icons.QUERY_STATS,
                "暂无统计数据",
                "先添加项目，再点右上角「同步历史」采集各仓库的 git 提交记录",
            ),
        )
    ]


# --------------------------------------------------------------------------- 构件
def _toolbar(state: ReportsState, vm: ReportsViewModel) -> ui.Control:
    # Row(wrap=True) 的子项不能带 expand：这里把需要撑开的元素放在第一行
    def pick_project(event) -> None:
        value = widgets.event_value(event)
        vm.set_project(None if value in (None, "all") else int(value))

    report = state.report
    return Column(
        spacing=T.FIELD_GAP,
        tight=True,
        controls=[
            Row(
                spacing=SPACE["2"],
                vertical_alignment=CrossAxisAlignment.CENTER,
                controls=[
                    Container(
                        width=240,
                        content=SelectBox(
                            value=str(state.project_id) if state.project_id is not None else "all",
                            options=[
                                ui.SelectOption(key="all", text="全部项目"),
                                *[
                                    ui.SelectOption(key=str(p.id), text=p.name)
                                    for p in state.projects
                                ],
                            ],
                            editable=False,
                            width=240,
                            on_change=pick_project,
                        ).ui(),
                    ),
                    Container(expand=True),
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
            Row(
                spacing=SPACE["2"],
                run_spacing=SPACE["2"],
                wrap=True,
                controls=[
                    widgets.choice_chip(
                        label,
                        selected=state.days == value,
                        on_click=lambda _, target=value: vm.set_days(target),
                    )
                    for label, value in RANGES
                ],
            ),
        ],
    )


def _signed(value: int, sign: str) -> str:
    """带方向的正负数。零不戴符号 —— "+0" / "-0" 读起来像一个 bug。"""
    return f"{sign}{format_count(abs(value))}" if value else "0"


def _metrics(state: ReportsState) -> ui.Control:
    totals = state.totals
    cells = (
        ("提交数", format_count(totals.commits), Tone.PRIMARY, Icons.COMMIT),
        ("新增行", _signed(totals.insertions, "+"), Tone.SUCCESS, Icons.ADD),
        ("删除行", _signed(-totals.deletions, "-"), Tone.DANGER, Icons.REMOVE),
        (
            "净增行",
            _signed(totals.net, "+" if totals.net >= 0 else "-"),
            Tone.INFO,
            Icons.STACKED_LINE_CHART,
        ),
        (
            "变更文件",
            format_count(totals.files_changed),
            Tone.WARNING,
            Icons.FILE_PRESENT_OUTLINED,
        ),
        ("活跃项目", format_count(totals.active_projects), Tone.NEUTRAL, Icons.FOLDER_OUTLINED),
    )
    return ResponsiveRow(
        spacing=T.GRID_GUTTER,
        run_spacing=T.GRID_GUTTER,
        controls=[
            widgets.metric(
                label, value, tone=tone, icon=icon, col={"xs": 6, "sm": 4, "md": 4, "lg": 2}
            )
            for label, value, tone, icon in cells
        ],
    )


def _trend_card(trend: tuple[TrendPoint, ...]) -> ui.Control:
    has_data = any(point.insertions or point.deletions for point in trend)

    return widgets.surface(
        content=Column(
            spacing=T.GRID_GUTTER,
            tight=True,
            controls=[
                Row(
                    alignment=MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=CrossAxisAlignment.CENTER,
                    wrap=True,
                    run_spacing=SPACE["2"],
                    controls=[
                        Row(
                            spacing=SPACE["2"],
                            tight=True,
                            vertical_alignment=CrossAxisAlignment.CENTER,
                            controls=[
                                T.text(
                                    "每日代码增减",
                                    level=T.TextLevel.TITLE,
                                    weight=FontWeight.W_600,
                                ),
                                widgets.pill(f"最近 {len(trend)} 天", dense=True),
                            ],
                        ),
                        Row(
                            spacing=SPACE["4"],
                            tight=True,
                            controls=[
                                _legend_item(T.addition_color(), "新增行"),
                                _legend_item(T.deletion_color(), "删除行"),
                            ],
                        ),
                    ],
                ),
                _bar_chart(trend)
                if has_data
                # 空图表不留 260px 的空白：一行图标 + 说明就够，
                # 否则整页看起来像"加载失败"，还白白挤走了下面的表格。
                else Container(
                    height=120,
                    alignment=Alignment.CENTER,
                    content=Row(
                        spacing=SPACE["2"],
                        tight=True,
                        vertical_alignment=CrossAxisAlignment.CENTER,
                        controls=[
                            Icon(Icons.INSIGHTS, size=T.ICON_MD, color=T.MUTED_TEXT),
                            widgets.muted("所选时间范围内没有提交记录", size=12),
                        ],
                    ),
                ),
            ],
        )
    )


def _legend_item(color, label: str) -> Row:
    return Row(
        spacing=SPACE["1"],
        tight=True,
        vertical_alignment=CrossAxisAlignment.CENTER,
        controls=[
            Container(width=8, height=8, border_radius=T.RADIUS_XS, bgcolor=color),
            widgets.muted(label, size=11),
        ],
    )


def _bar_chart(trend: tuple[TrendPoint, ...]) -> ui.Control:
    """每日新增向上、删除向下：一条 0 基线把两种方向分成两半。

    ``min_y`` / ``max_y`` 按峰值对称留 15% 余量 —— 让正负两侧的视觉长度可比，
    否则"删除比新增多"要靠读数字才能看出来。``stacked=True`` 让两根柱子共用
    同一个 x 位置（正值向上、负值向下），不会左右错开各占一格。
    """
    peak = max((max(point.insertions, point.deletions) for point in trend), default=0)
    bound = peak * 1.15 or 1

    return BarChart(
        data={
            "日期": [format_day(point.day) for point in trend],
            "新增": [point.insertions for point in trend],
            "删除": [-point.deletions for point in trend],
        },
        x="日期",
        y=["新增", "删除"],
        color=[T.addition_color(), T.deletion_color()],
        height=T.CHART_HEIGHT,
        stacked=True,
        group_spacing=6,
        rod_width=7,
        border_radius=3,
        tooltip=True,
        min_y=-bound,
        max_y=bound,
        baseline_y=0,
    )


def _table_card(state: ReportsState, vm: ReportsViewModel) -> ui.Control:
    rows = state.rows
    if state.loading and not rows:
        return widgets.skeleton_block(rows=5, text="正在汇总提交记录…")
    if not rows:
        return widgets.surface(
            height=T.CHART_HEIGHT,
            content=widgets.empty_state(
                Icons.QUERY_STATS,
                "暂无统计数据",
                "先添加项目，再点击右上角「同步历史」采集 git 提交记录",
            ),
        )

    return widgets.surface(
        content=Column(
            spacing=SPACE["2"],
            tight=True,
            controls=[
                Row(
                    spacing=SPACE["2"],
                    vertical_alignment=CrossAxisAlignment.CENTER,
                    controls=[
                        T.text(
                            "提交明细",
                            level=T.TextLevel.TITLE,
                            weight=FontWeight.W_600,
                        ),
                        widgets.pill(f"{len(rows)} 条", dense=True),
                        Container(expand=True),
                        widgets.muted("点击表头可排序", size=11),
                    ],
                ),
                Table(
                    data_table=DataTable(
                        columns=[
                            DataColumn(
                                Text(column.label, size=12, weight=FontWeight.W_600),
                                numeric=column.numeric,
                                on_sort=lambda event: vm.sort_by(
                                    event.column_index, event.ascending
                                ),
                            )
                            for column in COLUMNS
                        ],
                        rows=[_table_row(row) for row in rows],
                        sort_column_index=state.sort_index,
                        sort_ascending=state.sort_ascending,
                        column_spacing=20,
                        heading_row_height=40,
                        data_row_max_height=44,
                    ),
                    with_number=False,
                    with_paged=False,
                    zebra=True,
                    expand=False,
                ),
            ],
        )
    )


def _table_row(row: CommitRow) -> DataRow:
    commit = row.commit
    return DataRow(
        cells=[
            DataCell(
                Text(
                    row.project_name,
                    size=12,
                    weight=FontWeight.W_500,
                    max_lines=1,
                    overflow=TextOverflow.ELLIPSIS,
                )
            ),
            DataCell(
                Container(
                    width=340,
                    content=Text(
                        commit.message,
                        size=12,
                        max_lines=1,
                        overflow=TextOverflow.ELLIPSIS,
                        tooltip=commit.message,
                    ),
                )
            ),
            DataCell(widgets.muted(commit.author or "—", size=12)),
            DataCell(
                Text(
                    format_datetime(commit.committed_at),
                    size=12,
                    tooltip=f"提交 {commit.short_hash}",
                )
            ),
            DataCell(
                T.text(
                    f"+{format_count(commit.insertions)}",
                    level=T.TextLevel.LABEL,
                    color=T.addition_color(),
                    weight=FontWeight.W_600,
                )
            ),
            DataCell(
                T.text(
                    f"-{format_count(commit.deletions)}",
                    level=T.TextLevel.LABEL,
                    color=T.deletion_color(),
                    weight=FontWeight.W_600,
                )
            ),
            DataCell(Text(format_count(commit.files_changed), size=12)),
        ]
    )
