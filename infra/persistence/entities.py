"""SQLModel 表定义。

只描述"存什么"，不含任何业务规则。表名沿用历史库名，保证旧数据可直接读取。
ORM 实体是**持久化实现细节**，因此不放在 models 层、也不外泄给业务层。

时间列一律标注 :data:`~pydantic.NaiveDatetime`：全工程的时间语义是"本地时间的
朴素 datetime"（见 :func:`models.dtos.as_local_naive`），而 sqlmodel 会把裸
``datetime`` 映射成要求时区的 UTC 列，写入朴素值时会直接抛
``Datetime values must have timezone information``。历史库里存的也是朴素值，
所以不能用"改成 aware UTC"来绕过。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import NaiveDatetime
from sqlmodel import Field, SQLModel

from models.enums import Permission


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

    created_at: NaiveDatetime = Field(default_factory=datetime.now)
    updated_at: NaiveDatetime = Field(default_factory=datetime.now)


class CommitEntity(SQLModel, table=True):
    __tablename__ = "commitrecord"

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    commit_hash: str = Field(index=True)
    author: str = Field(default="")
    message: str = Field(default="")
    committed_at: NaiveDatetime = Field(index=True)
    insertions: int = Field(default=0)
    deletions: int = Field(default=0)
    files_changed: int = Field(default=0)


__all__ = ["CommitEntity", "ProjectEntity"]
