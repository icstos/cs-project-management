"""视图模型基类：状态、一次性通知，以及与平台能力解耦的请求通道。

三条约定，后面所有视图模型都遵守：

1. **状态不可变**：``state`` 是冻结数据类，任何变化都整体替换。
   flet 的 :class:`~flet.Observable` 会因此通知所有订阅了本视图模型的组件重新
   渲染，"UI = f(状态)" 于是自动成立。
2. **通知是一次性的**：``notice`` 带单调递增序号，视图只播报"没见过的那条"，
   因此重复渲染不会把同一条提示弹第二遍。
3. **不碰 UI 组件**：凡是必须由 flet 控件完成的事情（读写剪贴板、弹系统目录选择、
   保存文件），视图模型只发出一个 :class:`PlatformRequest`，由视图执行并回报结果。
   这样视图模型里没有一行 flet 控件代码，也就能脱离界面单独测试。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

import flet as ft

from models.enums import Tone

logger = logging.getLogger(__name__)

__all__ = [
    "Notice",
    "PlatformAction",
    "PlatformRequest",
    "Shortcut",
    "ViewModel",
]


@dataclass(frozen=True, slots=True)
class Notice:
    """一次性的用户提示（浮层 toast）。``seq`` 让视图识别"这是新的一条"。"""

    seq: int
    message: str
    tone: Tone = Tone.SUCCESS


class PlatformAction(StrEnum):
    """需要由视图借助 flet 控件完成的动作。"""

    READ_CLIPBOARD_PATH = "read_clipboard_path"
    COPY_TEXT = "copy_text"
    PICK_DIRECTORY = "pick_directory"
    SAVE_FILE = "save_file"


@dataclass(frozen=True, slots=True)
class PlatformRequest:
    """一次平台能力请求。视图按 ``action`` 分派，完成后回调视图模型。"""

    seq: int
    action: PlatformAction
    text: str = ""
    data: bytes | None = None


@dataclass(frozen=True, slots=True)
class Shortcut:
    """归一化后的键盘手势：视图把 ``ft.KeyboardEvent`` 翻译成它再交给视图模型。"""

    key: str
    ctrl: bool = False


class ViewModel[T](ft.Observable):
    """持有不可变状态 ``T``，并在状态变化时自动通知视图重渲染。"""

    def __init__(self, state: T) -> None:
        self._notice_seq = 0
        self._request_seq = 0
        self.notice: Notice | None = None
        #: 最近一次平台请求；视图订阅它并在变化时执行
        self.request: PlatformRequest | None = None
        self.state = state

    # ------------------------------------------------------------------ 状态
    def update(self, **changes: object) -> None:
        """按字段替换状态。字段不存在时会抛，属于开发期错误，不该静默。"""
        self.state = replace(self.state, **changes)

    def rewrite(self, state: T) -> None:
        """整体替换状态；内容相同时不触发重渲染。"""
        if state != self.state:
            self.state = state

    # ------------------------------------------------------------------ 通知
    def notify(self, message: str, tone: Tone = Tone.SUCCESS) -> None:
        self._notice_seq += 1
        self.notice = Notice(self._notice_seq, message, tone)

    def fail(self, action: str, exc: BaseException) -> None:
        """统一的失败上报：留一条带堆栈的日志，并给用户一句人话。"""
        logger.warning("%s失败：%s", action, exc)
        self.notify(f"{action}失败：{exc}", Tone.DANGER)

    # ------------------------------------------------------------------ 平台请求
    def ask_platform(
        self,
        action: PlatformAction,
        *,
        text: str = "",
        data: bytes | None = None,
    ) -> PlatformRequest:
        self._request_seq += 1
        request = PlatformRequest(self._request_seq, action, text, data)
        self.request = request
        return request

    # ------------------------------------------------------------------ 平台回执
    # 默认什么都不做：每个视图模型只覆写自己用得到的那几个。
    def accept_clipboard(self, candidates: Sequence[str]) -> None:
        """剪贴板内容读取完成。``candidates`` 按优先级排列（文件对象在前、纯文本在后）。"""

    def clipboard_written(self, error: str | None = None) -> None:
        """写剪贴板完成；``error`` 非空表示失败。"""

    def accept_directory(self, path: str) -> None:
        """系统目录选择框返回；用户取消时 ``path`` 为空串。"""

    def export_finished(self, saved_path: str | None, error: str | None = None) -> None:
        """保存文件完成；用户取消时 ``saved_path`` 为空、``error`` 也为空。"""
