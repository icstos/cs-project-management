from datetime import datetime

import flet as ft

from models.database import Permission, Project

BORDER_RADIUS = 10
CARD_RADIUS = 14
CARD_SHADOW = ft.BoxShadow(
    spread_radius=0,
    blur_radius=12,
    color=ft.Colors.with_opacity(0.08, ft.Colors.BLACK),
    offset=ft.Offset(0, 4),
)


def _button_shape(radius: int = BORDER_RADIUS) -> ft.RoundedRectangleBorder:
    return ft.RoundedRectangleBorder(radius=radius)


def primary_button(
    text: str,
    *,
    icon=None,
    on_click=None,
    disabled: bool = False,
) -> ft.FilledButton:
    return ft.FilledButton(
        text,
        icon=icon,
        disabled=disabled,
        on_click=on_click,
        style=ft.ButtonStyle(
            shape=_button_shape(),
            padding=ft.Padding.symmetric(horizontal=20, vertical=12),
            elevation=1,
        ),
    )


def secondary_button(
    text: str,
    *,
    icon=None,
    on_click=None,
    disabled: bool = False,
) -> ft.OutlinedButton:
    return ft.OutlinedButton(
        text,
        icon=icon,
        disabled=disabled,
        on_click=on_click,
        style=ft.ButtonStyle(
            shape=_button_shape(),
            padding=ft.Padding.symmetric(horizontal=18, vertical=12),
            side=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT),
        ),
    )


def danger_button(
    text: str,
    *,
    icon=None,
    on_click=None,
    disabled: bool = False,
) -> ft.FilledButton:
    return ft.FilledButton(
        text,
        icon=icon,
        disabled=disabled,
        on_click=on_click,
        style=ft.ButtonStyle(
            shape=_button_shape(),
            padding=ft.Padding.symmetric(horizontal=18, vertical=12),
            bgcolor=ft.Colors.ERROR,
            color=ft.Colors.ON_ERROR,
        ),
    )


def text_button(
    text: str,
    *,
    on_click=None,
    disabled: bool = False,
) -> ft.TextButton:
    return ft.TextButton(
        text,
        disabled=disabled,
        on_click=on_click,
        style=ft.ButtonStyle(
            shape=_button_shape(8),
            padding=ft.Padding.symmetric(horizontal=16, vertical=10),
        ),
    )


def icon_action_button(
    icon,
    tooltip: str,
    on_click,
    *,
    danger: bool = False,
) -> ft.IconButton:
    accent = ft.Colors.ERROR if danger else ft.Colors.PRIMARY
    return ft.IconButton(
        icon=icon,
        tooltip=tooltip,
        icon_color=accent if danger else ft.Colors.ON_SURFACE_VARIANT,
        icon_size=20,
        style=ft.ButtonStyle(
            shape=_button_shape(8),
            padding=8,
            bgcolor={
                ft.ControlState.HOVERED: ft.Colors.with_opacity(0.12, accent),
                ft.ControlState.DEFAULT: ft.Colors.with_opacity(
                    0.04, ft.Colors.ON_SURFACE
                ),
            },
        ),
        on_click=on_click,
    )


def surface_card(
    content,
    *,
    padding: int = 16,
    expand: bool = False,
    key: str | None = None,
) -> ft.Container:
    return ft.Container(
        key=key,
        expand=expand,
        padding=padding,
        border_radius=CARD_RADIUS,
        bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        shadow=CARD_SHADOW,
        content=content,
    )


def stat_card(
    title: str,
    value: str,
    *,
    icon,
    bgcolor,
    fgcolor,
) -> ft.Container:
    return ft.Container(
        col={"xs": 12, "sm": 4},
        padding=18,
        border_radius=CARD_RADIUS,
        bgcolor=bgcolor,
        border=ft.Border.all(1, ft.Colors.with_opacity(0.2, fgcolor)),
        content=ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Column(
                    spacing=6,
                    expand=True,
                    controls=[
                        ft.Text(
                            title, size=13, color=fgcolor, weight=ft.FontWeight.W_500
                        ),
                        ft.Text(
                            value, size=26, weight=ft.FontWeight.BOLD, color=fgcolor
                        ),
                    ],
                ),
                ft.Container(
                    width=44,
                    height=44,
                    border_radius=12,
                    bgcolor=ft.Colors.with_opacity(0.15, fgcolor),
                    alignment=ft.Alignment.CENTER,
                    content=ft.Icon(icon, color=fgcolor, size=22),
                ),
            ],
        ),
    )


