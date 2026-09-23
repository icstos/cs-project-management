"""项目表的数据访问。"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, select

from models.dto import GitStatus, Permission, Project, as_local_naive
from models.entities import ProjectEntity


def to_dto(entity: ProjectEntity) -> Project:
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


def list_projects(session: Session) -> list[Project]:
    statement = select(ProjectEntity).order_by(ProjectEntity.name)
    return [to_dto(entity) for entity in session.exec(statement).all()]


def get_project(session: Session, project_id: int) -> Project | None:
    entity = session.get(ProjectEntity, project_id)
    return to_dto(entity) if entity is not None else None


def find_by_path(session: Session, local_path: str) -> Project | None:
    statement = select(ProjectEntity).where(ProjectEntity.local_path == local_path)
    entity = session.exec(statement).first()
    return to_dto(entity) if entity is not None else None


def create_project(
    session: Session,
    *,
    name: str,
    local_path: str,
    permission: Permission,
    now: datetime,
) -> Project:
    entity = ProjectEntity(
        name=name,
        local_path=local_path,
        permission=permission.value,
        created_at=now,
        updated_at=now,
    )
    session.add(entity)
    session.flush()
    return to_dto(entity)


def update_project(
    session: Session,
    project_id: int,
    *,
    name: str,
    local_path: str,
    permission: Permission,
    now: datetime,
) -> Project | None:
    entity = session.get(ProjectEntity, project_id)
    if entity is None:
        return None
    entity.name = name
    entity.local_path = local_path
    entity.permission = permission.value
    entity.updated_at = now
    session.add(entity)
    session.flush()
    return to_dto(entity)


def delete_project(session: Session, project_id: int) -> bool:
    entity = session.get(ProjectEntity, project_id)
    if entity is None:
        return False
    session.delete(entity)
    session.flush()
    return True


def save_status(
    session: Session,
    project_id: int,
    status: GitStatus,
    *,
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
    return to_dto(entity)
