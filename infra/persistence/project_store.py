"""项目台账的持久化实现（:class:`~infra.ports.ProjectRepository`）。

对外只返回 models 层的冻结 DTO，实体不会外泄；每个方法自己开事务，
上层因此完全看不到 Session 的存在。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlmodel import select

from infra.persistence.database import Database
from infra.persistence.entities import ProjectEntity
from models.dtos import GitStatus, Project, as_local_naive
from models.enums import Permission


def _to_dto(entity: ProjectEntity) -> Project:
    return Project(
        id=entity.id or 0,
        name=entity.name,
        local_path=entity.local_path,
        created_at=as_local_naive(entity.created_at),
        updated_at=as_local_naive(entity.updated_at),
        permission=Permission.parse(entity.permission),
        has_remote=entity.has_remote,
        has_local_changes=entity.has_local_changes,
        has_gitignore=entity.has_gitignore,
        branch=entity.branch,
        changed_files=entity.changed_files,
        ahead=entity.ahead,
        behind=entity.behind,
        last_error=entity.last_error,
    )


class SqlProjectRepository:
    """基于 SQLModel 的项目台账仓储。"""

    def __init__(self, database: Database) -> None:
        self._db = database

    # ------------------------------------------------------------------ 读取
    def list_all(self) -> list[Project]:
        with self._db.session() as session:
            statement = select(ProjectEntity).order_by(ProjectEntity.name)
            return [_to_dto(entity) for entity in session.exec(statement).all()]

    def get(self, project_id: int) -> Project | None:
        with self._db.session() as session:
            return self._one(session.get(ProjectEntity, project_id))

    def find_by_path(self, local_path: str) -> Project | None:
        with self._db.session() as session:
            statement = select(ProjectEntity).where(ProjectEntity.local_path == local_path)
            return self._one(session.exec(statement).first())

    # ------------------------------------------------------------------ 写入
    def create(self, *, name: str, local_path: str, permission: Permission) -> Project:
        now = datetime.now()
        with self._db.session() as session:
            entity = ProjectEntity(
                name=name,
                local_path=local_path,
                permission=permission.value,
                created_at=now,
                updated_at=now,
            )
            session.add(entity)
            session.flush()
            return _to_dto(entity)

    def update(
        self,
        project_id: int,
        *,
        name: str,
        local_path: str,
        permission: Permission,
    ) -> Project | None:
        with self._db.session() as session:
            entity = session.get(ProjectEntity, project_id)
            if entity is None:
                return None
            entity.name = name
            entity.local_path = local_path
            entity.permission = permission.value
            entity.updated_at = datetime.now()
            session.add(entity)
            session.flush()
            return _to_dto(entity)

    def delete(self, project_id: int) -> bool:
        with self._db.session() as session:
            entity = session.get(ProjectEntity, project_id)
            if entity is None:
                return False
            session.delete(entity)
            session.flush()
            return True

    def save_status(self, project_id: int, status: GitStatus) -> Project | None:
        with self._db.session() as session:
            return self._apply(session, project_id, status, datetime.now())

    def save_statuses(self, entries: Sequence[tuple[int, GitStatus]]) -> list[Project]:
        now = datetime.now()
        updated: list[Project] = []
        with self._db.session() as session:
            for project_id, status in entries:
                project = self._apply(session, project_id, status, now)
                if project is not None:
                    updated.append(project)
        return updated

    # ------------------------------------------------------------------ 内部
    @staticmethod
    def _one(entity: ProjectEntity | None) -> Project | None:
        return _to_dto(entity) if entity is not None else None

    @staticmethod
    def _apply(
        session,
        project_id: int,
        status: GitStatus,
        now: datetime,
    ) -> Project | None:
        """把一次仓库探测结果落库。"""
        entity = session.get(ProjectEntity, project_id)
        if entity is None:
            return None
        entity.has_remote = status.has_remote
        entity.has_local_changes = status.has_local_changes
        entity.has_gitignore = status.has_gitignore
        entity.branch = status.branch
        entity.changed_files = status.change_count
        entity.ahead = status.ahead
        entity.behind = status.behind
        entity.last_error = status.error
        entity.updated_at = now
        session.add(entity)
        session.flush()
        return _to_dto(entity)


__all__ = ["SqlProjectRepository"]