def info_panel(content) -> ft.Container:
    return ft.Container(
        padding=16,
        border_radius=CARD_RADIUS,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        content=content,
    )


def show_snack(page: ft.Page, message: str, *, error: bool = False) -> None:
    page.snack_bar = ft.SnackBar(
        content=ft.Row(
            spacing=10,
            controls=[
                ft.Icon(
                    ft.Icons.ERROR_OUTLINE if error else ft.Icons.CHECK_CIRCLE_OUTLINE,
                    color=ft.Colors.ON_PRIMARY,
                    size=20,
                ),
                ft.Text(message, color=ft.Colors.ON_PRIMARY),
            ],
        ),
        bgcolor=ft.Colors.ERROR if error else ft.Colors.GREEN_700,
        behavior=ft.SnackBarBehavior.FLOATING,
        shape=ft.RoundedRectangleBorder(radius=10),
        margin=16,
    )
    page.snack_bar.open = True
    page.update()


def format_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M")


_STATUS_CHIP_GRAY = ft.Colors.GREY_600
_STATUS_CHIP_YELLOW = ft.Colors.AMBER_700


def status_chip(label: str, healthy: bool) -> ft.Container:
    """healthy=True 灰色（状态正常），healthy=False 黄色（需关注）。"""
    color = _STATUS_CHIP_GRAY if healthy else _STATUS_CHIP_YELLOW
    return ft.Container(
        content=ft.Row(
            spacing=6,
            tight=True,
            controls=[
                ft.Icon(
                    ft.Icons.CHECK_CIRCLE if healthy else ft.Icons.ERROR_OUTLINE,
                    size=14,
                    color=ft.Colors.WHITE,
                ),
                ft.Text(
                    label,
                    size=12,
                    weight=ft.FontWeight.W_500,
                    color=ft.Colors.WHITE,
                ),
            ],
        ),
        bgcolor=color,
        padding=ft.Padding.symmetric(horizontal=10, vertical=6),
        border_radius=20,
        border=ft.Border.all(1, color),
    )


def local_changes_chip(has_changes: bool) -> ft.Container:
    return status_chip(
        "有本地变更" if has_changes else "无本地变更",
        not has_changes,
    )


def permission_badge(permission: str) -> ft.Container:
    is_public = permission == Permission.PUBLIC.value
    color = ft.Colors.BLUE_600 if is_public else ft.Colors.GREY_700
    return ft.Container(
        content=ft.Row(
            spacing=4,
            tight=True,
            controls=[
                ft.Icon(
                    ft.Icons.PUBLIC if is_public else ft.Icons.LOCK,
                    size=14,
                    color=ft.Colors.ON_PRIMARY,
                ),
                ft.Text(
                    Permission.PUBLIC.label if is_public else Permission.PRIVATE.label,
                    size=12,
                    weight=ft.FontWeight.W_500,
                    color=ft.Colors.ON_PRIMARY,
                ),
            ],
        ),
        bgcolor=color,
        padding=ft.Padding.symmetric(horizontal=10, vertical=5),
        border_radius=20,
    )


def section_header(title: str, subtitle: str) -> ft.Column:
    return ft.Column(
        spacing=6,
        controls=[
            ft.Text(title, size=26, weight=ft.FontWeight.BOLD),
            ft.Text(subtitle, size=13, color=ft.Colors.ON_SURFACE_VARIANT),
        ],
    )


def empty_state(icon: str, title: str, hint: str) -> ft.Container:
    return ft.Container(
        alignment=ft.Alignment.CENTER,
        expand=True,
        content=ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=12,
            controls=[
                ft.Container(
                    width=80,
                    height=80,
                    border_radius=40,
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                    alignment=ft.Alignment.CENTER,
                    content=ft.Icon(icon, size=40, color=ft.Colors.OUTLINE),
                ),
                ft.Text(title, size=18, weight=ft.FontWeight.W_600),
                ft.Text(
                    hint,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                    text_align=ft.TextAlign.CENTER,
                ),
            ],
        ),
    )


def page_container(content) -> ft.Container:
    return ft.Container(
        expand=True,
        padding=24,
        bgcolor=ft.Colors.SURFACE,
        content=content,
    )
