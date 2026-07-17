import flet as ft

from models.database import init_db
from views.app import App


async def main(page: ft.Page) -> None:
    init_db()

    page.title = "CS 项目管理"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.theme = ft.Theme(color_scheme_seed=ft.Colors.BLUE)
    page.padding = 0
    page.window.width = 1180
    page.window.height = 760
    page.window.min_width = 960
    page.window.min_height = 640
    await page.window.center()

    page.render(App)


if __name__ == "__main__":
    ft.run(main)
