"""视图层的平台适配：把 flet 提供的系统能力接到视图模型的请求上。

视图模型只发出 :class:`~viewmodel.base.PlatformRequest`，具体怎么读剪贴板、
怎么弹系统对话框由这里决定。反向也成立：键盘事件在这里被归一化成
:class:`~viewmodel.base.Shortcut` 再交给视图模型，视图模型因此完全不认识
flet 控件类型。

本模块还提供两个小工具钩子，让每个页面用两行代码接好这套通道。
"""

from __future__ import annotations

import logging

import flet as ft

from models.enums import Tone
from view import widgets
from viewmodel.app_vm import AppViewModel
from viewmodel.base import PlatformAction, PlatformRequest, Shortcut, ViewModel

logger = logging.getLogger(__name__)

__all__ = ["FletPlatform", "use_notices", "use_platform_requests", "use_shortcuts"]


class FletPlatform:
    """一次会话一份：剪贴板与文件选择器都是页面级服务，不能重复注册。"""

    def __init__(self, page: ft.Page, clipboard: ft.Clipboard, picker: ft.FilePicker) -> None:
        self.page = page
        self._clipboard = clipboard
        self._picker = picker

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
            selected = await self._picker.get_directory_path(dialog_title=title or None)
        except Exception as exc:
            logger.warning("打开目录选择框失败：%s", exc)
            vm.notify(f"打开目录选择框失败：{exc}")
            return
        vm.accept_directory(selected or "")

    async def _save_file(self, request: PlatformRequest, vm: ViewModel) -> None:
        try:
            saved = await self._picker.save_file(
                dialog_title="导出提交明细",
                file_name=request.text,
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["csv"],
                src_bytes=request.data,
            )
        except Exception as exc:
            logger.warning("保存文件失败：%s", exc)
            vm.export_finished(None, str(exc))
            return
        vm.export_finished(saved)


# --------------------------------------------------------------------------- 钩子
def use_platform_requests(platform: FletPlatform, vm: ViewModel) -> None:
    """把视图模型发出的平台请求交给 :class:`FletPlatform` 执行。

    请求对象本身参与依赖比较，因此只有"新的一条请求"才会触发执行，
    重复渲染不会把同一次操作做两遍。
    """
    request = vm.request

    def setup() -> None:
        if request is not None:
            platform.page.run_task(platform.perform, request, vm)

    ft.use_effect(setup, [request])


def use_notices(page: ft.Page, vm: ViewModel) -> None:
    """播报视图模型的一次性提示。

    ``notice`` 自带单调序号，视图记住最近播报过的那条，因此重渲染不会重复弹窗。
    """
    notice = vm.notice
    announced = ft.use_ref(0)

    def setup() -> None:
        if notice is not None and notice.seq != announced.current:
            announced.current = notice.seq
            widgets.toast(page, notice.message, tone=notice.tone)

    ft.use_effect(setup, [notice])


def use_shortcuts(page: ft.Page, vm: AppViewModel) -> None:
    """把键盘事件归一化后交给视图模型，卸载时解除绑定。"""

    def setup():
        page.on_keyboard_event = lambda event: vm.on_shortcut(
            Shortcut(key=event.key, ctrl=bool(event.ctrl))
        )
        return lambda: setattr(page, "on_keyboard_event", None)

    ft.use_effect(setup, [])
