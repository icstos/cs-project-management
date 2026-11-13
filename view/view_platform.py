"""视图层的平台适配：把 cs-ui / Flet 提供的系统能力接到视图模型的请求上。

视图模型只发出 :class:`~viewmodel.base.PlatformRequest`，具体怎么读剪贴板、
怎么弹系统对话框由这里决定。反向也成立：键盘事件在这里被归一化成
:class:`~viewmodel.base.Shortcut` 再交给视图模型，视图模型因此完全不认识
任何控件类型。

本模块还提供两个小工具钩子，让每个页面用两行代码接好这套通道。
"""

from __future__ import annotations

import logging

import ui
from ui import Page

from models.enums import Tone
from view import widgets
from viewmodel.app_vm import AppViewModel
from viewmodel.base import PlatformAction, PlatformRequest, Shortcut, ViewModel

logger = logging.getLogger(__name__)

__all__ = ["FletPlatform", "use_notices", "use_platform_requests", "use_shortcuts"]


class FletPlatform:
    """一次会话一份：剪贴板与对话框服务都是页面级的，不能重复注册。

    ``dialog`` 是 cs-ui 的命令式对话框（:class:`ui.FileDialog`）：``await`` 一次
    拿到一个 ``Path``，用户取消返回 ``None``，失败抛 ``FileDialogError`` ——
    视图模型因此不必认识任何控件，还能把「用户反悔」与「对话框没弹出来」分开。
    这里**不碰 flet**：``ui`` 已经把系统对话框包好了。
    """

    def __init__(self, page: Page, clipboard: ui.Clipboard, dialog: ui.FileDialog) -> None:
        self.page = page
        self._clipboard = clipboard
        self._dialog = dialog

    async def perform(self, request: PlatformRequest, vm: ViewModel) -> None:
        """执行一条平台请求，并把结果回报给发起它的视图模型。"""
        match request.action:
            case PlatformAction.READ_CLIPBOARD_PATH:
                await self._read_clipboard(vm)
            case PlatformAction.COPY_TEXT:
                await self._copy_text(request.text, vm)
            case PlatformAction.PICK_DIRECTORY:
                await self._pick_directory(request.text, vm)
            case PlatformAction.SAVE_FILE:
                await self._save_file(request, vm)

    # ------------------------------------------------------------------ 剪贴板
    async def _read_clipboard(self, vm: ViewModel) -> None:
        """读取剪贴板的候选路径。

        在资源管理器里复制文件夹时，剪贴板里放的是「文件对象」而不是文本，
        输入框里直接 Ctrl+V 未必粘得出来，所以先按文件列表取、再退回纯文本。
        """
        candidates: list[str] = []
        try:
            candidates.extend(await self._clipboard.get_files() or [])
        except Exception:  # 平台不支持，或剪贴板里放的本来就不是文件
            logger.debug("剪贴板里没有文件对象")
        try:
            text = await self._clipboard.get()
        except Exception as exc:
            logger.warning("读取剪贴板失败：%s", exc)
            vm.notify(f"读取剪贴板失败：{exc}", Tone.DANGER)
            return
        if text:
            candidates.append(text)
        vm.accept_clipboard(candidates)

    async def _copy_text(self, text: str, vm: ViewModel) -> None:
        try:
            await self._clipboard.set(text)
        except Exception as exc:
            vm.clipboard_written(str(exc))
            return
        vm.clipboard_written(None)

    # ------------------------------------------------------------------ 对话框
    async def _pick_directory(self, title: str, vm: ViewModel) -> None:
        try:
            folder = await self._dialog.pick_directory(title=title)
        except ui.FileDialogError as exc:
            logger.warning("打开目录选择框失败：%s", exc)
            vm.notify(f"打开目录选择框失败：{exc}", Tone.DANGER)
            return
        # 取消与失败是两件事：取消只是空串，界面保持原值不动
        vm.accept_directory(str(folder) if folder else "")

    async def _save_file(self, request: PlatformRequest, vm: ViewModel) -> None:
        try:
            saved = await self._dialog.save_file(
                title="导出提交明细",
                file_name=request.text,
                extensions=["csv"],
                data=request.data,
            )
        except ui.FileDialogError as exc:
            logger.warning("保存文件失败：%s", exc)
            vm.export_finished(None, str(exc))
            return
        vm.export_finished(str(saved) if saved else None)


# --------------------------------------------------------------------------- 钩子
def use_platform_requests(platform: FletPlatform, vm: ViewModel) -> None:
    """把视图模型发出的平台请求交给 :class:`FletPlatform` 执行。

    ``vm.request`` 只作依赖比较（"换了一条新的"就重跑 effect）；要执行的那条经
    :meth:`~viewmodel.base.ViewModel.claim_request` 一次性取走。这一层不能省：
    flet 的 effect **在组件每次挂载后都会无条件跑一遍**，而切页签回来就是重新挂载，
    只判断 ``request is not None`` 会把上一次的请求再执行一遍 —— 现象就是选过一次
    目录、切走再切回来，系统目录框自己又弹出来。
    """
    request = vm.request

    def setup() -> None:
        claimed = vm.claim_request()
        if claimed is not None:
            platform.page.run_task(platform.perform, claimed, vm)

    ui.use_effect(setup, [request])


def use_notices(page: Page, vm: ViewModel) -> None:
    """播报视图模型的一次性提示。

    播没播过由 :meth:`~viewmodel.base.ViewModel.claim_notice` 判定（视图模型的
    生命期跟业务状态走，不随组件卸载归零），因此重新挂载不会重播旧提示。
    """
    notice = vm.notice

    def setup() -> None:
        claimed = vm.claim_notice()
        if claimed is not None:
            widgets.toast(page, claimed.message, tone=claimed.tone)

    ui.use_effect(setup, [notice])


def use_shortcuts(page: Page, vm: AppViewModel) -> None:
    """把键盘事件归一化后交给视图模型，卸载时解除绑定。"""

    def setup():
        page.on_keyboard_event = lambda event: vm.on_shortcut(
            Shortcut(key=event.key, ctrl=bool(event.ctrl))
        )
        return lambda: setattr(page, "on_keyboard_event", None)

    ui.use_effect(setup, [])
