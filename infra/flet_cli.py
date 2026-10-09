"""flet CLI 封装（:class:`~infra.ports.PackagerPort` 的实现）。

把"把某个项目打包成一个 Windows 程序"里**纯技术**的部分包在这里：

* 定位 flet CLI 并探测它是否可用；
* 由 :class:`~models.dtos.BuildPlan` 拼出 ``flet clean`` / ``flet build`` 的命令行；
* 跑命令并把输出按行实时回流给上层。

"该不该打包""产物目录能不能用""下一轮要删什么"属于业务判断，在 service 层。
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import time
from dataclasses import replace
from pathlib import Path

from infra.concurrency import offload
from infra.localfs import remove_tree
from infra.ports import CommandRunner, LineSink, PhaseSink
from infra.process import CommandError, utf8_env
from models.dtos import BuildOutcome, BuildPlan, CommandResult
from models.settings import BuildSettings

logger = logging.getLogger(__name__)

_SHORT_TAIL = 200

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


class BuildError(RuntimeError):
    """环境不满足打包条件（找不到 flet、源目录不可用……）。"""


class FletCli:
    """``flet build`` 的调用器。无状态，可安全跨渲染复用。"""

    def __init__(self, runner: CommandRunner, settings: BuildSettings) -> None:
        self._runner = runner
        self._settings = settings
        self._executable: str | None = None

    # ------------------------------------------------------------------ 定位
    def executable(self) -> str:
        """拿到可用的 flet CLI 路径，找不到就抛 :class:`BuildError`。"""
        if self._executable is None:
            found = _locate_flet(self._settings)
            if found is None:
                raise BuildError(
                    "未找到 flet 命令，无法打包。请确认已安装 flet CLI（pip install flet），"
                    f"或设置环境变量 {self._settings.executable_env} 指向 flet 可执行文件。"
                )
            self._executable = found
            logger.debug("使用 flet CLI：%s", found)
        return self._executable

    def peek_executable(self) -> str:
        """给界面预览用的版本：找不到也不抛，退回裸 ``flet``。"""
        if self._executable:
            return self._executable
        return _locate_flet(self._settings) or "flet"

    async def probe(self) -> tuple[bool, str]:
        """探测 flet CLI 是否可用，返回 ``(可用, 版本或原因)``。"""
        try:
            executable = self.executable()
        except BuildError as exc:
            return (False, str(exc))
        try:
            result = await self._runner.run(
                (executable, "--version"), timeout=self._settings.probe_timeout
            )
        except CommandError as exc:
            return (False, str(exc))
        if not result.ok:
            return (False, result.message)
        # flet --version 会输出两行（Flet / Flutter），取第一行当版本号
        text = (result.stdout or result.stderr).strip()
        return (True, text.splitlines()[0].strip() if text else "")

    # ------------------------------------------------------------------ 命令行
    def clean_argv(self, plan: BuildPlan) -> tuple[str, ...]:
        """在源目录里清掉上一次构建的 ``build`` 目录。"""
        return (plan.executable, "clean", plan.source)

    def build_argv(self, plan: BuildPlan) -> tuple[str, ...]:
        """``flet build``。``--artifact`` / ``--product`` 取台账里的项目名称。"""
        return (
            plan.executable,
            "build",
            plan.target,
            plan.source,
            "--artifact",
            plan.project_name,
            "--cleanup-app",
            "--cleanup-app-files",
            *plan.cleanup_globs,
            "--cleanup-package-files",
            *plan.cleanup_globs,
            "--cleanup-packages",
            "--company",
            plan.company,
            "--copyright",
            plan.copyright,
            "--output",
            plan.output,
            "--product",
            plan.project_name,
            "--python-version",
            plan.python_version,
            "--template",
            plan.template,
        )

    def describe(self, plan: BuildPlan) -> tuple[str, str, str]:
        """三条将要在源目录里执行的步骤（界面预览与执行同源）。

        第 0 步不是命令，却是"残留为什么能被清掉"的关键：``flet build`` 会把整个
        项目（含 ``.git``）复制进 ``build/``，那些只读 object 靠 ``flet clean`` 的
        裸 rmtree 删不掉（WinError 5），所以先由程序自己删一遍。
        """
        return (
            f"0) 删除 {plan.build_dir}（内置步骤，只读文件也删得掉）",
            "1) " + format_command(self.clean_argv(plan)),
            "2) " + format_command(self.build_argv(plan)),
        )

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

        plan = plan if plan.executable == executable else replace(plan, executable=executable)
        logger.info("开始打包「%s」：%s → %s", plan.project_name, plan.source, plan.output)

        # 1) 预清理：先把源目录里的 build 目录删掉。
        #    flet clean 用的是裸 shutil.rmtree，遇到只读文件就报 WinError 5 并直接退出 1
        #    —— 而 flet 会把整个项目复制进 build/ 里，项目自带的 .git/objects 全是只读的，
        #    所以"项目本身是 git 仓库"这一常见情况会让 flet clean 必然失败。
        #    remove_tree 会先去掉只读位再删，这里先跑一遍；随后的 flet clean
        #    面对的只是一个不存在的目录（输出 "Nothing to clean" 并返回 0）。
        _notify_phase(on_phase, "清理上一次构建的 build 目录")
        residue = await offload(remove_tree, plan.build_dir)
        if not residue.ok:
            blocker = residue.first_blocker
            reason = blocker.reason if blocker else "未知原因"
            where = blocker.path if blocker else str(plan.build_dir)
            logger.error("打包终止：build 目录删不干净（%s）\n%s", reason, where)
            return _failed(
                f"上一次构建的 build 目录删不掉（{reason}）：{where}。"
                "请先关掉占用它的程序（编辑器 / 资源管理器 / 终端）再重试",
                plan,
                started,
            )

        # 2) flet clean：清掉上一次构建留下的 build 目录
        _notify_phase(on_phase, "flet clean：清理上一次构建的残留")
        try:
            clean = await self._step(
                plan, self.clean_argv(plan), self._settings.clean_timeout, on_line
            )
        except BuildError as exc:
            return _failed(f"flet clean 执行失败：{exc}", plan, started)
        if not clean.ok:
            logger.error("打包终止：flet clean 失败\n%s", clean.message)
            return _failed(f"flet clean 失败：{_short(clean.message)}", plan, started)

        # 3) flet build
        _notify_phase(on_phase, "flet build：正在构建（首次会下载 Flutter 依赖，可能较久）")
        try:
            build = await self._step(
                plan, self.build_argv(plan), self._settings.build_timeout, on_line
            )
        except BuildError as exc:
            return _failed(f"flet build 执行失败：{exc}", plan, started)

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
            return await self._runner.run(
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


# --------------------------------------------------------------------------- 工具
def format_command(argv: tuple[str, ...]) -> str:
    """拼成可直接复制粘贴的命令行，含空格的参数补引号。"""
    return " ".join(f'"{arg}"' if " " in arg else arg for arg in argv)


def _notify_phase(sink: PhaseSink | None, text: str) -> None:
    logger.debug("打包阶段：%s", text)
    if sink is not None:
        sink(text)


def _failed(detail: str, plan: BuildPlan, started: float) -> BuildOutcome:
    logger.error("打包终止：%s", detail)
    return BuildOutcome(
        ok=False,
        detail=detail,
        output=plan.output,
        seconds=time.perf_counter() - started,
    )


def _locate_flet(settings: BuildSettings) -> str | None:
    """定位 flet CLI：显式配置 → 环境变量 → 当前解释器同目录 → PATH。

    开发态下 ``sys.executable`` 的 ``Scripts/flet.exe`` 命中率最高，也最可靠
    （不依赖 PATH 被改对）；打包后的程序里没有它，自然回退到 PATH。
    """
    for candidate_text in (settings.executable, os.environ.get(settings.executable_env)):
        if not candidate_text:
            continue
        candidate = Path(candidate_text).expanduser()
        if candidate.is_file():
            return str(candidate)
        logger.warning("flet 可执行文件不存在：%s", candidate_text)

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


__all__ = ["BuildError", "FletCli", "format_command"]
