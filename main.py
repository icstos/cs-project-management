import flet as ft

from models.database import init_db
from views.app import App


def build_theme() -> ft.Theme:
    button_shape = ft.RoundedRectangleBorder(radius=10)
    button_style = ft.ButtonStyle(
        shape=button_shape,
        padding=ft.Padding.symmetric(horizontal=18, vertical=12),
    )

    return ft.Theme(
        color_scheme_seed=ft.Colors.INDIGO,
        use_material3=True,
        visual_density=ft.VisualDensity.COMFORTABLE,
        card_theme=ft.CardTheme(
            elevation=0,
            shape=ft.RoundedRectangleBorder(radius=14),
            margin=0,
            color=ft.Colors.SURFACE_CONTAINER_LOW,
        ),
        filled_button_theme=ft.FilledButtonTheme(style=button_style),
        outlined_button_theme=ft.OutlinedButtonTheme(
            style=ft.ButtonStyle(
                shape=button_shape,
                padding=ft.Padding.symmetric(horizontal=18, vertical=12),
                side=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT),
            )
        ),
        text_button_theme=ft.TextButtonTheme(
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=8),
                padding=ft.Padding.symmetric(horizontal=16, vertical=10),
            )
        ),
        icon_button_theme=ft.IconButtonTheme(
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=8),
            )
        ),
        navigation_rail_theme=ft.NavigationRailTheme(
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            indicator_color=ft.Colors.PRIMARY_CONTAINER,
            indicator_shape=ft.RoundedRectangleBorder(radius=12),
            label_type=ft.NavigationRailLabelType.ALL,
        ),
        snackbar_theme=ft.SnackBarTheme(
            behavior=ft.SnackBarBehavior.FLOATING,
            shape=ft.RoundedRectangleBorder(radius=10),
        ),
        data_table_theme=ft.DataTableTheme(
            heading_row_color=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            heading_text_style=ft.TextStyle(weight=ft.FontWeight.W_600),
        ),
    )


async def main(page: ft.Page) -> None:
    init_db()

    page.title = "CS 项目管理"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.theme = build_theme()
    page.bgcolor = ft.Colors.SURFACE
    page.padding = 0
    page.window.width = 1180
    page.window.height = 760
    page.window.min_width = 960
    page.window.min_height = 640
    await page.window.center()

    page.render(App)


if __name__ == "__main__":
    ft.run(main)
