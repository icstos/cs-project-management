"""外部命令执行 + 日志记录。

git、flet build 这类外部命令统一从这里走，一处解决三件事：

* **可回放**：命令、工作目录、退出码、耗时与完整输出都进日志（输出走 DEBUG，
  失败走 WARNING），出问题照着日志重敲一遍就能复现；
* **实时**：输出按行回流给 ``on_line`` 回调，打包这类几分钟的命令能把进度透给界面；
* **有语义**：找不到可执行文件、超时这类"根本没有退出码"的失败转成专门的异常，
  业务层不必去翻 ``OSError`` 猜原因。

注意退出码非零**不算异常** —— 命令跑完了，是否当作失败由调用方判断；
只有"没跑起来"才抛 ``CommandError``。
"""

from __future__ import annotations

import asyncio
import codecs
import logging
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from core import logs

logger = logging.getLogger(__name__)

#: 单行上限。命令输出偶有超长行，默认 64KB 会让 readline 直接报错。
_STREAM_LIMIT = 1 << 20

#: 除制表符外的 C0 控制字符：git log 用 \x1e / \x1f 做分隔符，直接写进日志
#: 会变成看不见的乱码，读日志时只会觉得"这行怎么黏在一起"。
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_CONTROL_PLACEHOLDER = "·"

StreamName = str
"""``"out"`` 或 ``"err"``。"""
LineSink = Callable[[StreamName, str], None]
"""``on_line(流名, 行内容)``，用于把命令输出实时透出。"""


class CommandError(RuntimeError):
    """命令没能跑起来（找不到可执行文件 / 启动失败 / 超时）。"""


class CommandNotFound(CommandError):
    def __init__(self, executable: str) -> None:
        super().__init__(f"未找到可执行文件：{executable}")
        self.executable = executable


class CommandTimeout(CommandError):
    def __init__(self, command: str, timeout: float) -> None:
        super().__init__(f"{command} 执行超时（>{timeout:.0f}s，已终止）")
        self.command = command
        self.timeout = timeout


@dataclass(frozen=True, slots=True)
class CommandResult:
    """一次命令执行的结果。``stdout`` / ``stderr`` 已解码并去掉了行尾换行。"""

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
        return format_command(self.argv)

    @property
    def message(self) -> str:
        """给人看的失败原因：优先 stderr，其次 stdout，都没有才用退出码兜底。"""
        return (
            self.stderr.strip()
            or self.stdout.strip()
            or f"{self.command} 执行失败（退出码 {self.returncode}，无输出）"
        )


def format_command(argv: Sequence[str]) -> str:
    """拼成可直接复制粘贴的命令行，含空格的参数补引号。"""
    return " ".join(f'"{arg}"' if " " in arg else arg for arg in argv)


def _sanitize(text: str) -> str:
    """只用于**展示**：不可见控制字符换成占位符。

    注意不能改写 ``CommandResult`` 里的原始输出 —— 那里可能靠 \\x1e / \\x1f
    这种分隔符来解析（见 ``git log --pretty``）。
    """
    return _CONTROL.sub(_CONTROL_PLACEHOLDER, text)


async def run_command(
    argv: Sequence[str],
    *,
    cwd: str | Path | None = None,
    timeout: float | None = None,
    env: Mapping[str, str] | None = None,
    on_line: LineSink | None = None,
) -> CommandResult:
    """执行外部命令，全过程写日志。

    ``timeout`` 到期会杀掉进程并抛 ``CommandTimeout``；
    可执行文件不存在抛 ``CommandNotFound``；其余启动失败抛 ``CommandError``。
    """
    args = [str(item) for item in argv]
    label = _label(args, cwd)
    logger.debug("执行 %s", label)

    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            cwd=None if cwd is None else str(cwd),
            env=None if env is None else dict(env),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=_STREAM_LIMIT,
        )
    except FileNotFoundError as exc:
        logger.error("未找到可执行文件：%s", args[0])
        raise CommandNotFound(args[0]) from exc
    except OSError as exc:
        logger.error("无法启动 %s：%s", args[0], exc)
        raise CommandError(f"无法启动 {args[0]}：{exc}") from exc

    started = time.perf_counter()
    out: list[str] = []
    err: list[str] = []
    pumps = [
        asyncio.ensure_future(_pump(process.stdout, out, "out", on_line)),  # type: ignore[arg-type]
        asyncio.ensure_future(_pump(process.stderr, err, "err", on_line)),  # type: ignore[arg-type]
    ]

    timed_out = False
    try:
        # asyncio.timeout(None) 等价于不设限，省掉一条分支
        async with asyncio.timeout(timeout):
            await asyncio.gather(*pumps)
            await process.wait()
    except TimeoutError:
        timed_out = True
        await _terminate(process, pumps)
    except BaseException:
        # 被取消等情况：同步收尾，避免再被一次取消打断
        _abort(process, pumps)
        raise

    result = CommandResult(
        argv=tuple(args),
        cwd=None if cwd is None else str(cwd),
        returncode=process.returncode if process.returncode is not None else -1,
        stdout="\n".join(out),
        stderr="\n".join(err),
        seconds=time.perf_counter() - started,
        timed_out=timed_out,
    )
    _log_result(label, result)

    if timed_out:
        raise CommandTimeout(result.command, timeout or 0.0)
    return result


