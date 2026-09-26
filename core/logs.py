"""统一日志：把命令运行、操作轨迹与异常落到文件，便于追溯与定位报错。

``setup_logging()`` 装配一次之后，全应用（含 flet 框架自身）的日志都汇到同一组
handler：

* **文件**（``data/logs/app.log``）收 DEBUG 及以上，按 2MB 滚动保留 5 份 ——
  出问题时能回放现场，包括每条外部命令的完整输出；
* **控制台**收 INFO 及以上，开发时直接看得见（打包成窗口应用后 stderr 为空，
  自动跳过）。

行格式固定为 ``时间 | 级别 | 模块:行号 | 内容``，多行内容统一缩进续行，
既能 grep 也能肉眼扫读；``core.proc.block`` 负责把外部命令输出整理成这种块。

时机很重要：``flet.app.run`` 只在 ``FLET_LOG_LEVEL`` 存在、且根 logger **尚无**
handler 时才 ``basicConfig``。所以在 ``ft.run`` 之前装配，装配完成后 flet 自己的
日志也会一并进文件。
"""

from __future__ import annotations

import asyncio
import logging
import logging.handlers
import os
import platform
import sys
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from core.config import (
    APP_NAME,
    APP_VERSION,
    DATA_DIR,
    DB_PATH,
    LOG_BACKUPS,
    LOG_FILE,
    LOG_LEVEL_ENV,
    LOG_MAX_BYTES,
)

_LOGGER = "core.logs"

_FORMAT = "%(asctime)s.%(msecs)03d | %(levelname)-7s | %(name)s:%(lineno)d | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

#: 续行缩进。多行内容（堆栈、命令输出）都靠它和首行区分开。
INDENT = "    "

#: 单条日志最多附带多少行 / 多少字符的外部输出，防止一次把日志写爆。
BLOCK_LINES = 60
BLOCK_CHARS = 6000

#: 框架自身的日志级别（DEBUG 全是协议细节，一次启动能刷出几千行）。
#: 按名字**前缀**匹配，``"flet"`` 会一并管住运行期才创建的
#: ``flet_transport`` / ``flet_controls`` / ``flet_desktop``……
_NOISY = {
    "flet": logging.INFO,
    "asyncio": logging.INFO,
    "sqlalchemy": logging.WARNING,
    "PIL": logging.WARNING,
}

_configured = False
_stream_handler: logging.StreamHandler | None = None


class NoiseFilter(logging.Filter):
    """按 logger 名前缀限制最低级别。

    挂在 **handler** 上而不是给 logger 设级别：框架（flet）会在运行期陆续创建自己的
    logger，一次性 ``setLevel`` 管不住后来者，而 handler 过滤器对每条记录都会重新判定。
    """

    def __init__(self, limits: Mapping[str, int]) -> None:
        super().__init__()
        self._limits = dict(limits)

    def filter(self, record: logging.LogRecord) -> bool:
        limit = self._limit_for(record.name)
        return limit is None or record.levelno >= limit

    def _limit_for(self, name: str) -> int | None:
        """取最长命中的前缀，保证 ``flet_controls`` 也归 ``flet`` 管。"""
        found: int | None = None
        found_width = -1
        for prefix, limit in self._limits.items():
            if name.startswith(prefix) and len(prefix) > found_width:
                found, found_width = limit, len(prefix)
        return found


# --------------------------------------------------------------------------- 装配
def setup_logging(level: int | str | None = None) -> Path:
    """装配根 logger，返回日志文件路径。

    重复调用只调整控制台级别，不会重复挂 handler；``level`` 缺省时读环境变量
    ``CSPM_LOG_LEVEL``（默认 INFO）。文件始终记 DEBUG，所以调高控制台级别
    只会让屏幕更安静，不会丢日志。
    """
    global _configured, _stream_handler

    console_level = _resolve_level(level)
    if _configured:
        if _stream_handler is not None:
            _stream_handler.setLevel(console_level)
        return LOG_FILE

    root = logging.getLogger()
    # 清掉框架或默认配置留下的 handler，避免同一条日志写两遍
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(_FORMAT, _DATE_FORMAT)
    noise = NoiseFilter(_NOISY)
    handlers: list[logging.Handler] = []

    file_handler = _file_handler(formatter, noise)
    if file_handler is not None:
        handlers.append(file_handler)

    _stream_handler = _stream_handler_for(console_level, formatter, noise)
    if _stream_handler is not None:
        handlers.append(_stream_handler)

    if not handlers:  # 极端情况：日志目录不可写且没有 stderr
        handlers.append(logging.NullHandler())

    for handler in handlers:
        root.addHandler(handler)
    # 根 logger 放到 DEBUG，由各 handler 自己设门槛，文件才收得到 DEBUG
    root.setLevel(logging.DEBUG)

    # warnings.warn 也收进日志，免得只在控制台一闪而过
    logging.captureWarnings(True)

    _configured = True
    if file_handler is None:
        logging.getLogger(_LOGGER).warning("日志文件不可写，本次仅输出到控制台：%s", LOG_FILE)
    return LOG_FILE


