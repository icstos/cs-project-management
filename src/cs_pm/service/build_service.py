"""Flet 打包的业务编排。

把"把某个项目打包成一个 Windows 程序"里**属于判断**的部分留在这里，
把**属于技术**的部分（拼 flet 命令行、跑子进程）交给
:class:`~cs_pm.infra.ports.PackagerPort`：

1. **推导参数** :meth:`BuildService.plan` —— 纯计算，产物目录 =
   ``<发布根目录>/<源目录名>``，``--artifact`` / ``--product`` 取台账里的项目名称；
2. **体检** :meth:`BuildService.precheck` —— 把"必然失败"的情况（源目录没了、
   模板目录没了、输出目录套在源目录里）拦在真正开跑之前，别让用户白等十分钟；
3. **腾出产物目录** :meth:`BuildService.inspect` / :meth:`BuildService.archive` ——
   已有文件时先把整个目录移入同级的「历史版本」文件夹（名字追加 ``-before-时间``），
   移不动（文件被占用）时返回具体原因，原目录保持原样；
4. **执行** :meth:`BuildService.run` —— 交给打包端口跑完整轮（默认先清源目录的
   ``build``；打包页的开关关掉时跳过清理，直接增量构建），输出按行实时回流。
"""

from __future__ import annotations

import logging
from pathlib import Path

from cs_pm.infra.concurrency import offload
from cs_pm.infra.ports import FileSystemPort, LineSink, PackagerPort, PhaseSink, SystemShellPort
from cs_pm.models.dtos import (
    ArchiveReport,
    BuildOutcome,
    BuildPlan,
    Project,
    Readiness,
    TreeStats,
)
from cs_pm.models.settings import BuildSettings, SettingsProvider

logger = logging.getLogger(__name__)

__all__ = ["BuildService"]


