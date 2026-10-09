"""应用入口：装配程序、配置页面与窗口，然后挂载根组件。

页面级配置（主题、窗口、标题、字体）集中在这里 —— 组件不直接改 page 属性。

启动顺序有两条硬约束：

1. **日志必须在 ``ft.run`` 之前装配**。flet 只在根 logger 还没有 handler 时才
   ``basicConfig``，先装好才能把框架自身的日志一起收进文件。
2. **异常钩子必须在事件循环内安装**，否则接管不到 asyncio 任务的未捕获异常。

``configure_page`` 之后才 ``page.render``，因为渲染会立刻读窗口尺寸与主题。
"""

from __future__ import annotations

import logging
from functools import partial

import flet as ft
from flet.version import flet_version

from infra import locations
from models.settings import (
    APP_NAME,
    APP_TAGLINE,
    FONT_ASSET_PATH,
    FONT_FAMILY,
    WINDOW_HEIGHT,
    WINDOW_MIN_HEIGHT,
    WINDOW_MIN_WIDTH,
    WINDOW_WIDTH,
)
from view import design
from view.app import App
from viewmodel.container import Application, build_application

logger = logging.getLogger(__name__)


def configure_page(page: ft.Page) -> None:
    """把窗口、主题与字体一次性配好。"""
    page.title = f"{APP_NAME} · {APP_TAGLINE}"

    # 自定义字体必须先注册到 page.fonts（值为相对 assets 目录的路径），
    # 主题里的 font_family 才解析得到；漏了这一步字体会静默退回系统默认。
    font_file = locations.font_file()
    if font_file.exists():
        page.fonts = {FONT_FAMILY: FONT_ASSET_PATH}
    else:
        logger.warning("本地字体缺失，回退系统默认字体：%s", font_file)

    # 浅色为默认主题，深色主题同源注册；二者由外壳上的按钮切换（page.theme_mode）。
    # 两套 Theme 结构完全一致，只有色板不同，因此界面代码不需要区分明暗。
    page.theme = design.build_theme()
    page.dark_theme = design.build_dark_theme()
    page.theme_mode = ft.ThemeMode.LIGHT
    page.bgcolor = ft.Colors.SURFACE
    page.padding = 0

    window = page.window
    window.width = WINDOW_WIDTH
    window.height = WINDOW_HEIGHT
    window.min_width = WINDOW_MIN_WIDTH
    window.min_height = WINDOW_MIN_HEIGHT


def build_main(application: Application):
    """把程序装配包成一个会话回调。

    每个窗口一份视图模型：界面状态不能跨会话共享，而服务与基础设施是
    无状态的，可以在多个会话之间复用。
    """

    async def main(page: ft.Page) -> None:
        application.prepare()
        configure_page(page)
        page.render(partial(App, vm=application.create_view_model()))
        await page.window.center()
        logger.info("窗口已就绪（%dx%d）", WINDOW_WIDTH, WINDOW_HEIGHT)

    return main


def run() -> None:
    application = build_application()
    # 先装配日志再交给 ft.run —— 顺序反了框架日志就进不了文件。
    application.start(flet_version=flet_version)
    ft.run(build_main(application), name=APP_NAME)


if __name__ == "__main__":
    run()
