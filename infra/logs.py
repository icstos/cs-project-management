"""统一日志：把命令运行、操作轨迹与异常落到文件，便于追溯与定位报错。

装配一次之后，全应用（含 flet 框架自身）的日志都汇到同一组 handler：

* **文件**（``data/logs/app.log``）收 DEBUG 及以上，按 2MB 滚动保留 5 份 ——
  出问题时能回放现场，包括每条外部命令的完整输出；
* **控制台**收 INFO 及以上，开发时直接看得见（打包成窗口应用后 stderr 为空，
  自动跳过）。

行格式固定为 ``时间 | 级别 | 模块:行号 | 内容``，多行内容统一缩进续行，
既能 grep 也能肉眼扫读；:func:`block` 负责把外部命令输出整理成这种块。

时机很重要：``ft.run`` 只在根 logger **尚无** handler 时才 ``basicConfig``。
所以在 ``ft.run`` 之前装配，装配完成后 flet 自己的日志也会一并进文件。
"""

from __future__ import annotations

import asyncio
import logging
import logging.handlers
import platform
import sys
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from infra import locations
from models.settings import APP_NAME, APP_VERSION, LogSettings

_LOGGER = "infra.logs"

_FORMAT = "%(asctime)s.%(msecs)03d | %(levelname)-7s | %(name)s:%(lineno)d | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

#: 续行缩进。多行内容（堆栈、命令输出）都靠它和首行区分开。
INDENT = "    "

#: 单条日志最多附带多少行 / 多少字符的外部输出，防止一次把日志写爆。
BLOCK_LINES = 60
BLOCK_CHARS = 6000


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


class LogSetup:
    """一次性的日志装配。由组合根在 ``ft.run`` 之前构造并调用 :meth:`setup`。"""

    def __init__(self, settings: LogSettings, log_file: Path | None = None) -> None:
        self._settings = settings
        self._file = log_file or locations.log_dir() / settings.file_name
        self._configured = False
        self._stream_handler: logging.StreamHandler | None = None

    # ------------------------------------------------------------------ 装配
    def setup(self, level: int | str | None = None) -> Path:
        """装配根 logger，返回日志文件路径。

        重复调用只调整控制台级别，不会重复挂 handler；``level`` 缺省时读环境变量
        （默认为 INFO）。文件始终记 DEBUG，所以调高控制台级别只会让屏幕更安静，
        不会丢日志。
        """
        console_level = _resolve_level(level, self._settings)
        if self._configured:
            if self._stream_handler is not None:
                self._stream_handler.setLevel(console_level)
            return self._file

        root = logging.getLogger()
        # 清掉框架或默认配置留下的 handler，避免同一条日志写两遍
        for handler in list(root.handlers):
            root.removeHandler(handler)

        formatter = logging.Formatter(_FORMAT, _DATE_FORMAT)
        noise = NoiseFilter(_noise_limits(self._settings))
        handlers: list[logging.Handler] = []

        file_handler = self._file_handler(formatter, noise)
        if file_handler is not None:
            handlers.append(file_handler)

        self._stream_handler = self._stream_handler_for(console_level, formatter, noise)
        if self._stream_handler is not None:
            handlers.append(self._stream_handler)

        if not handlers:  # 极端情况：日志目录不可写且没有 stderr
            handlers.append(logging.NullHandler())

        for handler in handlers:
            root.addHandler(handler)
        # 根 logger 放到 DEBUG，由各 handler 自己设门槛，文件才收得到 DEBUG
        root.setLevel(logging.DEBUG)

        # warnings.warn 也收进日志，免得只在控制台一闪而过
        logging.captureWarnings(True)

        self._configured = True
        if file_handler is None:
            logging.getLogger(_LOGGER).warning("日志文件不可写，本次仅输出到控制台：%s", self._file)
        return self._file

    def install_hooks(self) -> None:
        """接管"没人接"的异常：主线程、子线程与 asyncio 任务。

        视图层有渲染兜底，但事件回调、后台任务里的异常原本会静默丢掉 ——
        这里补上，保证崩溃一定留堆栈。需要在事件循环内调用才能接管 asyncio 部分。
        """
        sys.excepthook = _log_uncaught
        threading.excepthook = _log_thread_uncaught
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.set_exception_handler(_log_asyncio)

    def log_startup(self, **extra: object) -> None:
        """记录启动环境。日志的第一条，排查问题时先看它。"""
        fields: dict[str, object] = {
            "python": f"{platform.python_version()}（{sys.executable}）",
            "平台": platform.platform(),
            "工作目录": Path.cwd(),
            "数据目录": locations.data_dir(),
            "数据库": locations.database_file(),
            "日志文件": self._file,
            "控制台级别": (
                logging.getLevelName(self._stream_handler.level)
                if self._stream_handler is not None
                else "关闭"
            ),
        }
        fields.update(extra)
        body = "\n".join(f"{key}: {value}" for key, value in fields.items())
        logging.getLogger(_LOGGER).info(
            "启动 %s v%s\n%s",
            APP_NAME,
            APP_VERSION,
            indent(body),
        )

    # ------------------------------------------------------------------ 内部
    def _file_handler(self, formatter: logging.Formatter, noise: logging.Filter):
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.handlers.RotatingFileHandler(
                self._file,
                maxBytes=self._settings.max_bytes,
                backupCount=self._settings.backups,
                encoding="utf-8",
            )
        except OSError:
            return None
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(formatter)
        handler.addFilter(noise)
        return handler

    def _stream_handler_for(
        self,
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
def _noise_limits(settings: LogSettings) -> dict[str, int]:
    limits: dict[str, int] = {}
    for name, level in settings.noise:
        resolved = logging.getLevelName(level)
        limits[name] = resolved if isinstance(resolved, int) else logging.INFO
    return limits


def _resolve_level(level: int | str | None, settings: LogSettings) -> int:
    if level is None:
        level = settings.default_level
    if isinstance(level, int):
        return level
    resolved = logging.getLevelName(str(level).strip().upper())
    return resolved if isinstance(resolved, int) else logging.INFO


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
    "LogSetup",
    "NoiseFilter",
    "block",
    "indent",
]
