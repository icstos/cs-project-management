"""业务数据契约。

界面与视图模型只认识这里的**不可变对象**，永远不接触 ORM 实体或数据库会话，
因此可以安全地跨线程传递、随意缓存，也不会出现"会话关闭后属性失效"的问题。

本模块只描述数据形状与它自身的派生读数（``net`` / ``short_hash`` / ``warnings``
之类的一次性推导），不编排任何流程；带副作用的逻辑属于 service，
带交互的逻辑属于 viewmodel。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from models.enums import ChangeKind, Permission

__all__ = [
    "Blocker",
    "BuildOutcome",
    "BuildPlan",
    "Change",
    "CommandResult",
    "Commit",
    "CommitOutcome",
    "CommitRow",
    "GitStatus",
    "Project",
    "ProjectTotals",
    "Readiness",
    "RemoveReport",
    "Report",
    "SyncOutcome",
    "Totals",
    "TreeStats",
    "TrendPoint",
    "as_local_naive",
]


def as_local_naive(value: datetime) -> datetime:
    """统一成本地时间的朴素 datetime，避免带时区与不带时区混存。"""
    if value.tzinfo is None:
        return value
    return value.astimezone().replace(tzinfo=None)


# --------------------------------------------------------------------------- Git
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
        if "U" in code or code in {"AA", "DD"}:
            return ChangeKind.CONFLICT
        if "R" in code:
            return ChangeKind.RENAMED
        if "A" in code:
            return ChangeKind.ADDED
        if "D" in code:
            return ChangeKind.DELETED
        if "T" in code:
            return ChangeKind.TYPE_CHANGED
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


# --------------------------------------------------------------------------- 外部命令
@dataclass(frozen=True, slots=True)
class CommandResult:
    """一次外部命令执行的结果。``stdout`` / ``stderr`` 已解码并去掉了行尾换行。"""

    argv: tuple[str, ...]
    cwd: str | None
    returncode: int
    stdout: str
    stderr: str
    seconds: float
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    @property
    def output_lines(self) -> int:
        return len(self.stdout.splitlines()) + len(self.stderr.splitlines())

    @property
    def command(self) -> str:
        """可读的命令行，用于日志与错误文案。"""
        return " ".join(f'"{arg}"' if " " in arg else arg for arg in self.argv)

    @property
    def message(self) -> str:
        """给人看的失败原因：优先 stderr，其次 stdout，都没有才用退出码兜底。"""
        return (
            self.stderr.strip()
            or self.stdout.strip()
            or f"{self.command} 执行失败（退出码 {self.returncode}，无输出）"
        )


# --------------------------------------------------------------------------- 文件系统
@dataclass(frozen=True, slots=True)
class TreeStats:
    """一个目录的占用概况。"""

    exists: bool = False
    files: int = 0
    directories: int = 0
    bytes: int = 0
    top: tuple[str, ...] = ()

    @property
    def empty(self) -> bool:
        """目录不存在、或存在但里面没有任何文件（空目录不影响打包）。"""
        return not self.exists or self.files == 0


@dataclass(frozen=True, slots=True)
class Blocker:
    """一个删不掉的条目。"""

    path: str
    reason: str
    locked: bool = False


@dataclass(frozen=True, slots=True)
class RemoveReport:
    """一次递归删除的结果。``removed`` 是**已删掉**的文件数，失败时也可能大于 0。"""

    ok: bool
    removed: int = 0
    total: int = 0
    blockers: tuple[Blocker, ...] = ()

    @property
    def first_blocker(self) -> Blocker | None:
        return self.blockers[0] if self.blockers else None

    @property
    def remaining(self) -> int:
        return max(self.total - self.removed, 0)


# --------------------------------------------------------------------------- 打包
@dataclass(frozen=True, slots=True)
class BuildPlan:
    """一次打包的完整参数。

    所有配置都在这里固化，命令构造因此是纯函数 —— 界面展示的命令行与实际
    执行的命令行必然一致，不会出现"看到的和跑的不是一条"。
    """

    project_id: int
    project_name: str
    source: str
    output: str
    template: str
    company: str
    copyright: str
    python_version: str
    target: str = "windows"
    executable: str = "flet"
    cleanup_globs: tuple[str, ...] = ("build",)

    @property
    def output_name(self) -> str:
        """产物目录名（取源目录名，便于和项目文件夹一一对应）。"""
        return Path(self.output).name

    @property
    def build_dir(self) -> Path:
        """flet 在源目录下的构建目录 —— ``flet clean`` 删的就是它。"""
        return Path(self.source) / (self.cleanup_globs[0] if self.cleanup_globs else "build")


@dataclass(frozen=True, slots=True)
class Readiness:
    """打包前的体检结论。``issue`` 非空就不该让用户点开始。"""

    issue: str | None = None
    warnings: tuple[str, ...] = ()
    #: Flutter bootstrap 模板目录是否就绪（界面上的一个状态角标）
    template_ok: bool = False

    @property
    def ready(self) -> bool:
        return self.issue is None


@dataclass(frozen=True, slots=True)
class BuildOutcome:
    """一次打包的结果。"""

    ok: bool
    detail: str
    command: str = ""
    output: str = ""
    artifact: str = ""
    seconds: float = 0.0
    lines: int = 0