# --------------------------------------------------------------------------- 内部
def _label(args: Sequence[str], cwd: str | Path | None) -> str:
    """日志里的命令标识：``[git] push origin main @ D:\\repo``。"""
    tag = Path(args[0]).stem or args[0]
    text = f"[{tag}] {' '.join(args[1:])}".rstrip()
    return f"{text} @ {cwd}" if cwd is not None else text


async def _pump(
    stream: asyncio.StreamReader,
    sink: list[str],
    name: StreamName,
    on_line: LineSink | None,
) -> None:
    """把一条管道按行读出来：进日志、进汇总、有回调就实时透出。

    用增量解码器而不是 ``decode()``，多字节字符被切在两个 chunk 之间时不会变成乱码。
    """
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    while chunk := await stream.readline():
        line = decoder.decode(chunk).rstrip("\r\n")
        if line:
            _emit(sink, name, line, on_line)
    tail = decoder.decode(b"", final=True).strip()
    if tail:
        _emit(sink, name, tail, on_line)


def _emit(sink: list[str], name: StreamName, line: str, on_line: LineSink | None) -> None:
    sink.append(line)
    logger.debug("  %s> %s", name, _sanitize(line))
    if on_line is not None:
        on_line(name, line)


async def _terminate(process: asyncio.subprocess.Process, pumps: list[asyncio.Task[None]]) -> None:
    """收尾：杀掉进程、等它退出、把读管道的任务停掉。"""
    _abort(process, pumps)
    await asyncio.gather(*pumps, return_exceptions=True)


def _abort(process: asyncio.subprocess.Process, pumps: list[asyncio.Task[None]]) -> None:
    """不做任何等待的收尾，用在会被二次取消的路径上。"""
    if process.returncode is None:
        process.kill()
    for pump in pumps:
        pump.cancel()


def _log_result(label: str, result: CommandResult) -> None:
    if result.timed_out:
        logger.error("超时 %s（已终止）\n%s", label, _output_block(result))
    elif result.ok:
        # 成功的输出已经在上面按行记过，这里不再重复整块，日志体积减半
        logger.debug("完成 %s → 退出码 0，%.2fs", label, result.seconds)
    else:
        # 失败一律 WARNING：控制台级别调到 INFO 也照样看得见，
        # 且把输出原文附在同一条记录里，不必再去翻上面的 DEBUG 行
        logger.warning(
            "失败 %s → 退出码 %d，%.2fs\n%s",
            label,
            result.returncode,
            result.seconds,
            _output_block(result),
        )


def _output_block(result: CommandResult) -> str:
    """命令输出缩进成块，附在日志记录后面。两个流分别标注，便于区分。"""
    parts: list[str] = []
    for name, text in (("stderr", result.stderr), ("stdout", result.stdout)):
        if text.strip():
            parts.append(f"{logs.INDENT}{name}:")
            parts.append(logs.INDENT + logs.block(_sanitize(text)))
    return "\n".join(parts) if parts else f"{logs.INDENT}（无输出）"


__all__ = [
    "CommandError",
    "CommandNotFound",
    "CommandResult",
    "CommandTimeout",
    "LineSink",
    "format_command",
    "run_command",
]
