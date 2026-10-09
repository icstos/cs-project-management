"""面向展示的纯格式化。

放在视图模型层而不是视图层：视图模型负责把领域值整理成"可以直接写进界面"的
字符串（相对时间、字节数、带千分位的计数），视图只需照抄。视图依赖视图模型，
方向因此始终是单向的。
"""

from __future__ import annotations

from datetime import datetime

__all__ = [
    "format_count",
    "format_datetime",
    "format_day",
    "format_relative",
    "human_bytes",
]

_DATETIME = "%Y-%m-%d %H:%M"
_DAY = "%m-%d"
_MINUTE = 60
_HOUR = 3600
_DAY_SECONDS = 86_400
_WEEK_SECONDS = 604_800


def format_datetime(value: datetime) -> str:
    return value.strftime(_DATETIME)


def format_day(value: datetime) -> str:
    return value.strftime(_DAY)


def format_relative(value: datetime, *, now: datetime | None = None) -> str:
    """人类友好的相对时间，超过一周则回退到具体日期。"""
    reference = now or datetime.now()
    seconds = (reference - value).total_seconds()
    match seconds:
        case s if s < 0:
            return format_datetime(value)
        case s if s < _MINUTE:
            return "刚刚"
        case s if s < _HOUR:
            return f"{int(s // _MINUTE)} 分钟前"
        case s if s < _DAY_SECONDS:
            return f"{int(s // _HOUR)} 小时前"
        case s if s < _WEEK_SECONDS:
            return f"{int(s // _DAY_SECONDS)} 天前"
        case _:
            return format_datetime(value)


def format_count(value: int) -> str:
    return f"{value:,}"


def human_bytes(value: int) -> str:
    """把字节数写成 113.2 MB 这种读法。"""
    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"
