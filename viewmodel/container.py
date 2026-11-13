"""组合根：把基础设施实现装配成服务，再把服务装配成视图模型。

整个程序只有这里认识**具体**实现（SQLite 仓储、subprocess、git CLI、flet CLI），
也只有这里把外部配置（环境变量、运行环境）翻译成注入用的参数包。
换掉任何一项技术实现，只需要改这个文件；上层代码一行都不用动。

打包参数是全程序唯一一份"用户能改的配置"，因此它的流向要看清：
``环境/运行环境推导的默认值`` → :class:`~service.settings_service.SettingsService`
（合并数据库里保存过的值）→ **取值函数** ``lambda: settings_service.current`` 注入
打包服务与 flet CLI。注入的是函数不是值 —— 设置页保存后下一次取参数就是新的，
不需要重启程序。
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from infra import locations
from infra.flet_cli import FletCli
from infra.git_cli import GitCli
from infra.localfs import LocalFileSystem
from infra.localpaths import LocalPaths
from infra.logs import LogSetup
from infra.persistence import (
    Database,
    SqlCommitRepository,
    SqlProjectRepository,
    SqlSettingsRepository,
)
from infra.process import SubprocessRunner
from infra.shell import ExplorerShell
from models.settings import (
    BuildSettings,
    GitSettings,
    LogSettings,
    env_flag,
)
from service import BuildService, CommitService, ProjectService, ReportService, SettingsService
from viewmodel.app_vm import AppViewModel

__all__ = ["Application", "Services", "build_application"]


@dataclass(frozen=True, slots=True)
class Services:
    """服务层的五个入口，界面只需认识它们。"""

    projects: ProjectService
    commits: CommitService
    reports: ReportService
    build: BuildService
    settings: SettingsService


@dataclass(frozen=True, slots=True)
class Application:
    """装配完成的程序：日志、数据库、服务与视图模型工厂。"""

    log: LogSetup
    database: Database
    services: Services

    def start(self, *, flet_version: str = "") -> None:
        """进程起步：装配日志并记下启动环境。

        必须在 ``ft.run`` **之前**调用 —— flet 只在根 logger 还没有 handler 时
        才 ``basicConfig``，先装好才能把框架自身的日志一起收进文件。
        """
        self.log.setup()
        self.log.log_startup(flet=flet_version)

    def prepare(self) -> None:
        """会话起步：在事件循环内装异常钩子，建表并把保存的设置读进来。

        顺序不能反：设置存在数据库里，``initialize`` 之前读不到表。
        """
        self.log.install_hooks()
        self.database.initialize()
        self.services.settings.reload()

    def create_view_model(self) -> AppViewModel:
        """每个窗口一份视图模型（状态不能跨会话共享）。"""
        return AppViewModel(
            projects=self.services.projects,
            commits=self.services.commits,
            reports=self.services.reports,
            build=self.services.build,
            settings=self.services.settings,
        )


def build_application() -> Application:
    """按依赖方向自下而上装配：infra → service → viewmodel。"""
    runner = SubprocessRunner()
    paths = LocalPaths()
    shell = ExplorerShell()

    # ---------------------------------------------------------------- 配置
    git_settings = GitSettings()
    build_defaults = _build_settings()

    # ---------------------------------------------------------------- 基础设施
    database = Database(locations.database_file())
    project_store = SqlProjectRepository(database)
    commit_store = SqlCommitRepository(database)
    settings_store = SqlSettingsRepository(database)
    git = GitCli(runner, git_settings)
    filesystem = LocalFileSystem()

    # ---------------------------------------------------------------- 服务
    settings = SettingsService(store=settings_store, defaults=build_defaults)

    def current() -> BuildSettings:
        """「此刻生效的打包参数」。注入函数而不是参数包，设置页保存后立刻生效。"""
        return settings.current

    packager = FletCli(runner, current)

    services = Services(
        projects=ProjectService(
            projects=project_store,
            commits=commit_store,
            git=git,
            paths=paths,
            shell=shell,
            concurrency=git_settings.concurrency,
        ),
        commits=CommitService(projects=project_store, git=git, shell=shell),
        reports=ReportService(
            projects=project_store,
            commits=commit_store,
            git=git,
            history_limit=git_settings.history_limit,
        ),
        build=BuildService(
            packager=packager,
            filesystem=filesystem,
            shell=shell,
            settings=current,
        ),
        settings=settings,
    )

    return Application(
        log=LogSetup(LogSettings()),
        database=database,
        services=services,
    )


def _build_settings() -> BuildSettings:
    """把环境变量与运行环境翻译成打包参数的默认值。

    这些只是**默认值**：用户在「设置」页保存过的值会覆盖它们。
    """
    defaults = BuildSettings()
    output_root = locations.build_output_root(defaults.output_root)
    return replace(
        defaults,
        output_root=str(output_root),
        template_dir=str(locations.build_template_dir(output_root, defaults.executable_env)),
        company=env_flag("CSPM_BUILD_COMPANY", defaults.company),
        copyright=env_flag("CSPM_BUILD_COPYRIGHT", defaults.copyright),
        python_version=env_flag("CSPM_BUILD_PYTHON_VERSION", defaults.python_version),
        executable=env_flag(defaults.executable_env, ""),
    )
