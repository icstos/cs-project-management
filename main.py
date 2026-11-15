"""应用入口：装配程序、配置页面与窗口，然后挂载根组件。

页面级配置（主题、窗口、标题）集中在这里 —— 组件不直接改 page 属性。
**主题与字体只有 cs-ui 一个事实源**：``ui.apply_theme`` 同时下发浅色与深色两套
主题，并把框架自带的那款字体注册到 ``page.fonts``；本模块只负责告诉它"先按哪一档
显示"，既不持有字体文件，也不碰字体族名 —— 字体随框架走，一次换、处处对。

启动顺序有两条硬约束：

1. **日志必须在 ``ui.run`` 之前装配**。框架只在根 logger 还没有 handler 时才
   ``basicConfig``，先装好才能把框架自身的日志一起收进文件。
2. **异常钩子必须在事件循环内安装**，否则接管不到 asyncio 任务的未捕获异常。

``configure_page`` 之后才 ``page.render``，因为渲染会立刻读窗口尺寸与主题。
"""

from __future__ import annotations

import logging
from functools import partial

import ui

from models.settings import (
    APP_NAME,
    APP_TAGLINE,
    WINDOW_HEIGHT,
    WINDOW_MIN_HEIGHT,
    WINDOW_MIN_WIDTH,
    WINDOW_WIDTH,
)
from view.app import App
from viewmodel.container import Application, build_application

logger = logging.getLogger(__name__)


def configure_page(page: ui.Page) -> None:
    """把窗口、主题与字体一次性配好。"""
    page.title = f"{APP_NAME} · {APP_TAGLINE}"
    page.padding = 0

    # 浅色为默认（与既有观感一致）；``apply_theme`` 会把明暗两套一起写进
    # page.theme / page.dark_theme，运行时切换只是换一棵现成的树。
    # 字体注册也在这一次调用里完成（见 ui.core.fonts）：漏了注册，主题里的
    # font_family 就无处可解析，字体会静默退回系统默认 —— 所以不在这里分两步做。
    theme = ui.theme_state()
    theme.set_mode("light")
    ui.apply_theme(page, theme)

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

    async def main(page: ui.Page) -> None:
        application.prepare()
        configure_page(page)
        page.render(partial(App, vm=application.create_view_model()))
        await page.window.center()
        logger.info("窗口已就绪（%dx%d）", WINDOW_WIDTH, WINDOW_HEIGHT)

    return main


def run() -> None:
    application = build_application()
    # 先装配日志再交给 ui.run —— 顺序反了框架日志就进不了文件。
    # 版本号取 cs-ui 的 ui.FLET_VERSION：本工程不再直接依赖 flet 包，
    # 运行在哪个框架版本上一律问框架自己。
    application.start(flet_version=ui.FLET_VERSION)
    ui.run(build_main(application), name=APP_NAME)


if __name__ == "__main__":
    run()
