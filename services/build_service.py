"""Flet 打包服务。

把"把某个项目打包成一个 Windows 程序"拆成可以单独验证的几步，每一步都能对用户
解释清楚：

1. **推导参数** ``plan()`` —— 纯计算，产物目录 = ``<发布根目录>/<源目录名>``，
   ``--artifact`` / ``--product`` 取台账里的项目名称；
2. **体检** ``precheck()`` —— 把"必然失败"的情况（源目录没了、模板目录没了、
   输出目录套在源目录里）拦在真正开跑之前，别让用户白等十分钟；
3. **腾空产物目录** ``inspect()`` / ``purge()`` —— 已有文件时由界面确认后才删，
   删不干净（文件被占用）由 ``core.fs`` 给出具体路径与原因；
4. **执行** ``run()`` —— 先用 ``core.fs`` 清掉源目录里的 ``build``（只读文件也删得掉），
   再跑 ``flet clean`` 兜底，最后 ``flet build``，输出按行实时回流给界面。

所有外部命令统一走 ``core.proc.run_command``：命令、工作目录、退出码、耗时与
完整输出都进日志，照着日志能把整轮打包原样重放一遍。
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import NamedTuple

from core import fs, shell
from core.config import (
    BUILD_CLEAN_TIMEOUT,
    BUILD_CLEANUP_GLOBS,
    BUILD_COMPANY,
    BUILD_COPYRIGHT,
    BUILD_OUTPUT_ROOT,
    BUILD_PROBE_TIMEOUT,
    BUILD_PYTHON_VERSION,
    BUILD_TARGET,
    BUILD_TEMPLATE_DIR,
    BUILD_TIMEOUT,
    FLET_EXECUTABLE_ENV,
)
from core.proc import (
    CommandError,
    CommandResult,
    LineSink,
    format_command,
    run_command,
    utf8_env,
)
from core.tasks import offload
from models.dto import BuildOutcome, BuildPlan, Project

logger = logging.getLogger(__name__)

PhaseSink = Callable[[str], None]
"""``on_phase(阶段说明)``，用于把"现在卡在哪一步"透给界面。"""

_SHORT_TAIL = 200


class BuildError(RuntimeError):
    """环境不满足打包条件（找不到 flet、源目录不可用……）。"""


class Readiness(NamedTuple):
    """打包前的体检结论。``issue`` 非空就不该让用户点开始。"""

    issue: str | None = None
    warnings: tuple[str, ...] = ()


class BuildService:
    """打包流程编排。无状态，可安全跨渲染复用。"""

    def __init__(self) -> None:
        self._executable: str | None = None

    # ------------------------------------------------------------------ flet CLI
    def executable(self) -> str:
        """拿到可用的 flet CLI 路径，找不到就抛 :class:`BuildError`。"""
        if self._executable is None:
            found = _locate_flet()
            if found is None:
                raise BuildError(
                    "未找到 flet 命令，无法打包。请确认已安装 flet CLI（pip install flet），"
                    f"或设置环境变量 {FLET_EXECUTABLE_ENV} 指向 flet 可执行文件。"
                )
            self._executable = found
            logger.debug("使用 flet CLI：%s", found)
        return self._executable

    def peek_executable(self) -> str:
        """给界面预览用的版本：找不到也不抛，退回裸 ``flet``。"""
        if self._executable:
            return self._executable
        return _locate_flet() or "flet"

    async def probe(self) -> tuple[bool, str]:
        """探测 flet CLI 是否可用，返回 ``(可用, 版本或原因)``。"""
        try:
            executable = self.executable()
        except BuildError as exc:
            return (False, str(exc))
        try:
            result = await run_command((executable, "--version"), timeout=BUILD_PROBE_TIMEOUT)
        except CommandError as exc:
            return (False, str(exc))
        if not result.ok:
            return (False, result.message)
        # flet --version 会输出两行（Flet / Flutter），取第一行当版本号
        text = (result.stdout or result.stderr).strip()
        return (True, text.splitlines()[0].strip() if text else "")

    # ------------------------------------------------------------------ 计划
    def plan(self, project: Project) -> BuildPlan:
        """按项目推导打包参数。**纯计算**，渲染时可以直接调用。"""
        source = Path(project.local_path)
        name = project.name.strip() or source.name
        return BuildPlan(
            project_id=project.id,
            # artifact / product 用台账里的项目名称（例如「文档编辑器」）
            project_name=name,
            source=str(source),
            output=str(BUILD_OUTPUT_ROOT / source.name),
            template=str(BUILD_TEMPLATE_DIR),
            company=BUILD_COMPANY,
            copyright=BUILD_COPYRIGHT,
            python_version=BUILD_PYTHON_VERSION,
            target=BUILD_TARGET,
            executable=self.peek_executable(),
            cleanup_globs=BUILD_CLEANUP_GLOBS,
        )

    def precheck(self, plan: BuildPlan) -> Readiness:
        """开始前的静态检查。返回的第一个 ``issue`` 会直接展示给用户。"""
        source = Path(plan.source)
        output = Path(plan.output)

        if not source.is_dir():
            return Readiness(issue=f"源目录不存在或不是目录：{plan.source}")
        if not Path(plan.template).is_dir():
            return Readiness(
                issue=f"Flutter 模板目录不存在：{plan.template}"
                "（可用环境变量 CSPM_FLET_TEMPLATE 指向别处）"
            )
        if not plan.project_name:
            return Readiness(issue="项目名称为空，无法作为 artifact / product")
        # 产物目录落在源目录里会把自己打包进去，越打越大
        if output == source or source in output.parents:
            return Readiness(issue="产物目录不能位于源目录内部，否则会把构建产物打包进去")

        warnings: list[str] = []
        if not source.joinpath("pyproject.toml").is_file():
            warnings.append("源目录缺少 pyproject.toml，flet build 可能拿不到应用元数据")
        return Readiness(issue=None, warnings=tuple(warnings))

    # ------------------------------------------------------------------ 产物目录
    async def inspect(self, output: str) -> fs.TreeStats:
        """统计产物目录现状。可能上万文件，丢线程池。"""
        return await offload(fs.tree_stats, output)

    async def purge(self, output: str) -> fs.RemoveReport:
        """删除产物目录。失败时 ``blockers`` 里有具体的阻塞路径。"""
        return await offload(fs.remove_tree, output)

    def open_target(self, path: str) -> tuple[bool, str]:
        """在文件管理器中打开目录（成功后返回 True）。"""
        return shell.reveal(path)

    # ------------------------------------------------------------------ 执行
    async def run(
        self,
        plan: BuildPlan,
        *,
        on_line: LineSink | None = None,
        on_phase: PhaseSink | None = None,
    ) -> BuildOutcome:
        """跑完整轮打包：清理 build 目录 → ``flet clean`` → ``flet build``。

        任一步失败立刻返回，不再往下走 —— 带着旧残留继续构建只会产出更迷惑的结果。
        """
        started = time.perf_counter()
        try:
            executable = self.executable()
        except BuildError as exc:
            logger.error("打包无法开始（%s）：%s", plan.project_name, exc)
            return BuildOutcome(ok=False, detail=str(exc), output=plan.output)

        plan = _with_executable(plan, executable)
        logger.info(
            "开始打包「%s」：%s → %s",
            plan.project_name,
            plan.source,
            plan.output,
        )

        # 1) 预清理：先把源目录里的 build 目录删掉。
        #    flet clean 用的是裸 shutil.rmtree，遇到只读文件就报 WinError 5 并直接退出 1
        #    —— 而 flet 会把整个项目复制进 build/ 里，项目自带的 .git/objects 全是只读的，
        #    所以"项目本身是 git 仓库"这一常见情况会让 flet clean 必然失败。
        #    core.fs.remove_tree 会先去掉只读位再删，这里先跑一遍；随后的 flet clean
        #    面对的只是一个不存在的目录（输出 "Nothing to clean" 并返回 0）。
        _notify(on_phase, "清理上一次构建的 build 目录")
        residue = await offload(fs.remove_tree, plan.build_dir)
        if not residue.ok:
            blocker = residue.first_blocker
            reason = blocker.reason if blocker else "未知原因"
            where = blocker.path if blocker else str(plan.build_dir)
            logger.error("打包终止：build 目录删不干净（%s）\n%s", reason, where)
            return self._fail(
                f"上一次构建的 build 目录删不掉（{reason}）：{where}。"
                "请先关掉占用它的程序（编辑器 / 资源管理器 / 终端）再重试",
                plan,
                started,
            )

        # 2) flet clean：清掉上一次构建留下的 build 目录
        _notify(on_phase, "flet clean：清理上一次构建的残留")
        try:
            clean = await self._step(plan, plan.clean_command(), BUILD_CLEAN_TIMEOUT, on_line)
        except BuildError as exc:
            return self._fail(f"flet clean 执行失败：{exc}", plan, started)
        if not clean.ok:
            logger.error("打包终止：flet clean 失败\n%s", clean.message)
            return self._fail(f"flet clean 失败：{_short(clean.message)}", plan, started)

        # 3) flet build
        _notify(on_phase, "flet build：正在构建（首次会下载 Flutter 依赖，可能较久）")
        try:
            build = await self._step(plan, plan.build_command(), BUILD_TIMEOUT, on_line)
        except BuildError as exc:
            return self._fail(f"flet build 执行失败：{exc}", plan, started)

        if not build.ok:
            logger.error("打包失败「%s」：\n%s", plan.project_name, build.message)
            return BuildOutcome(
                ok=False,
                detail=_failure_detail(build),
                command=build.command,
                output=plan.output,
                seconds=time.perf_counter() - started,
                lines=build.output_lines,
            )

        artifact = _find_artifact(Path(plan.output))
        seconds = time.perf_counter() - started
        logger.info(
            "打包完成「%s」：%s（%.1fs%s）",
            plan.project_name,
            plan.output,
            seconds,
            f"，产物 {artifact}" if artifact else "",
        )
        return BuildOutcome(
            ok=True,
            detail=f"打包完成，用时 {seconds:.0f} 秒" + (f"：{artifact}" if artifact else ""),
            command=build.command,
            output=plan.output,
            artifact=artifact,
            seconds=seconds,
            lines=build.output_lines,
        )

    # ------------------------------------------------------------------ 内部
    async def _step(
        self,
        plan: BuildPlan,
        argv: tuple[str, ...],
        timeout: float,
        on_line: LineSink | None,
    ) -> CommandResult:
        try:
            return await run_command(
                argv,
                cwd=plan.source,
                timeout=timeout,
                # flet CLI 是 Python 程序，默认按系统代码页（GBK）写输出，
                # rich 的状态图标 ✅ 编码不了就直接把构建打挂 —— 见 utf8_env 注释
                env=utf8_env(),
                on_line=on_line,
            )
        except CommandError as exc:
            raise BuildError(str(exc)) from exc

    def _fail(self, detail: str, plan: BuildPlan, started: float) -> BuildOutcome:
        logger.error("打包终止：%s", detail)
        return BuildOutcome(
            ok=False,
            detail=detail,
            output=plan.output,
            seconds=time.perf_counter() - started,
        )


# --------------------------------------------------------------------------- 工具
def _with_executable(plan: BuildPlan, executable: str) -> BuildPlan:
    if plan.executable == executable:
        return plan
    return replace(plan, executable=executable)


def _notify(sink: PhaseSink | None, text: str) -> None:
    logger.debug("打包阶段：%s", text)
    if sink is not None:
        sink(text)


def _locate_flet() -> str | None:
    """定位 flet CLI：环境变量 → 当前解释器同目录 → PATH。

    开发态下 ``sys.executable`` 的 ``Scripts/flet.exe`` 命中率最高，也最可靠
    （不依赖 PATH 被改对）；打包后的程序里没有它，自然回退到 PATH。
    """
    configured = os.environ.get(FLET_EXECUTABLE_ENV)
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_file():
            return str(candidate)
        logger.warning("%s 指向的文件不存在：%s", FLET_EXECUTABLE_ENV, configured)

    names = ("flet.exe", "flet") if os.name == "nt" else ("flet",)
    base = Path(sys.executable).parent
    for folder in (base / "Scripts", base / "bin", base):
        for name in names:
            candidate = folder / name
            if candidate.is_file():
                return str(candidate)
    return shutil.which("flet")


def _find_artifact(output: Path) -> str:
    """在产物目录里找可执行文件，找不到就返回空串。"""
    try:
        return next((str(item) for item in sorted(output.glob("*.exe"))), "")
    except OSError:
        return ""


def _short(text: str, limit: int = _SHORT_TAIL) -> str:
    """把命令输出压成一行摘要（完整内容在控制台与日志里）。"""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "命令没有输出"
    tail = lines[-1]
    return tail if len(tail) <= limit else tail[: limit - 1] + "…"


#: flet 会在 Flutter SDK 未通过校验时问 "Proceed? [y/n]" 并等待输入。窗口程序没有
#: 可交互的控制台（stdin 接的是空设备），这类提示只会让构建直接失败 —— 与其丢一个
#: EOFError 给用户，不如把"该怎么办"一起说出来。
_INTERACTIVE_HINTS: tuple[tuple[str, str], ...] = (
    (
        "Proceed?",
        "flet 在构建开始时要求交互确认（通常是本机 Flutter SDK 没通过版本校验）。"
        "请先在命令行里完整跑一次这条命令、按提示处理完，再回到这里打包",
    ),
)


def _interactive_hint(text: str) -> str:
    for marker, hint in _INTERACTIVE_HINTS:
        if marker in text:
            return hint
    return ""


def _failure_detail(result: CommandResult) -> str:
    """失败摘要：最后一行 + 可能的"该怎么办"。"""
    detail = f"打包失败：{_short(result.message)}"
    hint = _interactive_hint(f"{result.stdout}\n{result.stderr}")
    return f"{detail}；{hint}" if hint else detail


def describe(plan: BuildPlan) -> str:
    """界面用的命令行预览。"""
    return format_command(plan.build_command())


__all__ = ["BuildError", "BuildService", "Readiness", "describe"]
