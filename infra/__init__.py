"""基础设施层：封装底层技术实现，并对外暴露抽象接口。

上层只依赖 :mod:`infra.ports` 里的 ``Protocol``；本层的具体实现
（SQLite 仓储、子进程执行、git 命令行、flet CLI、本机文件系统、路径规则、
操作系统外壳、日志装配）都在这里，且不含任何业务规则。

依赖方向：``infra → models``，反向不成立。
"""

from infra.concurrency import gather_limited, offload
from infra.flet_cli import FletCli
from infra.git_cli import GitCli, GitError
from infra.localfs import LocalFileSystem
from infra.localpaths import LocalPaths
from infra.locations import (
    assets_dir,
    build_output_root,
    build_template_dir,
    data_dir,
    database_file,
    font_file,
    is_frozen,
    log_dir,
)
from infra.logs import LogSetup
from infra.persistence import Database, SqlCommitRepository, SqlProjectRepository
from infra.process import (
    CommandError,
    CommandNotFound,
    CommandTimeout,
    SubprocessRunner,
    utf8_env,
)
from infra.shell import ExplorerShell

__all__ = [
    "CommandError",
    "CommandNotFound",
    "CommandTimeout",
    "Database",
    "ExplorerShell",
    "FletCli",
    "GitCli",
    "GitError",
    "LocalFileSystem",
    "LocalPaths",
    "LogSetup",
    "SqlCommitRepository",
    "SqlProjectRepository",
    "SubprocessRunner",
    "assets_dir",
    "build_output_root",
    "build_template_dir",
    "data_dir",
    "database_file",
    "font_file",
    "gather_limited",
    "is_frozen",
    "log_dir",
    "offload",
    "utf8_env",
]
