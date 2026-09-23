"""数据契约与表定义。

``models.database`` 需要显式导入（它会读配置、建引擎），
因此不在这里转出，避免"导入即建库"的副作用。
"""

from models.dto import (
    Change,
    ChangeKind,
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
    as_local_naive,
)
from models.entities import CommitEntity, ProjectEntity

__all__ = [
    "Change",
    "ChangeKind",
    "Commit",
    "CommitEntity",
    "CommitOutcome",
    "CommitRow",
    "GitStatus",
    "Permission",
    "Project",
    "ProjectEntity",
    "ProjectTotals",
    "Report",
    "SyncOutcome",
    "Totals",
    "TrendPoint",
    "as_local_naive",
]
