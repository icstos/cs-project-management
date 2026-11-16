"""组件级错误边界。

flet 的会话调度器把「渲染组件」放在一个后台任务里，且只捕获
``asyncio.CancelledError``。一旦某个组件在渲染中抛异常，异常会穿出调度循环、
悄悄结束那个任务 —— 此后**所有** ``update()`` 都不再被处理，界面永久冻结，
而且没有任何提示。

这是一个代价极高的失败模式，所以这里给每个顶层视图套一层兜底：
渲染失败时记录日志并返回一张错误卡片，其余界面继续可用。

错误卡片本身也遵守同一套设计令牌：出错时界面可能只剩这一块内容，
它更应该看起来是"这个产品的一部分"，而不是一坨 traceback。
"""

from __future__ import annotations

import functools
import logging
import traceback
from collections.abc import Callable
from typing import Any

import ui
from ui import (
    SPACE,
    Alignment,
    Border,
    Column,
    Container,
    CrossAxisAlignment,
    FontWeight,
    Icon,
    Icons,
    Row,
    Text,
)

from cs_pm.models.enums import Tone
from cs_pm.view import design as T
from cs_pm.view import widgets

logger = logging.getLogger(__name__)

__all__ = ["error_card", "guarded"]


def guarded[F: Callable[..., Any]](fn: F) -> F:
    """把组件函数包成 ``ui.component``，并在渲染出错时降级为错误卡片。

    用法与 ``@ui.component`` 完全一致，只是多了一层保护。
    """

    @functools.wraps(fn)
    def render(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # 兜底：任何渲染异常都不能逃出组件
            logger.exception("组件 %s 渲染失败", fn.__name__)
            return error_card(fn.__name__, exc)

    return ui.component(render)  # type: ignore[return-value]


def error_card(name: str, exc: BaseException) -> ui.Control:
    """出错时的降级界面：说清哪个视图崩了、为什么崩，并给出堆栈。"""
    detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
    stack = "".join(traceback.format_tb(exc.__traceback__)[-4:]).rstrip()
    style = T.tone_style(Tone.DANGER)

    return Container(
        expand=True,
        alignment=Alignment.CENTER,
        padding=SPACE["8"],
        content=Column(
            horizontal_alignment=CrossAxisAlignment.CENTER,
            spacing=SPACE["4"],
            tight=True,
            width=T.DIALOG_WIDTH * 2,
            controls=[
                Container(
                    width=48,
                    height=48,
                    border_radius=T.RADIUS_LG,
                    bgcolor=style.container,
                    alignment=Alignment.CENTER,
                    content=Icon(Icons.ERROR_OUTLINE, size=T.ICON_LG + 6, color=style.accent),
                ),
                T.text(
                    "这个视图渲染时出错了",
                    level=T.TextLevel.TITLE,
                    weight=FontWeight.W_600,
                ),
                widgets.muted(f"{name} · {detail}", size=12, max_lines=3),
                # 深色代码块：与打包页的控制台同一套观感
                Row(
                    spacing=0,
                    controls=[
                        Container(
                            expand=True,
                            padding=SPACE["4"],
                            border_radius=T.RADIUS_MD,
                            border=Border.all(1, T.BORDER_COLOR),
                            bgcolor=T.CONSOLE_BG,
                            content=Text(
                                stack,
                                size=11,
                                color=T.CONSOLE_TEXT,
                                # 堆栈缩进靠空格对齐，中文字体字宽不等，补等宽字体兜底
                                font_family_fallback=T.MONO_FONTS,
                                selectable=True,
                                style=ui.TextStyle(height=1.55),
                            ),
                        )
                    ],
                ),
                widgets.muted("其他页面仍可正常使用；请把上面的信息反馈给开发者。", size=11),
            ],
        ),
    )
