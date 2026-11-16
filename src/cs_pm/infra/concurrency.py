"""并发辅助：把阻塞调用挪出事件循环，并给批量任务加上并发上限。

Flet 的事件回调运行在事件循环里，任何同步阻塞调用（SQLite 查询、文件 IO）都会
卡住整个界面，因此统一通过 :func:`offload` 丢到线程池执行。
"""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import Awaitable, Callable, Iterable

logger = logging.getLogger(__name__)

__all__ = ["gather_limited", "offload"]


async def offload[T](fn: Callable[..., T], /, *args: object, **kwargs: object) -> T:
    """在线程池中执行同步函数，返回其结果。"""
    if kwargs:
        return await asyncio.to_thread(functools.partial(fn, **kwargs), *args)
    return await asyncio.to_thread(fn, *args)


async def gather_limited[T, R](
    items: Iterable[T],
    worker: Callable[[T], Awaitable[R]],
    *,
    limit: int,
) -> list[R]:
    """并发执行 ``worker``，同时运行数量不超过 ``limit``。

    用于批量探测 Git 仓库：既要并行提速，又不能一次拉起几十个子进程。
    """
    gate = asyncio.Semaphore(max(1, limit))

    async def guarded(item: T) -> R:
        async with gate:
            return await worker(item)

    return list(await asyncio.gather(*(guarded(item) for item in items)))
