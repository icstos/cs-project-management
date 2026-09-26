"""项目业务编排。

对外只暴露异步方法并返回 DTO，内部统一做三件事：

1. 校验用户输入（名称、路径、是否 Git 仓库、是否重复）；
2. 把阻塞的 SQLite 访问丢进线程池；
3. 把多次 git 探测按并发上限并行执行，最后一次性落库。

日志分工：外部命令的细节在 ``core.proc``，这里只记**操作流水**（谁对哪个项目做了什么、
结果如何），两者按时间线拼起来就能还原一次完整的用户操作。
"""

from __future__ import annotations

import itertools
import logging
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path

from core.config import (
    GIT_CONCURRENCY,
    GIT_HISTORY_LIMIT,
    REPORT_ROW_LIMIT,
    TREND_DAYS_DEFAULT,
    TREND_DAYS_MAX,
)
from core.paths import normalize, problem
from core.tasks import gather_limited, offload
from models.database import session_scope
from models.dto import (
    Commit,
    CommitOutcome,
    CommitRow,
    GitStatus,
    Permission,
    Project,
    ProjectTotals,
    Report,
    SyncOutcome,
    Totals,
    TrendPoint,
)
from repositories import commit_repo, project_repo
from services.git_service import GitError, GitService

logger = logging.getLogger(__name__)

Progress = Callable[[int, int], None]
_UNKNOWN_PROJECT = "已删除项目"


