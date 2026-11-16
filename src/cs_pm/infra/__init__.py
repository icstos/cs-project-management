"""基础设施层：封装底层技术实现，并对外暴露抽象接口。

上层只依赖 :mod:`cs_pm.infra.ports` 里的 ``Protocol``；本层的具体实现
（SQLite 仓储、子进程执行、git 命令行、flet CLI、本机文件系统、路径规则、
操作系统外壳、日志装配）都在这里，且不含任何业务规则。

依赖方向：``infra → models``，反向不成立。
"""

from cs_pm.infra.concurrency import gather_limited, offload
from cs_pm.infra.flet_cli import FletCli
from cs_pm.infra.git_cli import GitCli, GitError
from cs_pm.infra.localfs import LocalFileSystem
from cs_pm.infra.localpaths import LocalPaths
from cs_pm.infra.locations import (
    assets_dir,
    build_output_root,
    build_template_dir,
    data_dir,
    database_file,
    is_frozen,
    log_dir,
)
from cs_pm.infra.logs import LogSetup
from cs_pm.infra.persistence import Database, SqlCommitRepository, SqlProjectRepository
from cs_pm.infra.process import (
    CommandError,
    CommandNotFound,
    CommandTimeout,
    SubprocessRunner,
    utf8_env,
)
from cs_pm.infra.shell import ExplorerShell

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
    "gather_limited",
    "is_frozen",
    "log_dir",
    "offload",
    "utf8_env",
]
