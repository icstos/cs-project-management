"""SQLModel 表定义。

只描述"存什么"，不含任何业务规则；表名沿用历史库名，保证旧数据可直接读取。
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from models.dto import Permission


class ProjectEntity(SQLModel, table=True):
    __tablename__ = "project"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    local_path: str = Field(unique=True, index=True)
    permission: str = Field(default=Permission.PRIVATE.value)

    has_remote: bool = Field(default=False)
    has_local_changes: bool = Field(default=False)
    has_gitignore: bool = Field(default=False)
    branch: str = Field(default="")
    changed_files: int = Field(default=0)
    ahead: int = Field(default=0)
    behind: int = Field(default=0)
    last_error: str = Field(default="")

    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class CommitEntity(SQLModel, table=True):
    __tablename__ = "commitrecord"

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    commit_hash: str = Field(index=True)
    author: str = Field(default="")
    message: str = Field(default="")
    committed_at: datetime = Field(index=True)
    insertions: int = Field(default=0)
    deletions: int = Field(default=0)
    files_changed: int = Field(default=0)
