"""界面基础件。

这里集中三件事，让各视图只关心"内容"而不是"样式"：

* 常用控件工厂（按钮、卡片、标签、空状态、指标卡、提示条）；
* 统一的反馈入口 ``toast``（Flet 1.0 已移除 ``page.snack_bar``，改用 ``show_dialog``）；
* 面向中文使用习惯的格式化函数。
"""

from __future__ import annotations

from datetime import datetime

import flet as ft

from core import theme as T
from models.dto import Permission


# --------------------------------------------------------------------------- 文本
def muted(text: str, *, size: int = 12, expand: bool = False, max_lines: int = 1) -> ft.Text:
    return ft.Text(
        text,
        size=size,
        color=T.MUTED_TEXT,
        expand=expand,
        max_lines=max_lines,
        overflow=ft.TextOverflow.ELLIPSIS,
    )


def title(text: str, *, size: int = 20, weight=ft.FontWeight.W_600) -> ft.Text:
    return ft.Text(text, size=size, weight=weight)


def key_hint(keys: str) -> ft.Container:
    """快捷键角标，例如 ⌘/Ctrl + N。"""
    return ft.Container(
        content=ft.Text(keys, size=10, color=T.MUTED_TEXT, weight=ft.FontWeight.W_500),
        padding=ft.Padding.symmetric(horizontal=6, vertical=2),
        border_radius=T.RADIUS_SM,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
        border=ft.Border.all(1, T.BORDER_COLOR),
    )


def format_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M")


def format_day(value) -> str:
    return value.strftime("%m-%d")


def format_relative(value: datetime, *, now: datetime | None = None) -> str:
    """人类友好的相对时间，超过一周则回退到具体日期。"""
    reference = now or datetime.now()
    seconds = (reference - value).total_seconds()
    match seconds:
        case s if s < 0:
            return format_datetime(value)
        case s if s < 60:
            return "刚刚"
        case s if s < 3600:
            return f"{int(s // 60)} 分钟前"
        case s if s < 86_400:
            return f"{int(s // 3600)} 小时前"
        case s if s < 604_800:
            return f"{int(s // 86_400)} 天前"
        case _:
            return format_datetime(value)


def format_count(value: int) -> str:
    return f"{value:,}"


def event_value(event):
    """取输入类控件本次事件携带的新值。

    Flet 客户端在抛出 ``change`` / ``select`` 时会先把新值作为事件数据送出，
    而回写 ``value`` 属性走的是另一条消息、并不保证先到达（例如 Switch 用
    ``notify=True`` 立即发送，TextField 则是延迟发送）。所以事件处理器一律
    以 ``event.data`` 为准，不要读 ``event.control.value``，否则可能读到旧值。
    """
    return getattr(event, "data", None)


# --------------------------------------------------------------------------- 按钮
def filled(
    text: str,
    *,
    icon: str | None = None,
    on_click=None,
    disabled: bool = False,
    tooltip: str | None = None,
) -> ft.FilledButton:
    return ft.FilledButton(
        content=text,
        icon=icon,
        on_click=on_click,
        disabled=disabled,
        tooltip=tooltip,
    )


def outlined(
    text: str,
    *,
    icon: str | None = None,
    on_click=None,
    disabled: bool = False,
    tooltip: str | None = None,
) -> ft.OutlinedButton:
    return ft.OutlinedButton(
        content=text,
        icon=icon,
        on_click=on_click,
        disabled=disabled,
        tooltip=tooltip,
    )


def text_btn(
    text: str,
    *,
    icon: str | None = None,
    on_click=None,
    disabled: bool = False,
    tone: T.Tone | None = None,
) -> ft.TextButton:
    style = None
    if tone is not None:
        style = ft.ButtonStyle(color=T.tone_style(tone).accent)
    return ft.TextButton(
        content=text,
        icon=icon,
        on_click=on_click,
        disabled=disabled,
        style=style,
    )


def danger(
    text: str,
    *,
    icon: str = ft.Icons.DELETE_OUTLINE,
    on_click=None,
    disabled: bool = False,
) -> ft.FilledButton:
    return ft.FilledButton(
        content=text,
        icon=icon,
        on_click=on_click,
        disabled=disabled,
        style=ft.ButtonStyle(
            bgcolor=ft.Colors.ERROR,
            color=ft.Colors.ON_ERROR,
            shape=ft.RoundedRectangleBorder(radius=T.RADIUS_MD),
            padding=ft.Padding.symmetric(horizontal=18, vertical=12),
        ),
    )