class ProjectService:
    def __init__(self, git: GitService | None = None) -> None:
        self._git = git or GitService()

    # ------------------------------------------------------------------ 只读
    async def list_projects(self) -> list[Project]:
        return await offload(self._load_projects)

    async def get(self, project_id: int) -> Project:
        project = await offload(self._load_project, project_id)
        if project is None:
            raise ValueError("项目不存在或已被删除")
        return project

    async def git_available(self) -> bool:
        return await self._git.is_available()

    # ------------------------------------------------------------------ 维护
    async def create(self, *, name: str, local_path: str, permission: Permission) -> Project:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("项目名称不能为空")
        resolved = self._resolve_repo(local_path)

        project = await offload(self._insert, clean_name, resolved, permission)
        logger.info("新增项目「%s」→ %s（%s）", clean_name, resolved, permission.value)
        return await self.refresh(project.id)

    async def update(
        self,
        project_id: int,
        *,
        name: str,
        local_path: str,
        permission: Permission,
    ) -> Project:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("项目名称不能为空")
        resolved = self._resolve_repo(local_path)

        project = await offload(self._modify, project_id, clean_name, resolved, permission)
        logger.info(
            "更新项目 #%d →「%s」%s（%s）", project_id, clean_name, resolved, permission.value
        )
        if project.local_path == resolved:  # 路径没变就不用重新探测
            return project
        return await self.refresh(project_id)

    async def delete(self, project_id: int) -> Project:
        project = await self.get(project_id)
        await offload(self._remove, project_id)
        logger.info("删除项目 #%d「%s」（%s）", project_id, project.name, project.local_path)
        return project

    async def refresh(self, project_id: int) -> Project:
        project = await self.get(project_id)
        status = await self._git.probe(project.local_path)
        updated = await offload(self._save_status, project_id, status)
        return updated or project

    async def refresh_all(self, *, on_progress: Progress | None = None) -> list[Project]:
        projects = await self.list_projects()
        if not projects:
            logger.info("刷新全部：暂无项目")
            return []

        total = len(projects)
        logger.info("刷新全部：开始探测 %d 个仓库（并发 %d）", total, GIT_CONCURRENCY)
        _notify(on_progress, 0, total)
        done = itertools.count(1)

        async def probe(project: Project) -> GitStatus:
            status = await self._git.probe(project.local_path)
            _notify(on_progress, next(done), total)
            return status

        statuses = await gather_limited(projects, probe, limit=GIT_CONCURRENCY)
        pairs = [(project.id, status) for project, status in zip(projects, statuses, strict=True)]
        updated = await offload(self._save_statuses, pairs)

        dirty = sum(1 for status in statuses if status.has_local_changes)
        broken = [
            project.name for project, status in zip(projects, statuses, strict=True) if status.error
        ]
        logger.info("刷新全部：完成 %d 个仓库，%d 个有待提交变更", len(updated), dirty)
        for name in broken:
            logger.warning("刷新全部：项目「%s」状态异常", name)
        return updated

    # ------------------------------------------------------------------ 提交
    async def preview(self, project_id: int) -> GitStatus:
        """提交前的实时预览：分支、领先/落后、待提交文件清单。"""
        project = await self.get(project_id)
        return await self._git.probe(project.local_path)

    async def commit(self, project_id: int, message: str, *, push: bool = True) -> CommitOutcome:
        project = await self.get(project_id)
        committed, pushed, detail, status = await self._git.commit(
            project.local_path, message, push=push
        )
        await offload(self._save_status, project_id, status)
        # git_service 记的是仓库路径，这里补上项目名，日志里才对得上界面
        level = logging.INFO if pushed or not push else logging.WARNING
        logger.log(level, "项目「%s」提交结果：%s", project.name, detail)
        return CommitOutcome(
            committed=committed,
            pushed=pushed,
            detail=detail,
            status=status,
        )

    # ------------------------------------------------------------------ 统计
    async def sync_history(
        self,
        project_id: int | None = None,
        *,
        on_progress: Progress | None = None,
    ) -> SyncOutcome:
        """采集 git 历史并写入数据库。单个项目失败不影响其余项目。"""
        targets = (
            [await self.get(project_id)] if project_id is not None else await self.list_projects()
        )
        if not targets:
            return SyncOutcome()

        logger.info("同步历史：开始采集 %d 个仓库", len(targets))
        created = updated = 0
        failures: list[str] = []
        for index, project in enumerate(targets, start=1):
            try:
                commits = await self._git.history(project.local_path, limit=GIT_HISTORY_LIMIT)
                new_count, changed_count = await offload(self._store_commits, project.id, commits)
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

    async def report(
        self,
        *,
        project_id: int | None = None,
        days: int | None = None,
        row_limit: int = REPORT_ROW_LIMIT,
    ) -> Report:
        return await offload(self._build_report, project_id, days, row_limit)

    # ------------------------------------------------------------------ 同步实现
    def _load_projects(self) -> list[Project]:
        with session_scope() as session:
            return project_repo.list_projects(session)

    def _load_project(self, project_id: int) -> Project | None:
        with session_scope() as session:
            return project_repo.get_project(session, project_id)

    def _insert(self, name: str, local_path: str, permission: Permission) -> Project:
        with session_scope() as session:
            if project_repo.find_by_path(session, local_path) is not None:
                raise ValueError("该路径已添加为项目")
            return project_repo.create_project(
                session,
                name=name,
                local_path=local_path,
                permission=permission,
                now=datetime.now(),
            )

    def _modify(
        self,
        project_id: int,
        name: str,
        local_path: str,
        permission: Permission,
    ) -> Project:
        with session_scope() as session:
            existing = project_repo.find_by_path(session, local_path)
            if existing is not None and existing.id != project_id:
                raise ValueError("该路径已被其他项目占用")
            project = project_repo.update_project(
                session,
                project_id,
                name=name,
                local_path=local_path,
                permission=permission,
                now=datetime.now(),
            )
            if project is None:
                raise ValueError("项目不存在或已被删除")
            return project

    def _remove(self, project_id: int) -> None:
        with session_scope() as session:
            commit_repo.delete_for_project(session, project_id)
            if not project_repo.delete_project(session, project_id):
                raise ValueError("项目不存在或已被删除")

    def _save_status(self, project_id: int, status: GitStatus) -> Project | None:
        with session_scope() as session:
            return project_repo.save_status(session, project_id, status, now=datetime.now())

    def _save_statuses(self, pairs: Sequence[tuple[int, GitStatus]]) -> list[Project]:
        now = datetime.now()
        updated: list[Project] = []
        with session_scope() as session:
            for project_id, status in pairs:
                project = project_repo.save_status(session, project_id, status, now=now)
                if project is not None:
                    updated.append(project)
        return updated

    def _store_commits(self, project_id: int, commits: Sequence[Commit]) -> tuple[int, int]:
        with session_scope() as session:
            return commit_repo.upsert_commits(session, project_id, commits)

    def _build_report(
        self,
        project_id: int | None,
        days: int | None,
        row_limit: int,
    ) -> Report:
        since = None if days is None else date.today() - timedelta(days=days - 1)
        with session_scope() as session:
            names = {project.id: project.name for project in project_repo.list_projects(session)}
            commits_count, insertions, deletions, files_changed, active = commit_repo.totals(
                session, project_id=project_id, since=since
            )
            daily = commit_repo.daily_totals(session, project_id=project_id, since=since)
            grouped = commit_repo.project_totals(session, project_id=project_id, since=since)
            total_rows = commit_repo.count(session, project_id=project_id, since=since)
            commits = commit_repo.list_commits(
                session, project_id=project_id, since=since, limit=row_limit
            )

        return Report(
            totals=Totals(
                commits=commits_count,
                insertions=insertions,
                deletions=deletions,
                files_changed=files_changed,
                active_projects=active,
            ),
            trend=_build_trend(daily, days),
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

    @staticmethod
    def _resolve_repo(local_path: str) -> str:
        """校验并规范化用户填入的目录。

        路径可能来自浏览按钮，也可能是直接粘贴的（带引号、``file://`` 前缀、
        正斜杠……），所以先走 ``core.paths.normalize`` 收敛形态；判据与界面上的
        即时提示同源（``core.paths.problem``），界面说可用就不会在这里再被拒。
        """
        issue = problem(local_path)
        if issue:
            logger.warning("路径校验未通过：%r → %s", local_path, issue)
            raise ValueError(issue)
        return str(Path(normalize(local_path)).resolve())


# --------------------------------------------------------------------------- 辅助
def _build_trend(
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
