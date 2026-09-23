"""业务数据契约。

界面层只认识这里的不可变对象，永远不接触 ORM 实体，
因此可以安全地跨线程传递、随意缓存，也不会出现会话关闭后属性失效的问题。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum


def as_local_naive(value: datetime) -> datetime:
    """统一成本地时间的朴素 datetime，避免带时区与不带时区混存。"""
    if value.tzinfo is None:
        return value
    return value.astimezone().replace(tzinfo=None)


class Permission(StrEnum):
    """项目可见性。"""

    PUBLIC = "public"
    PRIVATE = "private"

    @property
    def label(self) -> str:
        match self:
            case Permission.PUBLIC:
                return "公开"
            case _:
                return "私有"

    @property
    def icon(self) -> str:
        match self:
            case Permission.PUBLIC:
                return "public"
            case _:
                return "lock"

    @classmethod
    def parse(cls, value: str | None) -> Permission:
        """宽松解析：脏数据一律回退为私有。"""
        try:
            return cls(value) if value else cls.PRIVATE
        except ValueError:
            return cls.PRIVATE


# --------------------------------------------------------------------------- Git
class ChangeKind(StrEnum):
    """工作区变更类型，用于在提交页给出直观标记。"""

    MODIFIED = "modified"
    ADDED = "added"
    DELETED = "deleted"
    RENAMED = "renamed"
    UNTRACKED = "untracked"
    CONFLICT = "conflict"
    TYPE_CHANGED = "type_changed"

    @property
    def label(self) -> str:
        match self:
            case ChangeKind.ADDED:
                return "新增"
            case ChangeKind.DELETED:
                return "删除"
            case ChangeKind.RENAMED:
                return "重命名"
            case ChangeKind.UNTRACKED:
                return "未跟踪"
            case ChangeKind.CONFLICT:
                return "冲突"
            case ChangeKind.TYPE_CHANGED:
                return "类型变更"
            case _:
                return "已修改"

    @property
    def badge(self) -> str:
        match self:
            case ChangeKind.ADDED:
                return "A"
            case ChangeKind.DELETED:
                return "D"
            case ChangeKind.RENAMED:
                return "R"
            case ChangeKind.UNTRACKED:
                return "?"
            case ChangeKind.CONFLICT:
                return "U"
            case ChangeKind.TYPE_CHANGED:
                return "T"
            case _:
                return "M"


@dataclass(frozen=True, slots=True)
class Change:
    """一条工作区变更。``code`` 为 git porcelain 的原始状态码。"""

    code: str
    path: str

    @property
    def kind(self) -> ChangeKind:
        if self.code == "??":
            return ChangeKind.UNTRACKED
        code = self.code.replace(" ", "")
        match code:
            case "AA" | "DD" | "UU" if True:
                return ChangeKind.CONFLICT
            case _ if "U" in code:
                return ChangeKind.CONFLICT
            case _ if "R" in code:
                return ChangeKind.RENAMED
            case _ if "A" in code:
                return ChangeKind.ADDED
            case _ if "D" in code:
                return ChangeKind.DELETED
            case _ if "T" in code:
                return ChangeKind.TYPE_CHANGED
            case _:
                return ChangeKind.MODIFIED


@dataclass(frozen=True, slots=True)
class GitStatus:
    """一次仓库探测的结果快照。"""

    is_repo: bool = False
    has_remote: bool = False
    has_local_changes: bool = False
    has_gitignore: bool = False
    branch: str = ""
    upstream: str = ""
    ahead: int = 0
    behind: int = 0
    changes: tuple[Change, ...] = ()
    error: str = ""

    @property
    def change_count(self) -> int:
        return len(self.changes)


# --------------------------------------------------------------------------- 项目
@dataclass(frozen=True, slots=True)
class Project:
    id: int
    name: str
    local_path: str
    created_at: datetime
    updated_at: datetime
    permission: Permission = Permission.PRIVATE
    has_remote: bool = False
    has_local_changes: bool = False
    has_gitignore: bool = False
    branch: str = ""
    changed_files: int = 0
    ahead: int = 0
    behind: int = 0
    last_error: str = ""

    @property
    def is_clean(self) -> bool:
        return not self.has_local_changes

    @property
    def warnings(self) -> tuple[str, ...]:
        """需要用户关注的问题，用于卡片上的黄色提示。"""
        issues: list[str] = []
        if self.last_error:
            issues.append(f"仓库探测异常：{self.last_error}")
        if not self.has_remote:
            issues.append("未配置远程仓库")
        if not self.has_gitignore:
            issues.append("缺少 .gitignore")
        return tuple(issues)


# --------------------------------------------------------------------------- 提交
@dataclass(frozen=True, slots=True)
class Commit:
    commit_hash: str
    message: str
    committed_at: datetime
    project_id: int = 0
    author: str = ""
    insertions: int = 0
    deletions: int = 0
    files_changed: int = 0

    @property
    def short_hash(self) -> str:
        return self.commit_hash[:8]

    @property
    def net(self) -> int:
        return self.insertions - self.deletions


@dataclass(frozen=True, slots=True)
class CommitRow:
    """报表里的一行：提交记录 + 所属项目名。"""

    commit: Commit
    project_name: str


@dataclass(frozen=True, slots=True)
class Totals:
    commits: int = 0
    insertions: int = 0
    deletions: int = 0
    files_changed: int = 0
    active_projects: int = 0

    @property
    def net(self) -> int:
        return self.insertions - self.deletions


@dataclass(frozen=True, slots=True)
class TrendPoint:
    day: date
    commits: int = 0
    insertions: int = 0
    deletions: int = 0


@dataclass(frozen=True, slots=True)
class ProjectTotals:
    project_id: int
    project_name: str
    commits: int = 0
    insertions: int = 0
    deletions: int = 0

    @property
    def net(self) -> int:
        return self.insertions - self.deletions


@dataclass(frozen=True, slots=True)
class Report:
    """统计页所需的全部数据，一次查询就绪。"""

    totals: Totals = Totals()
    trend: tuple[TrendPoint, ...] = ()
    rows: tuple[CommitRow, ...] = ()
    per_project: tuple[ProjectTotals, ...] = ()
    row_count: int = 0
    truncated: bool = False


# --------------------------------------------------------------------------- 操作结果
@dataclass(frozen=True, slots=True)
class CommitOutcome:
    committed: bool
    pushed: bool
    detail: str
    status: GitStatus | None = None


@dataclass(frozen=True, slots=True)
class SyncOutcome:
    """历史采集结果。"""

    projects: int = 0
    created: int = 0
    updated: int = 0
    failures: tuple[str, ...] = ()

    @property
    def headline(self) -> str:
        if not self.projects:
            return "没有可采集的项目"
        summary = f"已采集 {self.projects} 个项目：新增 {self.created} 条，更新 {self.updated} 条"
        if self.failures:
            summary += f"，{len(self.failures)} 个失败"
        return summary