class BuildService:
    """打包流程编排。无状态，可安全跨渲染复用。"""

    def __init__(
        self,
        *,
        packager: PackagerPort,
        filesystem: FileSystemPort,
        shell: SystemShellPort,
        settings: SettingsProvider,
    ) -> None:
        self._packager = packager
        self._fs = filesystem
        self._shell = shell
        #: 「当前生效的参数」的取值函数。设置页改完立刻生效，不需要重启程序
        self._settings_of = settings

    # ------------------------------------------------------------------ 工具探测
    async def probe_tool(self) -> tuple[bool, str]:
        """探测 flet CLI 是否可用，返回 ``(可用, 版本或原因)``。"""
        return await self._packager.probe()

    def output_root(self) -> str:
        """发布根目录，供界面上的「打开发布目录」使用。"""
        return self._settings_of().output_root

    # ------------------------------------------------------------------ 计划
    def plan(self, project: Project, *, clean_build: bool = True) -> BuildPlan:
        """按项目推导打包参数。**纯计算**，渲染时可以直接调用。

        ``clean_build`` 由打包页的开关传入（不属于设置页的持久化参数）：
        它只决定"这轮构建要不要先删 ``build`` 目录"，默认从零构建。
        """
        return self.plan_with(self._settings_of(), project, clean_build=clean_build)

    def plan_with(
        self, settings: BuildSettings, project: Project, *, clean_build: bool = True
    ) -> BuildPlan:
        """用给定的一份参数推导计划。

        设置页需要「改了还没保存」时的命令预览，所以把参数包显式传进来 ——
        与真正执行时走的是同一个函数，预览必然等于落地后的命令。
        """
        source = Path(project.local_path)
        return BuildPlan(
            project_id=project.id,
            # artifact / product 用台账里的项目名称（例如「文档编辑器」）；
            # 名称为空时回退源目录名，否则 flet build 拿不到合法的产物名
            project_name=project.name.strip() or source.name,
            source=str(source),
            output=str(Path(settings.output_root) / source.name),
            template=settings.template_dir,
            company=settings.company,
            copyright=settings.copyright,
            python_version=settings.python_version,
            target=settings.target,
            executable=self._packager.peek_executable(),
            cleanup_globs=settings.cleanup_globs,
            org=settings.org,
            description=settings.description,
            build_version=settings.build_version,
            build_number=settings.build_number,
            module_name=settings.module_name,
            cleanup_app=settings.cleanup_app,
            cleanup_packages=settings.cleanup_packages,
            compile_app=settings.compile_app,
            compile_packages=settings.compile_packages,
            assume_yes=settings.assume_yes,
            skip_flutter_doctor=settings.skip_flutter_doctor,
            verbose=settings.verbose,
            exclude_globs=settings.exclude_globs,
            include_globs=settings.include_globs,
            clean_build=clean_build,
        )

    def precheck(self, plan: BuildPlan) -> Readiness:
        """开始前的静态检查。返回的 ``issue`` 会直接展示给用户。"""
        source = Path(plan.source)
        output = Path(plan.output)
        template_ok = _template_ready(plan.template)

        if not source.is_dir():
            return Readiness(
                issue=f"源目录不存在或不是目录：{plan.source}", template_ok=template_ok
            )
        if not template_ok:
            return Readiness(
                issue=f"Flutter 模板目录不存在：{plan.template}"
                "（在「设置」页改成实际目录，或用环境变量 CSPM_FLET_TEMPLATE 指定）",
                template_ok=False,
            )
        if not plan.project_name:
            return Readiness(issue="项目名称为空，无法作为 artifact / product", template_ok=True)
        # 产物目录落在源目录里会把自己打包进去，越打越大
        if output == source or source in output.parents:
            return Readiness(
                issue="产物目录不能位于源目录内部，否则会把构建产物打包进去", template_ok=True
            )

        warnings: list[str] = []
        if not source.joinpath("pyproject.toml").is_file():
            warnings.append("源目录缺少 pyproject.toml，flet build 可能拿不到应用元数据")
        return Readiness(issue=None, warnings=tuple(warnings), template_ok=True)

    def preview_steps(self, plan: BuildPlan, *, archive: bool = False) -> tuple[str, ...]:
        """界面上的"将要执行的步骤"，与实际执行同源。

        ``archive`` 由打包页按产物目录的**现状**传入：非空时第一步是"把旧产物
        整体移入历史版本"，移完才轮到清理与构建。
        """
        steps = self._packager.describe(plan)
        if not archive:
            return steps
        return (f"把已有产物移入历史版本：{plan.history_dir}", *steps)

    # ------------------------------------------------------------------ 产物目录
    async def inspect(self, output: str) -> TreeStats:
        """统计产物目录现状。可能上万文件，丢线程池。"""
        return await offload(self._fs.tree_stats, output)

    async def archive(self, plan: BuildPlan) -> ArchiveReport:
        """把上一次的产物整体移入历史版本，返回**实际**落到的路径。

        移动而不是删除：存档目录与产物目录同父级（同一个卷），改名即完成，
        不占额外空间，旧版本随时可翻回来。移不动（多半是里面的程序还在运行）
        时原目录保持原样，``reason`` 可直接展示。
        """
        target = plan.archive_target()
        logger.info("把已有产物移入历史版本：%s → %s", plan.output, target)
        report = await offload(self._fs.archive_tree, plan.output, str(target))
        if report.ok:
            logger.info("旧版本已存档：%s（%d 个文件）", report.target, report.files)
        else:
            logger.warning("旧版本存档失败：%s（%s）", report.source, report.reason)
        return report

    async def reveal(self, path: str) -> tuple[bool, str]:
        """在文件管理器中打开目录（成功后返回 True）。"""
        return await offload(self._shell.reveal, path)

    # ------------------------------------------------------------------ 执行
    async def run(
        self,
        plan: BuildPlan,
        *,
        on_line: LineSink | None = None,
        on_phase: PhaseSink | None = None,
    ) -> BuildOutcome:
        return await self._packager.run(plan, on_line=on_line, on_phase=on_phase)


def _template_ready(template: str) -> bool:
    """模板是否可用。

    ``--template`` 既可以是本地目录，也可以是 ``https://…`` / ``git@…`` 这类
    远程地址（flet 自己 clone），所以远程地址一律算"就绪"，别拿
    ``Path.is_dir()`` 把它们判成缺失。空值仍算缺失 —— 打包时 flet 会退回默认模板，
    但本项目默认值就是本地模板目录，空着多半是误改。
    """
    text = (template or "").strip()
    if not text:
        return False
    if "://" in text or text.startswith("git@"):
        return True
    return Path(text).is_dir()
