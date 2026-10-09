"""提交记录表的持久化实现（:class:`~infra.ports.CommitRepository`）。

批量写入采用"先比对、只更新真正变化的行"的策略：既避免逐条 SELECT，
也避免无谓的 UPDATE，几千条历史基本一次提交完成。统计聚合全部下推到 SQL。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, time

from sqlalchemy import delete, func, update
from sqlmodel import select

from infra.persistence.database import Database
from infra.persistence.entities import CommitEntity
from models.dtos import Commit, as_local_naive

_SCALARS = select(
    CommitEntity.id,
    CommitEntity.commit_hash,
    CommitEntity.author,
    CommitEntity.message,
    CommitEntity.committed_at,
    CommitEntity.insertions,
    CommitEntity.deletions,
    CommitEntity.files_changed,
)


class SqlCommitRepository:
    """基于 SQLModel 的提交历史仓储。"""

    def __init__(self, database: Database) -> None:
        self._db = database

    # ------------------------------------------------------------------ 写入
    def upsert(self, project_id: int, commits: Sequence[Commit]) -> tuple[int, int]:
        """写入提交历史，返回 (新增条数, 更新条数)。"""
        if not commits:
            return (0, 0)

        created = updated = 0
        with self._db.session() as session:
            existing = {
                row.commit_hash: row
                for row in session.exec(_SCALARS.where(CommitEntity.project_id == project_id)).all()
            }
            for commit in commits:
                row = existing.get(commit.commit_hash)
                if row is None:
                    session.add(_to_entity(project_id, commit))
                    created += 1
                    continue
                if _signature(commit) == _row_signature(row):
                    continue
                session.execute(
                    update(CommitEntity)
                    .where(CommitEntity.id == row.id)
                    .values(
                        author=commit.author,
                        message=commit.message,
                        committed_at=commit.committed_at,
                        insertions=commit.insertions,
                        deletions=commit.deletions,
                        files_changed=commit.files_changed,
                    )
                )
                updated += 1
            session.flush()
        return (created, updated)

    def delete_for_project(self, project_id: int) -> int:
        with self._db.session() as session:
            result = session.execute(
                delete(CommitEntity).where(CommitEntity.project_id == project_id)
            )
            return int(result.rowcount or 0)

    # ------------------------------------------------------------------ 查询
    def count(self, *, project_id: int | None = None, since: date | None = None) -> int:
        statement = select(func.count(CommitEntity.id)).where(*_conditions(project_id, since))
        with self._db.session() as session:
            return int(session.exec(statement).one() or 0)

    def list_commits(
        self,
        *,
        project_id: int | None = None,
        since: date | None = None,
        limit: int | None = None,
    ) -> list[Commit]:
        statement = (
            select(CommitEntity)
            .where(*_conditions(project_id, since))
            .order_by(CommitEntity.committed_at.desc(), CommitEntity.id.desc())
        )
        if limit is not None:
            statement = statement.limit(limit)
        with self._db.session() as session:
            return [_to_dto(entity) for entity in session.exec(statement).all()]

    def totals(
        self, *, project_id: int | None = None, since: date | None = None
    ) -> tuple[int, int, int, int, int]:
        """返回 (提交数, 新增行, 删除行, 变更文件数, 活跃项目数)。"""
        statement = select(
            func.count(CommitEntity.id),
            func.coalesce(func.sum(CommitEntity.insertions), 0),
            func.coalesce(func.sum(CommitEntity.deletions), 0),
            func.coalesce(func.sum(CommitEntity.files_changed), 0),
            func.count(func.distinct(CommitEntity.project_id)),
        ).where(*_conditions(project_id, since))
        with self._db.session() as session:
            row = session.exec(statement).one()
        return (int(row[0]), int(row[1]), int(row[2]), int(row[3]), int(row[4]))

    def daily_totals(
        self, *, project_id: int | None = None, since: date | None = None
    ) -> list[tuple[str, int, int, int]]:
        """按天聚合，返回 (YYYY-MM-DD, 提交数, 新增行, 删除行)。"""
        day = func.date(CommitEntity.committed_at)
        statement = (
            select(
                day,
                func.count(CommitEntity.id),
                func.coalesce(func.sum(CommitEntity.insertions), 0),
                func.coalesce(func.sum(CommitEntity.deletions), 0),
            )
            .where(*_conditions(project_id, since))
            .group_by(day)
            .order_by(day)
        )
        with self._db.session() as session:
            return [
                (str(row[0]), int(row[1]), int(row[2]), int(row[3]))
                for row in session.exec(statement).all()
            ]

    def project_totals(
        self, *, project_id: int | None = None, since: date | None = None
    ) -> list[tuple[int, int, int, int]]:
        """按项目聚合，返回 (项目 ID, 提交数, 新增行, 删除行)。"""
        statement = (
            select(
                CommitEntity.project_id,
                func.count(CommitEntity.id),
                func.coalesce(func.sum(CommitEntity.insertions), 0),
                func.coalesce(func.sum(CommitEntity.deletions), 0),
            )
            .where(*_conditions(project_id, since))
            .group_by(CommitEntity.project_id)
            .order_by(func.count(CommitEntity.id).desc())
        )
        with self._db.session() as session:
            return [
                (int(row[0]), int(row[1]), int(row[2]), int(row[3]))
                for row in session.exec(statement).all()
            ]


# --------------------------------------------------------------------------- 内部
def _conditions(project_id: int | None, since: date | None) -> list:
    clauses = []
    if project_id is not None:
        clauses.append(CommitEntity.project_id == project_id)
    if since is not None:
        clauses.append(CommitEntity.committed_at >= datetime.combine(since, time.min))
    return clauses


def _to_dto(entity: CommitEntity) -> Commit:
    return Commit(
        commit_hash=entity.commit_hash,
        message=entity.message,
        committed_at=as_local_naive(entity.committed_at),
        project_id=entity.project_id,
        author=entity.author,
        insertions=entity.insertions,
        deletions=entity.deletions,
        files_changed=entity.files_changed,
    )


def _to_entity(project_id: int, commit: Commit) -> CommitEntity:
    return CommitEntity(
        project_id=project_id,
        commit_hash=commit.commit_hash,
        author=commit.author,
        message=commit.message,
        committed_at=commit.committed_at,
        insertions=commit.insertions,
        deletions=commit.deletions,
        files_changed=commit.files_changed,
    )


def _signature(commit: Commit) -> tuple:
    return (
        commit.author,
        commit.message,
        commit.committed_at,
        commit.insertions,
        commit.deletions,
        commit.files_changed,
    )


def _row_signature(row) -> tuple:
    return (
        row.author,
        row.message,
        as_local_naive(row.committed_at),
        row.insertions,
        row.deletions,
        row.files_changed,
    )


__all__ = ["SqlCommitRepository"]
