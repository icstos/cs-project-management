from datetime import datetime

import flet as ft

from models.database import Permission, Project


def show_snack(page: ft.Page, message: str, *, error: bool = False) -> None:
    page.snack_bar = ft.SnackBar(
        content=ft.Text(message),
        bgcolor=ft.Colors.ERROR if error else ft.Colors.GREEN_700,
        behavior=ft.SnackBarBehavior.FLOATING,
    )
    page.snack_bar.open = True
    page.update()


def format_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M")


def status_chip(label: str, active: bool, active_color: ft.Colors) -> ft.Chip:
    return ft.Chip(
        label=ft.Text(label),
        bgcolor=active_color if active else ft.Colors.SURFACE_CONTAINER_HIGHEST,
        color=ft.Colors.ON_PRIMARY if active else ft.Colors.ON_SURFACE_VARIANT,
    )


def permission_badge(permission: str) -> ft.Container:
    is_public = permission == Permission.PUBLIC.value
    return ft.Container(
        content=ft.Text(
            Permission.PUBLIC.label if is_public else Permission.PRIVATE.label,
            size=12,
            color=ft.Colors.ON_PRIMARY,
        ),
        bgcolor=ft.Colors.BLUE_600 if is_public else ft.Colors.GREY_700,
        padding=ft.Padding.symmetric(horizontal=10, vertical=4),
        border_radius=12,
    )


def section_header(title: str, subtitle: str) -> ft.Column:
    return ft.Column(
        spacing=4,
        controls=[
            ft.Text(title, size=24, weight=ft.FontWeight.BOLD),
            ft.Text(subtitle, size=13, color=ft.Colors.ON_SURFACE_VARIANT),
        ],
    )


def empty_state(icon: str, title: str, hint: str) -> ft.Container:
    return ft.Container(
        alignment=ft.Alignment.CENTER,
        expand=True,
        content=ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=8,
            controls=[
                ft.Icon(icon, size=56, color=ft.Colors.OUTLINE),
                ft.Text(title, size=18, weight=ft.FontWeight.W_600),
                ft.Text(hint, color=ft.Colors.ON_SURFACE_VARIANT),
            ],
        ),
    )