def install_hooks() -> None:
    """接管"没人接"的异常：主线程、子线程与 asyncio 任务。

    界面层有 ``views.guard`` 兜渲染异常，但事件回调、后台任务里的异常原本会
    静默丢掉 —— 这里补上，保证崩溃一定留堆栈。需要在事件循环内调用才能接管
    asyncio 部分。
    """
    sys.excepthook = _log_uncaught
    threading.excepthook = _log_thread_uncaught
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.set_exception_handler(_log_asyncio)


def log_startup(**extra: object) -> None:
    """记录启动环境。日志的第一条，排查问题时先看它。"""
    fields: dict[str, object] = {
        "python": f"{platform.python_version()}（{sys.executable}）",
        "平台": platform.platform(),
        "工作目录": Path.cwd(),
        "数据目录": DATA_DIR,
        "数据库": DB_PATH,
        "日志文件": LOG_FILE,
        "控制台级别": logging.getLevelName(_stream_handler.level)
        if _stream_handler is not None
        else "关闭",
    }
    fields.update(extra)
    body = "\n".join(f"{key}: {value}" for key, value in fields.items())
    logging.getLogger(_LOGGER).info(
        "启动 %s v%s\n%s",
        APP_NAME,
        APP_VERSION,
        indent(body),
    )


# --------------------------------------------------------------------------- 输出整理
def indent(text: str) -> str:
    """给多行内容加续行缩进，使其在日志里归属于上一条记录。"""
    return INDENT + text.replace("\n", "\n" + INDENT)


def block(
    text: str,
    *,
    lines: int = BLOCK_LINES,
    chars: int = BLOCK_CHARS,
) -> str:
    """把外部命令输出整理成可读的日志块：去掉空行、限行数、限长度、缩进续行。"""
    kept = [line.rstrip() for line in text.splitlines() if line.strip()]
    if not kept:
        return f"{INDENT}（无输出）"

    body = indent("\n".join(kept[:lines]))
    if len(kept) > lines:
        body += f"\n{INDENT}…（省略 {len(kept) - lines} 行）"
    if len(body) > chars:
        body = body[:chars] + f"…（截断，原文共 {len(text)} 字符）"
    return body


# --------------------------------------------------------------------------- 内部
def _resolve_level(level: int | str | None) -> int:
    if level is None:
        level = os.environ.get(LOG_LEVEL_ENV, "INFO")
    if isinstance(level, int):
        return level
    resolved = logging.getLevelName(str(level).strip().upper())
    return resolved if isinstance(resolved, int) else logging.INFO


def _file_handler(formatter: logging.Formatter, noise: logging.Filter) -> logging.Handler | None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            LOG_FILE,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUPS,
            encoding="utf-8",
        )
    except OSError:
        return None
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(formatter)
    handler.addFilter(noise)
    return handler


def _stream_handler_for(
    level: int,
    formatter: logging.Formatter,
    noise: logging.Filter,
) -> logging.StreamHandler | None:
    # 打包成窗口应用（pythonw / flet 外壳）时 stderr、stdout 都可能是 None
    stream = sys.stderr or sys.stdout
    if stream is None:
        return None
    handler = logging.StreamHandler(stream)
    handler.setLevel(level)
    handler.setFormatter(formatter)
    handler.addFilter(noise)
    return handler


def _log_uncaught(exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
    logging.getLogger("uncaught").critical("主线程未捕获异常", exc_info=(exc_type, exc, tb))


def _log_thread_uncaught(args: threading.ExceptHookArgs) -> None:
    name = args.thread.name if args.thread is not None else "?"
    logging.getLogger("uncaught").critical(
        "子线程 %s 未捕获异常",
        name,
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )


def _log_asyncio(loop: asyncio.AbstractEventLoop, context: Mapping[str, Any]) -> None:
    failure = context.get("exception")
    source = context.get("future") or context.get("task") or context.get("handle") or "?"
    message = context.get("message") or "asyncio 任务出现未处理异常"
    if isinstance(failure, BaseException):
        logging.getLogger("asyncio").error("%s（%s）", message, source, exc_info=failure)
    else:
        logging.getLogger("asyncio").error("%s（%s）", message, source)


__all__ = [
    "BLOCK_CHARS",
    "BLOCK_LINES",
    "INDENT",
    "NoiseFilter",
    "block",
    "indent",
    "install_hooks",
    "log_startup",
    "setup_logging",
]
