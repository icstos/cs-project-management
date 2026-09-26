"""应用入口：初始化数据库、配置页面与窗口，然后挂载根组件。

页面级配置（主题、窗口、标题）集中在这里，业务组件不直接改 page 属性。
"""

from __future__ import annotations

import logging

import flet as ft

from core.config import (
    APP_NAME,
    APP_TAGLINE,
    FONT_ASSET_PATH,
    FONT_FAMILY,
    FONT_FILE,
    WINDOW_HEIGHT,
    WINDOW_MIN_HEIGHT,
    WINDOW_MIN_WIDTH,
    WINDOW_WIDTH,
)
from core.theme import build_theme
from models.database import init_db
from views.app import App

logger = logging.getLogger(__name__)


def configure_page(page: ft.Page) -> None:
    page.title = f"{APP_NAME} · {APP_TAGLINE}"

    # 自定义字体必须先注册到 page.fonts（值为相对 assets 目录的路径），
    # 主题里的 font_family 才解析得到；漏了这一步字体会静默退回系统默认。
    if FONT_FILE.exists():
        page.fonts = {FONT_FAMILY: FONT_ASSET_PATH}
    else:
        logger.warning("本地字体缺失，回退系统默认字体：%s", FONT_FILE)

    page.theme_mode = ft.ThemeMode.LIGHT
    page.theme = build_theme()
    page.bgcolor = ft.Colors.SURFACE
    page.padding = 0

    window = page.window
    window.width = WINDOW_WIDTH
    window.height = WINDOW_HEIGHT
    window.min_width = WINDOW_MIN_WIDTH
    window.min_height = WINDOW_MIN_HEIGHT


async def main(page: ft.Page) -> None:
    init_db()
    configure_page(page)
    page.render(App)
    await page.window.center()


def run() -> None:
    ft.run(main, name=APP_NAME)


if __name__ == "__main__":
    run()
