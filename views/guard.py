"""组件级错误边界。

Flet 1.0 的会话调度器把「渲染组件」放在一个后台任务里，且只捕获
``asyncio.CancelledError``。一旦某个组件在渲染中抛异常，异常会穿出调度循环、
悄悄结束掉那个任务 —— 此后**所有** ``update()`` 都不再被处理，界面永久冻结，
而且没有任何提示。

这是一个代价极高的失败模式，所以这里给每个顶层视图套一层兜底：
渲染失败时记录日志并返回一张错误卡片，其余界面继续可用。
"""

from __future__ import annotations

import functools
import logging
import traceback
from collections.abc import Callable
from typing import Any

import flet as ft

logger = logging.getLogger(__name__)


def guarded[F: Callable[..., Any]](fn: F) -> F:
    """把组件函数包成 ``ft.component``，并在渲染出错时降级为错误卡片。

    用法与 ``@ft.component`` 完全一致，只是多了一层保护。
    """

    @functools.wraps(fn)
    def render(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # 兜底：任何渲染异常都不能逃出组件
            logger.exception("组件 %s 渲染失败", fn.__name__)
            return error_card(fn.__name__, exc)

    return ft.component(render)  # type: ignore[return-value]


def error_card(name: str, exc: BaseException) -> ft.Control:
    """出错时的降级界面：说清哪个视图崩了、为什么崩，并给出堆栈。"""
    from core import theme as T
    from views import ui

    detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
    stack = "".join(traceback.format_tb(exc.__traceback__)[-4:]).rstrip()

    return ft.Container(
        expand=True,
        alignment=ft.Alignment.CENTER,
        padding=T.SPACE_XXL,
        content=ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=T.SPACE_MD,
            tight=True,
            width=T.DIALOG_WIDTH * 2,
            controls=[
                ft.Icon(
                    ft.Icons.REPORT_GMAILERRORRED,
                    size=40,
                    color=T.tone_style(T.Tone.DANGER).accent,
                ),
                ft.Text("这个视图渲染时出错了", size=17, weight=ft.FontWeight.W_600),
                ui.muted(f"{name} · {detail}", size=12, max_lines=3),
                ui.flat_panel(
                    ft.Text(
                        stack,
                        size=11,
                        font_family=T.FONT_FAMILY,
                        # 堆栈缩进靠空格对齐，中文字体字宽不等，补等宽字体兜底。
                        font_family_fallback=["Consolas", "monospace"],
                        selectable=True,
                        color=T.MUTED_TEXT,
                    ),
                    padding=T.SPACE_MD,
                ),
                ui.muted("其他页面仍可正常使用；请把上面的信息反馈给开发者。", size=11),
            ],
        ),
    )


__all__ = ["error_card", "guarded"]