def icon_action(
    icon: str,
    tooltip: str,
    on_click,
    *,
    tone: T.Tone = T.Tone.NEUTRAL,
    disabled: bool = False,
) -> ft.IconButton:
    style = T.tone_style(tone)
    color = ft.Colors.PRIMARY if tone is T.Tone.PRIMARY else style.accent
    return ft.IconButton(
        icon=icon,
        tooltip=tooltip,
        on_click=on_click,
        disabled=disabled,
        icon_size=19,
        icon_color=color if tone is not T.Tone.NEUTRAL else T.MUTED_TEXT,
        style=ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=T.RADIUS_SM),
            padding=8,
            bgcolor={
                ft.ControlState.HOVERED: ft.Colors.with_opacity(0.10, color),
                ft.ControlState.DEFAULT: ft.Colors.TRANSPARENT,
            },
        ),
    )


# --------------------------------------------------------------------------- 容器
def surface(
    content,
    *,
    padding: int | ft.Padding = T.CARD_PADDING,
    expand: bool = False,
    key: str | None = None,
    col=None,
    height: int | None = None,
    on_click=None,
    hover: bool = False,
) -> ft.Container:
    return ft.Container(
        key=key,
        col=col,
        height=height,
        expand=expand,
        content=content,
        padding=padding,
        on_click=on_click,
        border_radius=T.RADIUS_LG,
        bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
        border=ft.Border.all(1, T.BORDER_COLOR),
        shadow=T.CARD_SHADOW if hover is False else None,
        ink=on_click is not None,
        animate=(
            ft.Animation(duration=160, curve=ft.AnimationCurve.EASE_OUT)
            if on_click is not None
            else None
        ),
    )


def flat_panel(content, *, padding: int = T.SPACE_LG) -> ft.Container:
    """低对比度的信息面板，用于承载次要说明。"""
    return ft.Container(
        content=content,
        padding=padding,
        border_radius=T.RADIUS_MD,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
        border=ft.Border.all(1, T.BORDER_COLOR),
    )


def divider(*, vertical: bool = False) -> ft.Control:
    if vertical:
        return ft.VerticalDivider(width=1, thickness=1, color=T.BORDER_COLOR)
    return ft.Divider(height=1, thickness=1, color=T.BORDER_COLOR)


# --------------------------------------------------------------------------- 标签
def pill(
    label: str,
    *,
    tone: T.Tone = T.Tone.NEUTRAL,
    icon: str | None = None,
    dense: bool = False,
) -> ft.Container:
    style = T.tone_style(tone)
    return ft.Container(
        content=ft.Row(
            spacing=T.SPACE_XS,
            tight=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                *([ft.Icon(icon, size=13, color=style.on_container)] if icon else []),
                ft.Text(
                    label,
                    size=11 if dense else 12,
                    weight=ft.FontWeight.W_500,
                    color=style.on_container,
                ),
            ],
        ),
        padding=ft.Padding.symmetric(horizontal=8 if dense else 10, vertical=3 if dense else 5),
        border_radius=T.RADIUS_PILL,
        bgcolor=style.container,
    )


def flag_pill(label: str, ok: bool, *, bad_tone: T.Tone = T.Tone.WARNING) -> ft.Container:
    return pill(
        label,
        tone=T.Tone.NEUTRAL if ok else bad_tone,
        icon=ft.Icons.CHECK_CIRCLE if ok else ft.Icons.WARNING_AMBER_ROUNDED,
        dense=True,
    )


def permission_pill(permission: Permission) -> ft.Container:
    public = permission is Permission.PUBLIC
    return pill(
        permission.label,
        tone=T.Tone.INFO if public else T.Tone.NEUTRAL,
        icon=ft.Icons.PUBLIC if public else ft.Icons.LOCK,
        dense=True,
    )


def diff_text(insertions: int, deletions: int, *, size: int = 13) -> ft.Row:
    """git 约定：新增绿、删除红。"""
    return ft.Row(
        spacing=T.SPACE_SM,
        tight=True,
        controls=[
            ft.Text(
                f"+{format_count(insertions)}",
                size=size,
                color=T.ADDITION_COLOR,
                weight=ft.FontWeight.W_600,
            ),
            ft.Text(
                f"-{format_count(deletions)}",
                size=size,
                color=T.DELETION_COLOR,
                weight=ft.FontWeight.W_600,
            ),
        ],
    )


# --------------------------------------------------------------------------- 区块
def section(title_text: str, subtitle: str | None = None) -> ft.Column:
    controls: list[ft.Control] = [
        ft.Text(title_text, size=24, weight=ft.FontWeight.BOLD),
    ]
    if subtitle:
        controls.append(muted(subtitle, size=13, max_lines=2))
    return ft.Column(spacing=T.SPACE_XS, tight=True, controls=controls)


def page_header(
    title_text: str,
    subtitle: str | None = None,
    *,
    actions: list[ft.Control] | None = None,
) -> ft.Row:
    return ft.Row(
        spacing=T.SPACE_MD,
        vertical_alignment=ft.CrossAxisAlignment.START,
        controls=[
            ft.Column(
                spacing=T.SPACE_XS,
                tight=True,
                expand=True,
                controls=section(title_text, subtitle).controls,
            ),
            ft.Row(spacing=T.SPACE_SM, tight=True, controls=actions or []),
        ],
    )


