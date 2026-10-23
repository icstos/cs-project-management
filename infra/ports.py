"""基础设施层对外暴露的**抽象接口**。

上层（service）只依赖这里的 ``Protocol``，不认识 SQLite、subprocess、git 命令行
或 flet CLI。组合根负责把具体实现注入进来，因此替换任何一项技术实现
（换数据库、换版本控制后端、换打包工具）都不需要改动业务代码。

这些协议只描述"能做什么"，不描述"怎么做"：
所有方法都返回 models 层的不可变对象，实现细节一律挡在接口之后。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from typing import Protocol, runtime_checkable

from models.dtos import (
    BuildOutcome,
    BuildPlan,
    CommandResult,
    Commit,
    CommitOutcome,
    GitStatus,
    Project,
    RemoveReport,
    TreeStats,
)
from models.enums import Permission

__all__ = [
    "CommandRunner",
    "CommitRepository",
    "FileSystemPort",
    "GitPort",
    "LineSink",
    "PackagerPort",
    "PathPort",
    "PhaseSink",
    "ProjectRepository",
    "SystemShellPort",
]

#: ``on_line(流名, 行内容)``，``流名`` 为 ``"out"`` / ``"err"``
LineSink = Callable[[str, str], None]
#: ``on_phase(阶段说明)``，用于把"现在卡在哪一步"透给上层
PhaseSink = Callable[[str], None]


@runtime_checkable
class CommandRunner(Protocol):
    """执行外部命令。退出码非零**不抛异常**，是否算失败由调用方判断。"""

    async def run(
        self,
        argv: Sequence[str],
        *,
        cwd: str | None = None,
        timeout: float | None = None,
        env: Mapping[str, str] | None = None,
        on_line: LineSink | None = None,
    ) -> CommandResult: ...


@runtime_checkable
class GitPort(Protocol):
    """读写本地 Git 仓库。"""

    def is_repo(self, path: str) -> bool: ...

    async def available(self) -> bool: ...

    async def probe(self, repo_path: str) -> GitStatus: ...

    async def history(self, repo_path: str, *, limit: int) -> list[Commit]: ...

    async def commit(self, repo_path: str, message: str, *, push: bool) -> CommitOutcome: ...


@runtime_checkable
class PackagerPort(Protocol):
    """把项目目录构建成可分发程序（``flet build``）。"""

    def peek_executable(self) -> str: ...

    async def probe(self) -> tuple[bool, str]: ...

    def clean_argv(self, plan: BuildPlan) -> tuple[str, ...]: ...

    def build_argv(self, plan: BuildPlan) -> tuple[str, ...]: ...

    def describe(self, plan: BuildPlan) -> tuple[str, ...]: ...

    async def run(
        self,
        plan: BuildPlan,
        *,
        on_line: LineSink | None = None,
        on_phase: PhaseSink | None = None,
    ) -> BuildOutcome: ...


@runtime_checkable
class ProjectRepository(Protocol):
    """项目台账的持久化。实现内部自行管理事务与连接。"""

    def list_all(self) -> list[Project]: ...

    def get(self, project_id: int) -> Project | None: ...

    def find_by_path(self, local_path: str) -> Project | None: ...

    def create(self, *, name: str, local_path: str, permission: Permission) -> Project: ...

    def update(
        self,
        project_id: int,
        *,
        name: str,
        local_path: str,
        permission: Permission,
    ) -> Project | None: ...

    def delete(self, project_id: int) -> bool: ...

    def save_status(self, project_id: int, status: GitStatus) -> Project | None: ...

    def save_statuses(self, entries: Sequence[tuple[int, GitStatus]]) -> list[Project]: ...


@runtime_checkable
class CommitRepository(Protocol):
    """提交历史与统计聚合。"""

    def upsert(self, project_id: int, commits: Sequence[Commit]) -> tuple[int, int]: ...

    def delete_for_project(self, project_id: int) -> int: ...

    def count(self, *, project_id: int | None = None, since: date | None = None) -> int: ...

    def list_commits(
        self,
        *,
        project_id: int | None = None,
        since: date | None = None,
        limit: int | None = None,
    ) -> list[Commit]: ...

    def totals(
        self, *, project_id: int | None = None, since: date | None = None
    ) -> tuple[int, int, int, int, int]: ...

    def daily_totals(
        self, *, project_id: int | None = None, since: date | None = None
    ) -> list[tuple[str, int, int, int]]: ...

    def project_totals(
        self, *, project_id: int | None = None, since: date | None = None
    ) -> list[tuple[int, int, int, int]]: ...


@runtime_checkable
class FileSystemPort(Protocol):
    """目录占用统计与"能删得掉"的递归删除。"""

    def tree_stats(self, root: str) -> TreeStats: ...

    def remove_tree(self, root: str) -> RemoveReport: ...


@runtime_checkable
class SystemShellPort(Protocol):
    """操作系统集成。"""

    def reveal(self, path: str) -> tuple[bool, str]: ...

    def notify_changed(self, path: str) -> None:
        """告诉外壳「这个目录的状态变了」，让资源管理器与 Git 客户端的角标重新读取。"""
        ...


@runtime_checkable
class PathPort(Protocol):
    """把用户带来的各种路径写法收敛成本机可用形态，并给出可用性判据。"""

    def normalize(self, raw: str) -> str: ...

    def has_paste_marks(self, raw: str) -> bool: ...

    def problem(self, raw: str) -> str | None: ...

    def suggest_name(self, raw: str) -> str: ...
