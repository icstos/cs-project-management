"""提交历史的采集与统计聚合。

* :meth:`ReportService.sync_history` 从各仓库读取 git log 写入统计库，单个项目
  失败不影响其余项目；
* :meth:`ReportService.report` 一次聚合出统计页所需的全部数据（总量、每日趋势、
  按项目分组、明细行），全部下推到 SQL，不在界面线程里做循环汇总。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import date, timedelta

from infra.concurrency import offload
from infra.git_cli import GitError
from infra.ports import CommitRepository, GitPort, ProjectRepository
from models.dtos import (
    CommitRow,
    ProjectTotals,
    Report,
    SyncOutcome,
    Totals,
    TrendPoint,
)
from models.settings import TREND_DAYS_DEFAULT, TREND_DAYS_MAX

logger = logging.getLogger(__name__)

#: ``on_progress(已完成, 总数)``
Progress = Callable[[int, int], None]

_UNKNOWN_PROJECT = "已删除项目"

__all__ = ["Progress", "ReportService"]


class ReportService:
    """历史采集与统计报表。"""

    def __init__(
        self,
        *,
        projects: ProjectRepository,
        commits: CommitRepository,
        git: GitPort,
        history_limit: int,
    ) -> None:
        self._projects = projects
        self._commits = commits
        self._git = git
        self._history_limit = history_limit

    # ------------------------------------------------------------------ 采集
    async def sync_history(
        self,
        project_id: int | None = None,
        *,
        on_progress: Progress | None = None,
    ) -> SyncOutcome:
        targets = (
            [await self._require(project_id)]
            if project_id is not None
            else await offload(self._projects.list_all)
        )
        if not targets:
            return SyncOutcome()

        logger.info("同步历史：开始采集 %d 个仓库", len(targets))
        created = updated = 0
        failures: list[str] = []
        for index, project in enumerate(targets, start=1):
            try:
                commits = await self._git.history(project.local_path, limit=self._history_limit)
                new_count, changed_count = await offload(self._commits.upsert, project.id, commits)
                created += new_count
                updated += changed_count
                logger.debug(
                    "同步历史：项目「%s」新增 %d 条、更新 %d 条",
                    project.name,
                    new_count,
                    changed_count,
                )
            except GitError as exc:
                logger.warning("同步历史：项目「%s」失败：%s", project.name, exc)
                failures.append(f"{project.name}：{exc}")
            finally:
                _notify(on_progress, index, len(targets))

        logger.info(
            "同步历史：完成 %d 个仓库，新增 %d 条、更新 %d 条，失败 %d 个",
            len(targets),
            created,
            updated,
            len(failures),
        )
        return SyncOutcome(
            projects=len(targets),
            created=created,
            updated=updated,
            failures=tuple(failures),
        )

    # ------------------------------------------------------------------ 报表
    async def report(
        self,
        *,
        project_id: int | None = None,
        days: int | None = None,
        row_limit: int,
    ) -> Report:
        return await offload(self._build_report, project_id, days, row_limit)

    def _build_report(
        self,
        project_id: int | None,
        days: int | None,
        row_limit: int,
    ) -> Report:
        since = None if days is None else date.today() - timedelta(days=days - 1)
        names = {project.id: project.name for project in self._projects.list_all()}
        commits_count, insertions, deletions, files_changed, active = self._commits.totals(
            project_id=project_id, since=since
        )
        daily = self._commits.daily_totals(project_id=project_id, since=since)
        grouped = self._commits.project_totals(project_id=project_id, since=since)
        total_rows = self._commits.count(project_id=project_id, since=since)
        commits = self._commits.list_commits(project_id=project_id, since=since, limit=row_limit)

        return Report(
            totals=Totals(
                commits=commits_count,
                insertions=insertions,
                deletions=deletions,
                files_changed=files_changed,
                active_projects=active,
            ),
            trend=_fill_trend(daily, days),
            rows=tuple(
                CommitRow(
                    commit=commit, project_name=names.get(commit.project_id, _UNKNOWN_PROJECT)
                )
                for commit in commits
            ),
            per_project=tuple(
                ProjectTotals(
                    project_id=row[0],
                    project_name=names.get(row[0], _UNKNOWN_PROJECT),
                    commits=row[1],
                    insertions=row[2],
                    deletions=row[3],
                )
                for row in grouped
            ),
            row_count=total_rows,
            truncated=total_rows > len(commits),
        )

    # ------------------------------------------------------------------ 内部
    async def _require(self, project_id: int):
        project = await offload(self._projects.get, project_id)
        if project is None:
            raise ValueError("项目不存在或已被删除")
        return project


def _fill_trend(
    daily: Sequence[tuple[str, int, int, int]],
    days: int | None,
) -> tuple[TrendPoint, ...]:
    """把稀疏的按天聚合补齐成连续序列，缺失的日期补 0，图表才不会跳。"""
    window = min(days or TREND_DAYS_DEFAULT, TREND_DAYS_MAX)
    buckets = {
        row[0]: TrendPoint(
            day=date.fromisoformat(row[0]),
            commits=row[1],
            insertions=row[2],
            deletions=row[3],
        )
        for row in daily
    }
    today = date.today()
    return tuple(
        buckets.get(
            (day := today - timedelta(days=offset)).isoformat(),
            TrendPoint(day=day),
        )
        for offset in range(window - 1, -1, -1)
    )


def _notify(callback: Progress | None, done: int, total: int) -> None:
    if callback is not None:
        callback(done, total)