def page_shell(*, header: ft.Control, body: ft.Control) -> ft.Container:
    return ft.Container(
        expand=True,
        padding=T.PAGE_PADDING,
        bgcolor=T.SURFACE_COLOR,
        content=ft.Column(
            expand=True,
            spacing=T.SECTION_SPACING,
            controls=[header, body],
        ),
    )


def hint_row(icon: str, text: str, *, tone: T.Tone = T.Tone.INFO) -> ft.Row:
    style = T.tone_style(tone)
    return ft.Row(
        spacing=T.SPACE_SM,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.Icon(icon, size=16, color=style.accent),
            ft.Text(text, size=12, color=T.MUTED_TEXT, expand=True),
        ],
    )


# --------------------------------------------------------------------------- 指标卡
def metric(
    label: str,
    value: str,
    *,
    tone: T.Tone = T.Tone.PRIMARY,
    icon: str | None = None,
    hint: str | None = None,
    col=None,
) -> ft.Container:
    style = T.tone_style(tone)
    return ft.Container(
        col=col or {"xs": 12, "sm": 6, "md": 4, "lg": 2},
        padding=T.SPACE_LG,
        border_radius=T.RADIUS_LG,
        bgcolor=style.container,
        content=ft.Column(
            spacing=T.SPACE_XS,
            tight=True,
            controls=[
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Text(
                            label,
                            size=12,
                            weight=ft.FontWeight.W_500,
                            color=style.on_container,
                        ),
                        *([ft.Icon(icon, size=17, color=style.accent)] if icon else []),
                    ],
                ),
                ft.Text(
                    value,
                    size=24,
                    weight=ft.FontWeight.BOLD,
                    color=style.on_container,
                ),
                *([ft.Text(hint, size=11, color=style.accent)] if hint else []),
            ],
        ),
    )


# --------------------------------------------------------------------------- 状态
def empty_state(
    icon: str,
    title_text: str,
    hint: str,
    *,
    action: ft.Control | None = None,
) -> ft.Container:
    return ft.Container(
        expand=True,
        alignment=ft.Alignment.CENTER,
        padding=T.SPACE_XXL,
        content=ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=T.SPACE_MD,
            tight=True,
            controls=[
                ft.Container(
                    width=76,
                    height=76,
                    border_radius=T.RADIUS_PILL,
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
                    alignment=ft.Alignment.CENTER,
                    content=ft.Icon(icon, size=36, color=ft.Colors.OUTLINE),
                ),
                ft.Text(title_text, size=17, weight=ft.FontWeight.W_600),
                ft.Text(
                    hint,
                    size=13,
                    color=T.MUTED_TEXT,
                    text_align=ft.TextAlign.CENTER,
                    max_lines=3,
                ),
                *(
                    [ft.Container(content=action, margin=ft.Margin.only(top=T.SPACE_SM))]
                    if action
                    else []
                ),
            ],
        ),
    )


def busy_block(text: str = "正在加载…") -> ft.Container:
    return ft.Container(
        expand=True,
        alignment=ft.Alignment.CENTER,
        content=ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=T.SPACE_MD,
            tight=True,
            controls=[
                ft.ProgressRing(width=30, height=30, stroke_width=3),
                muted(text, size=13),
            ],
        ),
    )


def inline_error(message: str) -> ft.Row:
    return hint_row(ft.Icons.ERROR_OUTLINE, message, tone=T.Tone.DANGER)


def toast(page: ft.Page, message: str, *, tone: T.Tone = T.Tone.SUCCESS) -> None:
    """右下角浮动提示。"""
    style = T.tone_style(tone)
    page.show_dialog(
        ft.SnackBar(
            content=ft.Row(
                spacing=T.SPACE_SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Icon(style.icon, color=ft.Colors.WHITE, size=19),
                    ft.Text(message, color=ft.Colors.WHITE, size=13, expand=True),
                ],
            ),
            bgcolor=style.accent,
            behavior=ft.SnackBarBehavior.FLOATING,
            shape=ft.RoundedRectangleBorder(radius=T.RADIUS_MD),
            margin=ft.Margin.all(T.SPACE_LG),
            duration=ft.Duration(seconds=3),
        )
    )


def confirm_dialog(
    *,
    title_text: str,
    message: str,
    confirm_label: str,
    on_confirm,
    on_cancel,
    extra: ft.Control | None = None,
) -> ft.AlertDialog:
    return ft.AlertDialog(
        modal=True,
        title=ft.Text(title_text, size=18, weight=ft.FontWeight.W_600),
        content=ft.Column(
            width=T.DIALOG_WIDTH,
            tight=True,
            spacing=T.SPACE_MD,
            controls=[
                ft.Text(message, size=13),
                *([extra] if extra else []),
            ],
        ),
        actions=[
            text_btn("取消", on_click=on_cancel),
            danger(confirm_label, on_click=on_confirm),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
