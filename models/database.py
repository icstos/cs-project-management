from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Generator, Optional

from sqlmodel import Field, Session, SQLModel, create_engine, select

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "app.db"


class Permission(str, Enum):
    PUBLIC = "public"
    PRIVATE = "private"

    @property
    def label(self) -> str:
        return "公开" if self is Permission.PUBLIC else "私有"


class Project(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    local_path: str = Field(unique=True, index=True)
    has_remote: bool = False
    has_local_changes: bool = False
    permission: str = Field(default=Permission.PRIVATE.value)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    @property
    def permission_label(self) -> str:
        try:
            return Permission(self.permission).label
        except ValueError:
            return self.permission


class CommitRecord(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    commit_hash: str = Field(index=True)
    message: str
    committed_at: datetime = Field(index=True)
    insertions: int = 0
    deletions: int = 0
    files_changed: int = 0


engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


def session_scope() -> Session:
    return Session(engine)


def list_projects(session: Session) -> list[Project]:
    return list(session.exec(select(Project).order_by(Project.name)).all())


def get_project(session: Session, project_id: int) -> Optional[Project]:
    return session.get(Project, project_id)


def get_project_by_path(session: Session, local_path: str) -> Optional[Project]:
    normalized = str(Path(local_path).resolve())
    return session.exec(select(Project).where(Project.local_path == normalized)).first()


def save_project(session: Session, project: Project) -> Project:
    project.local_path = str(Path(project.local_path).resolve())
    project.updated_at = datetime.now()
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def delete_project(session: Session, project_id: int) -> bool:
    project = session.get(Project, project_id)
    if not project:
        return False
    for record in session.exec(
        select(CommitRecord).where(CommitRecord.project_id == project_id)
    ).all():
        session.delete(record)
    session.delete(project)
    session.commit()
    return True


def list_commit_records(
    session: Session, project_id: Optional[int] = None
) -> list[CommitRecord]:
    stmt = select(CommitRecord).order_by(CommitRecord.committed_at.desc())
    if project_id is not None:
        stmt = stmt.where(CommitRecord.project_id == project_id)
    return list(session.exec(stmt).all())


def upsert_commit_records(
    session: Session, project_id: int, records: list[CommitRecord]
) -> int:
    existing = {
        row.commit_hash: row
        for row in session.exec(
            select(CommitRecord).where(CommitRecord.project_id == project_id)
        ).all()
    }
    saved = 0
    for record in records:
        record.project_id = project_id
        if record.commit_hash in existing:
            stored = existing[record.commit_hash]
            stored.message = record.message
            stored.committed_at = record.committed_at
            stored.insertions = record.insertions
            stored.deletions = record.deletions
            stored.files_changed = record.files_changed
            session.add(stored)
        else:
            session.add(record)
        saved += 1
    session.commit()
    return saved
