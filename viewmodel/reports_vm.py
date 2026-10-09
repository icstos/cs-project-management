"""统计视图模型：趋势、可排序明细与 CSV 导出。

数据由 ``ReportService.report`` 一次聚合完成（分组下推到 SQL），
这里只做排序、导出与状态流转。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from models.dtos import CommitRow, Project, Report, Totals, TrendPoint
from models.enums import Tone
from models.settings import REPORT_ROW_LIMIT
from service.report_service import ReportService
from viewmodel.base import PlatformAction, ViewModel
from viewmodel.formatting import format_datetime

logger = logging.getLogger(__name__)

__all__ = ["COLUMNS", "RANGES", "ReportColumn", "ReportsState", "ReportsViewModel"]


@dataclass(frozen=True, slots=True)
class ReportColumn:
    """明细表的一列：标题、排序键、是否右对齐（数值列）。

    排序键与列标题放在一起，视图按同一份定义同时生成表头与排序逻辑，
    不存在"加了列却忘了改排序"的错位。
    """

    label: str
    key: Callable[[CommitRow], object]
    numeric: bool = False


COLUMNS: tuple[ReportColumn, ...] = (
    ReportColumn("项目", lambda row: row.project_name.casefold()),
    ReportColumn("提交说明", lambda row: row.commit.message.casefold()),
    ReportColumn("作者", lambda row: (row.commit.author or "").casefold()),
    ReportColumn("提交时间", lambda row: row.commit.committed_at),
    ReportColumn("新增", lambda row: row.commit.insertions, numeric=True),
    ReportColumn("删除", lambda row: row.commit.deletions, numeric=True),
    ReportColumn("文件数", lambda row: row.commit.files_changed, numeric=True),
)

#: 时间范围选项：``(标题, 天数)``，``None`` 表示不限
RANGES: tuple[tuple[str, int | None], ...] = (
    ("7 天", 7),
    ("30 天", 30),
    ("90 天", 90),
    ("全部", None),
)

#: 默认按「提交时间」倒序，与直觉一致
_DEFAULT_SORT = next(index for index, column in enumerate(COLUMNS) if column.label == "提交时间")


@dataclass(frozen=True, slots=True)
class ReportsState:
    """统计页的全部状态。"""

    projects: tuple[Project, ...] = ()
    project_id: int | None = None
    days: int | None = 30
    report: Report | None = None
    loading: bool = True
    syncing: bool = False
    sort_index: int = _DEFAULT_SORT
    sort_ascending: bool = False

    # ------------------------------------------------------------------ 派生
    @property
    def totals(self) -> Totals:
        return self.report.totals if self.report else Totals()

    @property
    def trend(self) -> tuple[TrendPoint, ...]:
        return self.report.trend if self.report else ()

    @property
    def rows(self) -> tuple[CommitRow, ...]:
        """按当前排序列排序后的明细行。"""
        source = self.report.rows if self.report else ()
        if not 0 <= self.sort_index < len(COLUMNS):
            return source
        return tuple(
            sorted(
                source,
                key=COLUMNS[self.sort_index].key,
                reverse=not self.sort_ascending,
            )
        )

    @property
    def can_export(self) -> bool:
        return bool(self.rows)

    @property
    def active_range(self) -> str:
        return next((label for label, value in RANGES if value == self.days), "全部")


class ReportsViewModel(ViewModel[ReportsState]):
    """统计页的状态与命令。"""

    def __init__(self, service: ReportService) -> None:
        super().__init__(ReportsState())
        self._service = service
        #: 上一次导出请求涉及多少行，仅用于写日志
        self._pending_rows = 0

    # ------------------------------------------------------------------ 同步
    def sync(self, *, projects: tuple[Project, ...]) -> None:
        if self.state.projects != projects:
            self.update(projects=projects)

    # ------------------------------------------------------------------ 筛选
    def set_project(self, project_id: int | None) -> None:
        self.update(project_id=project_id)

    def set_days(self, days: int | None) -> None:
        self.update(days=days)

    def sort_by(self, index: int, ascending: bool) -> None:
        self.update(sort_index=index, sort_ascending=ascending)

    # ------------------------------------------------------------------ 数据
    async def load(self) -> None:
        self.update(loading=True)
        try:
            report = await self._service.report(
                project_id=self.state.project_id,
                days=self.state.days,
                row_limit=REPORT_ROW_LIMIT,
            )
        except Exception as exc:  # 统计读库失败不该让页面白屏
            logger.exception(
                "读取统计失败（project_id=%s，days=%s）", self.state.project_id, self.state.days
            )
            self.update(loading=False)
            self.notify(f"读取统计失败：{exc}", Tone.DANGER)
            return
        self.update(loading=False, report=report)

    async def sync_history(self) -> None:
        self.update(syncing=True)
        try:
            outcome = await self._service.sync_history(self.state.project_id)
        except Exception as exc:
            logger.exception("同步历史失败（project_id=%s）", self.state.project_id)
            self.update(syncing=False)
            self.notify(f"同步失败：{exc}", Tone.DANGER)
            return
        self.update(syncing=False)
        self.notify(
            outcome.headline,
            Tone.WARNING if outcome.failures else Tone.SUCCESS,
        )
        await self.load()

    # ------------------------------------------------------------------ 导出
    def request_export(self) -> None:
        """把当前明细交给视图去选保存位置。"""
        rows = self.state.rows
        if not rows:
            self.notify("当前筛选没有任何提交记录", Tone.WARNING)
            return
        file_name = f"commit-report-{date.today().isoformat()}.csv"
        self._pending_rows = len(rows)
        self.ask_platform(
            PlatformAction.SAVE_FILE,
            text=file_name,
            data=_to_csv(rows),
        )

    def export_finished(self, saved_path: str | None, error: str | None = None) -> None:
        if error:
            logger.error("导出 CSV 失败（%d 行）：%s", self._pending_rows, error)
            self.notify(f"导出失败：{error}", Tone.DANGER)
            return
        if not saved_path:
            return
        logger.info("导出提交明细：%d 行 → %s", self._pending_rows, saved_path)
        self.notify(f"已导出到 {saved_path}", Tone.INFO)


# --------------------------------------------------------------------------- 纯函数
def _to_csv(rows: tuple[CommitRow, ...]) -> bytes:
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
                    format_datetime(commit.committed_at),
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
