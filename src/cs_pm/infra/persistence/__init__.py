"""持久化实现：SQLite + SQLModel。

对外只暴露 :class:`~cs_pm.infra.ports.ProjectRepository` /
:class:`~cs_pm.infra.ports.CommitRepository` / :class:`~cs_pm.infra.ports.SettingsPort`
三个抽象接口的具体实现，上层不认识 Session，也不认识实体。
"""

from cs_pm.infra.persistence.commit_store import SqlCommitRepository
from cs_pm.infra.persistence.database import Database
from cs_pm.infra.persistence.project_store import SqlProjectRepository
from cs_pm.infra.persistence.settings_store import SqlSettingsRepository

__all__ = [
    "Database",
    "SqlCommitRepository",
    "SqlProjectRepository",
    "SqlSettingsRepository",
]
