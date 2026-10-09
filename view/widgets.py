"""界面基础件。

这里集中三件事，让各视图只关心"内容"而不是"样式"：

* 常用控件工厂（按钮、卡片、标签、空状态、指标卡、骨架屏、提示条）；
* 统一的反馈入口 :func:`toast`（Flet 1.0 已移除 ``page.snack_bar``，改用 ``show_dialog``）；
* 事件取值助手 :func:`event_value`。

所有构件都从 :mod:`view.design` 取令牌，圆角 / 间距 / 颜色 / 过渡时长因此全应用一致。
纯构件，不含业务判断 —— 需要判断的地方都发生在视图模型里。
"""

from __future__ import annotations

import flet as ft

from models.enums import Permission, Tone
from view import design as T
from viewmodel.formatting import format_count

__all__ = [
    "busy_block",
    "chart_label",
    "confirm_dialog",
    "danger",
    "diff_text",
    "divider",
    "empty_state",
    "event_value",
    "field_fill",
    "filled",
    "filter_chip",
    "flag_pill",
    "flat_panel",
    "hint_row",
    "icon_action",
    "inline_error",
    "key_hint",
    "metric",
    "muted",
    "outlined",
    "page_header",
    "page_shell",
    "permission_pill",
    "pill",
    "skeleton_block",
    "skeleton_card",
    "surface",
    "text_btn",
    "toast",
]


# --------------------------------------------------------------------------- 事件
def event_value(event) -> object:
    """取输入类控件本次事件携带的新值。

    Flet 客户端在抛出 ``change`` / ``select`` 时会先把新值作为事件数据送出，
    而回写 ``value`` 属性走的是另一条消息、并不保证先到达（例如 Switch 用
    ``notify=True`` 立即发送，TextField 则是延迟发送）。所以事件处理器一律
    以 ``event.data`` 为准，不要读 ``event.control.value``，否则可能读到旧值。
    """
    return getattr(event, "data", None)


# --------------------------------------------------------------------------- 文本
def muted(
    value: str,
    *,
    size: int = 12,
    expand: bool = False,
    max_lines: int = 1,
    selectable: bool = False,
) -> ft.Text:
    """次级信息：辅助文字层级 + 中性色，保持统一的视觉重量。"""
    return T.text(
        value,
        level=T.TextLevel.LABEL,
        size=size,
        color=T.MUTED_TEXT,
        expand=expand,
        max_lines=max_lines,
        overflow=ft.TextOverflow.ELLIPSIS,
        selectable=selectable,
    )


def chart_label(value: str, *, size: int = 10) -> ft.Text:
    """图表内的轴标签 / 数据标签。

    这些文本由画布直接绘制，拿不到 Material 主题的默认文本样式，
    因此必须显式声明字体，否则会退回系统默认字体。
    """
    return ft.Text(
        value,
        size=size,
        color=T.MUTED_TEXT,
        font_family=T.FONT_FAMILY,
    )


def key_hint(keys: str) -> ft.Container:
    """快捷键角标，例如 Ctrl + N。"""
    return ft.Container(
        content=T.text(
            keys,
            level=T.TextLevel.CAPTION,
            color=T.MUTED_TEXT,
            weight=ft.FontWeight.W_500,
        ),
        padding=ft.Padding.symmetric(horizontal=8, vertical=3),
        border_radius=T.RADIUS_XS,
        bgcolor=T.PANEL_COLOR,
        border=ft.Border.all(1, T.BORDER_COLOR),
    )


def field_fill() -> ft.ColorValue:
    """输入框填充色。

    控件级显式指定，不依赖 InputDecoration 的默认值 —— 默认值是客户端按
    ``surfaceContainerHighest`` 算出来的，与我们的中性色板对不齐。聚焦反馈
    由 :func:`design.field_border` 的 2px 主色描边承担。
    """
    return ft.Colors.with_opacity(0.045, ft.Colors.ON_SURFACE)


def filter_chip(label: str, *, selected: bool, on_select) -> ft.Chip:
    """筛选胶囊。

    选中态用主色浅底 + 主色文字，未选中态是极淡底 + 中性文字：
    两种状态的"重量"接近，切换时不会让整行跳动。
    """
    accent = ft.Colors.ON_PRIMARY_CONTAINER if selected else T.MUTED_TEXT
    return ft.Chip(
        label=ft.Text(
            label,
            size=12,
            weight=ft.FontWeight.W_500,
            color=accent,
            font_family=T.FONT_FAMILY,
        ),
        selected=selected,
        show_checkmark=False,
        on_select=on_select,
        bgcolor=ft.Colors.with_opacity(0.045, ft.Colors.ON_SURFACE),
        selected_color=ft.Colors.PRIMARY_CONTAINER,
        border_side=ft.BorderSide(1, ft.Colors.TRANSPARENT),
        elevation=0,
        elevation_on_click=0,
        padding=ft.Padding.symmetric(horizontal=12, vertical=6),
        label_padding=0,
    )


# --------------------------------------------------------------------------- 按钮
def filled(
    text: str,
    *,
    icon: str | None = None,
    on_click=None,
    disabled: bool = False,
    tooltip: str | None = None,
) -> ft.FilledButton:
    """主按钮：实色填充 + 悬停时轻微浮起（样式来自主题的 FilledButtonTheme）。"""
    return ft.FilledButton(
        content=text,
        icon=icon,
        on_click=on_click,
        disabled=disabled,
        tooltip=tooltip,
        elevation=0,
        icon_color=ft.Colors.ON_PRIMARY,
    )


def outlined(
    text: str,
    *,
    icon: str | None = None,
    on_click=None,
    disabled: bool = False,
    tooltip: str | None = None,
) -> ft.OutlinedButton:
    """次按钮：描边 + 悬停时边框与文字转主色。"""
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
    tone: Tone | None = None,
) -> ft.TextButton:
    """文字按钮：最轻量的一档，用于"取消"这类低优先级动作。"""
    style = None if tone is None else ft.ButtonStyle(color=T.tone_style(tone).accent)
    return ft.TextButton(content=text, icon=icon, on_click=on_click, disabled=disabled, style=style)


def danger(
    text: str,
    *,
    icon: str = ft.Icons.DELETE_OUTLINE,
    on_click=None,
    disabled: bool = False,
) -> ft.FilledButton:
    """危险操作按钮：错误色实心，仍保持与主按钮一致的形状与内边距。"""
    return ft.FilledButton(
        content=text,
        icon=icon,
        on_click=on_click,
        disabled=disabled,
        style=ft.ButtonStyle(
            bgcolor=ft.Colors.ERROR,
            color=ft.Colors.ON_ERROR,
            icon_color=ft.Colors.ON_ERROR,
            elevation={
                ft.ControlState.DEFAULT: 0,
                ft.ControlState.HOVERED: 1,
                ft.ControlState.PRESSED: 0,
            },
            shadow_color=ft.Colors.with_opacity(0.35, ft.Colors.ERROR),
            shape=ft.RoundedRectangleBorder(radius=T.RADIUS_BUTTON),
            padding=ft.Padding.symmetric(horizontal=18, vertical=12),
            overlay_color=ft.Colors.with_opacity(0.12, ft.Colors.ON_ERROR),
            animation_duration=ft.Duration(milliseconds=T.DURATION_BASE),
            mouse_cursor=ft.MouseCursor.CLICK,
        ),
    )


def icon_action(
    icon: str,
    tooltip: str,
    on_click,
    *,
    tone: Tone = Tone.NEUTRAL,
    disabled: bool = False,
    size: int = T.ICON_MD,
) -> ft.IconButton:
    """图标按钮：默认透明，悬停时出现一层语义色薄底。"""
    color = T.tone_style(tone).accent
    return ft.IconButton(
        icon=icon,
        tooltip=tooltip,
        on_click=on_click,
        disabled=disabled,
        icon_size=size,
        icon_color=color,
        style=ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=T.RADIUS_SM),
            padding=8,
            bgcolor={
                ft.ControlState.HOVERED: ft.Colors.with_opacity(0.10, color),
                ft.ControlState.DEFAULT: ft.Colors.TRANSPARENT,
            },
            overlay_color=ft.Colors.with_opacity(0.10, color),
            animation_duration=ft.Duration(milliseconds=T.DURATION_FAST),
            mouse_cursor=ft.MouseCursor.CLICK,
        ),
    )


# --------------------------------------------------------------------------- 容器
def surface(
    content,
    *,
    padding=T.CARD_PADDING,
    expand: bool = False,
    key: str | None = None,
    col=None,
    height: int | None = None,
    on_click=None,
    on_hover=None,
    hovered: bool = False,
    bgcolor: ft.ColorValue | None = None,
    border: ft.Border | None = None,
    tooltip: str | None = None,
    animate: bool = True,
) -> ft.Container:
    """卡片容器：极淡填充 + 超细边框 + 柔和投影。

    ``hovered=True`` 时投影加深一档，配合 :func:`design.animate` 形成
    "悬停轻微抬起"的反馈；交互式卡片（``on_click``）另外拿到 Material 水波纹。
    """
    interactive = on_click is not None
    return ft.Container(
        key=key,
        col=col,
        height=height,
        expand=expand,
        content=content,
        padding=padding,
        tooltip=tooltip,
        on_click=on_click,
        on_hover=on_hover,
        border_radius=T.RADIUS_CARD,
        bgcolor=bgcolor or T.CARD_COLOR,
        border=border or ft.Border.all(1, T.BORDER_COLOR),
        shadow=T.card_shadow(hover=hovered),
        ink=interactive,
        ink_color=ft.Colors.with_opacity(0.06, ft.Colors.PRIMARY) if interactive else None,
        animate=T.animate() if animate else None,
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
    )


def flat_panel(content, *, padding: int = T.SPACE_LG) -> ft.Container:
    """低对比度的信息面板，用于承载次要说明（比卡片再浅一档）。"""
    return ft.Container(
        content=content,
        padding=padding,
        border_radius=T.RADIUS_MD,
        bgcolor=T.PANEL_COLOR,
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
    tone: Tone = Tone.NEUTRAL,
    icon: str | None = None,
    dense: bool = False,
) -> ft.Container:
    """胶囊标签：语义色浅底 + 同色发丝描边。"""
    style = T.tone_style(tone)
    return ft.Container(
        content=ft.Row(
            spacing=T.SPACE_XS,
            tight=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                *([ft.Icon(icon, size=13, color=style.accent)] if icon else []),
                T.text(
                    label,
                    level=T.TextLevel.CAPTION,
                    size=11 if dense else 12,
                    weight=ft.FontWeight.W_500,
                    color=style.on_container,
                ),
            ],
        ),
        padding=ft.Padding.symmetric(horizontal=9 if dense else 11, vertical=3 if dense else 5),
        border_radius=T.RADIUS_PILL,
        bgcolor=style.container,
        border=ft.Border.all(1, ft.Colors.with_opacity(0.16, style.accent)),
    )


def flag_pill(
    label: str,
    ok: bool,
    *,
    bad_label: str | None = None,
    bad_tone: Tone = Tone.WARNING,
) -> ft.Container:
    """状态角标。

    ``bad_label`` 给出否定说法：否则会出现"已配置远程"配一个警告色图标的怪状态。
    """
    return pill(
        label if ok else (bad_label or label),
        tone=Tone.NEUTRAL if ok else bad_tone,
        icon=ft.Icons.CHECK_CIRCLE if ok else ft.Icons.WARNING_AMBER_ROUNDED,
        dense=True,
    )


def permission_pill(permission: Permission) -> ft.Container:
    public = permission is Permission.PUBLIC
    return pill(
        permission.label,
        tone=Tone.INFO if public else Tone.NEUTRAL,
        icon=ft.Icons.PUBLIC if public else ft.Icons.LOCK,
        dense=True,
    )


def diff_text(insertions: int, deletions: int, *, size: int = 12) -> ft.Row:
    """git 约定：新增绿、删除红。"""
    return ft.Row(
        spacing=T.SPACE_SM,
        tight=True,
        controls=[
            T.text(
                f"+{format_count(insertions)}",
                level=T.TextLevel.LABEL,
                size=size,
                color=T.addition_color(),
                weight=ft.FontWeight.W_600,
            ),
            T.text(
                f"-{format_count(deletions)}",
                level=T.TextLevel.LABEL,
                size=size,
                color=T.deletion_color(),
                weight=ft.FontWeight.W_600,
            ),
        ],
    )


# --------------------------------------------------------------------------- 区块
def section(title_text: str, subtitle: str | None = None) -> ft.Column:
    """页内区块标题（标题 + 可选副标题）。"""
    controls: list[ft.Control] = [T.text(title_text, level=T.TextLevel.DISPLAY)]
    if subtitle:
        controls.append(muted(subtitle, size=13, max_lines=2))
    return ft.Column(spacing=T.SPACE_XS, tight=True, controls=controls)


def page_header(
    title_text: str,
    subtitle: str | None = None,
    *,
    actions: list[ft.Control] | None = None,
) -> ft.Row:
    """页面头部：左侧标题组，右侧动作区，两端对齐、随窗口自适应。"""
    return ft.Row(
        spacing=T.SPACE_LG,
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
    """页面骨架：统一边距、统一底色、统一模块间距。"""
    return ft.Container(
        expand=True,
        padding=T.PAGE_PADDING,
        bgcolor=T.SURFACE_COLOR,
        content=ft.Column(expand=True, spacing=T.SECTION_SPACING, controls=[header, body]),
    )


def hint_row(icon: str, text: str, *, tone: Tone = Tone.INFO) -> ft.Row:
    """一行"图标 + 说明"，用于提示、警告与错误。"""
    style = T.tone_style(tone)
    return ft.Row(
        spacing=T.SPACE_SM,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.Icon(icon, size=T.ICON_SM, color=style.accent),
            T.text(
                text,
                level=T.TextLevel.CAPTION,
                size=12,
                color=T.MUTED_TEXT,
                expand=True,
            ),
        ],
    )


def inline_error(message: str) -> ft.Row:
    """表单内的实时错误提示（主色加深 + 错误图标，不改变布局高度）。"""
    return hint_row(ft.Icons.ERROR_OUTLINE, message, tone=Tone.DANGER)


# --------------------------------------------------------------------------- 指标卡
def metric(
    label: str,
    value: str,
    *,
    tone: Tone = Tone.PRIMARY,
    icon: str | None = None,
    hint: str | None = None,
    col=None,
) -> ft.Container:
    """指标卡：图标色块承担语义色，数值用最高层级，整体保持"极简白卡"。"""
    style = T.tone_style(tone)
    return ft.Container(
        col=col or {"xs": 12, "sm": 6, "md": 4, "lg": 2},
        padding=T.SPACE_LG,
        border_radius=T.RADIUS_CARD,
        bgcolor=T.CARD_COLOR,
        border=ft.Border.all(1, T.BORDER_COLOR),
        shadow=T.card_shadow(),
        animate=T.animate(),
        content=ft.Column(
            spacing=T.SPACE_XS,
            tight=True,
            controls=[
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Container(
                            width=30,
                            height=30,
                            border_radius=T.RADIUS_SM,
                            bgcolor=style.container,
                            alignment=ft.Alignment.CENTER,
                            content=ft.Icon(icon or style.icon, size=16, color=style.accent),
                        ),
                        *(
                            [
                                T.text(
                                    hint,
                                    level=T.TextLevel.CAPTION,
                                    color=style.accent,
                                    weight=ft.FontWeight.W_500,
                                )
                            ]
                            if hint
                            else []
                        ),
                    ],
                ),
                T.text(
                    value,
                    level=T.TextLevel.DISPLAY,
                    size=24,
                    weight=ft.FontWeight.W_600,
                ),
                muted(label, size=12),
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
    """空状态：柔和的图标容器 + 标题 + 一句引导 + 可选主操作。"""
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
                    width=72,
                    height=72,
                    border_radius=T.RADIUS_XL,
                    bgcolor=T.PANEL_COLOR,
                    border=ft.Border.all(1, T.BORDER_COLOR),
                    alignment=ft.Alignment.CENTER,
                    content=ft.Icon(icon, size=32, color=T.MUTED_TEXT),
                ),
                T.text(title_text, level=T.TextLevel.TITLE, size=16),
                T.text(
                    hint,
                    level=T.TextLevel.BODY,
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
    """柔和加载动画：进度环 + 一行说明，用于"确实在忙"的整块占位。"""
    return ft.Container(
        expand=True,
        alignment=ft.Alignment.CENTER,
        content=ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=T.SPACE_MD,
            tight=True,
            controls=[
                ft.ProgressRing(width=28, height=28, stroke_width=3),
                muted(text, size=13),
            ],
        ),
    )


def _bar(width: int | None = None, *, height: int = 12, expand: bool = False) -> ft.Container:
    return ft.Container(
        width=width,
        height=height,
        expand=expand,
        border_radius=T.RADIUS_XS,
        bgcolor=T.CODE_COLOR,
    )


def skeleton_block(
    *,
    rows: int = 3,
    title: bool = True,
    text: str = "正在加载…",
) -> ft.Container:
    """骨架屏：用微光扫过的灰条替代空白等待，结构与应用卡片的节奏一致。"""
    placeholder = ft.Column(
        spacing=T.SPACE_MD,
        tight=True,
        controls=[
            _bar(180, height=16) if title else ft.Container(),
            *[
                ft.Row(
                    spacing=T.SPACE_MD,
                    controls=[
                        ft.Container(
                            width=32,
                            height=32,
                            border_radius=T.RADIUS_SM,
                            bgcolor=T.CODE_COLOR,
                        ),
                        ft.Column(
                            spacing=T.SPACE_SM,
                            tight=True,
                            expand=True,
                            controls=[_bar(expand=True), _bar(160)],
                        ),
                    ],
                )
                for _ in range(rows)
            ],
        ],
    )
    return ft.Container(
        expand=True,
        content=ft.Column(
            spacing=T.SPACE_LG,
            controls=[
                ft.Container(
                    padding=T.CARD_PADDING,
                    border_radius=T.RADIUS_CARD,
                    bgcolor=T.CARD_COLOR,
                    border=ft.Border.all(1, T.BORDER_COLOR),
                    content=ft.Shimmer(
                        base_color=ft.Colors.with_opacity(0.0, T.MUTED_TEXT),
                        highlight_color=ft.Colors.with_opacity(0.12, T.MUTED_TEXT),
                        period=1400,
                        content=placeholder,
                    ),
                ),
                ft.Row(
                    spacing=T.SPACE_SM,
                    alignment=ft.MainAxisAlignment.CENTER,
                    controls=[
                        ft.ProgressRing(width=14, height=14, stroke_width=2),
                        muted(text, size=12),
                    ],
                ),
            ],
        ),
    )


def skeleton_card(*, col=None, height: int = 168) -> ft.Container:
    """卡片骨架：与真实项目卡片同宽同高，首屏加载时布局不跳动。"""
    return ft.Container(
        col=col,
        height=height,
        padding=T.CARD_PADDING,
        border_radius=T.RADIUS_CARD,
        bgcolor=T.CARD_COLOR,
        border=ft.Border.all(1, T.BORDER_COLOR),
        content=ft.Shimmer(
            base_color=ft.Colors.with_opacity(0.0, T.MUTED_TEXT),
            highlight_color=ft.Colors.with_opacity(0.12, T.MUTED_TEXT),
            period=1400,
            content=ft.Column(
                spacing=T.SPACE_MD,
                tight=True,
                controls=[
                    ft.Row(
                        spacing=T.SPACE_MD,
                        controls=[
                            ft.Column(
                                spacing=T.SPACE_SM,
                                tight=True,
                                expand=True,
                                controls=[_bar(140, height=15), _bar(expand=True, height=10)],
                            ),
                            ft.Container(
                                width=44,
                                height=22,
                                border_radius=T.RADIUS_PILL,
                                bgcolor=T.CODE_COLOR,
                            ),
                        ],
                    ),
                    ft.Row(
                        spacing=T.SPACE_SM,
                        controls=[
                            ft.Container(
                                width=64,
                                height=20,
                                border_radius=T.RADIUS_PILL,
                                bgcolor=T.CODE_COLOR,
                            ),
                            ft.Container(
                                width=88,
                                height=20,
                                border_radius=T.RADIUS_PILL,
                                bgcolor=T.CODE_COLOR,
                            ),
                        ],
                    ),
                    ft.Container(height=1, bgcolor=T.BORDER_COLOR),
                    ft.Row(
                        spacing=T.SPACE_MD,
                        controls=[_bar(120, height=11), ft.Container(expand=True)],
                    ),
                ],
            ),
        ),
    )


def toast(page: ft.Page, message: str, *, tone: Tone = Tone.SUCCESS) -> None:
    """右下角浮动提示：固定深底 + 语义色图标，两套主题下都清晰可读。"""
    return page.show_dialog(
        ft.SnackBar(
            content=ft.Row(
                spacing=T.SPACE_MD,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Icon(T.tone_style(tone).icon, color=T.notify_accent(tone), size=19),
                    ft.Text(
                        message,
                        color=T.NOTIFY_TEXT,
                        size=13,
                        expand=True,
                        font_family=T.FONT_FAMILY,
                    ),
                ],
            ),
            bgcolor=T.NOTIFY_BG,
            behavior=ft.SnackBarBehavior.FLOATING,
            shape=ft.RoundedRectangleBorder(radius=T.RADIUS_MD),
            elevation=0,
            margin=ft.Margin.all(T.SPACE_LG),
            width=420,
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
    """确认框：标题 + 说明 + 可选补充面板 + "取消 / 危险确认"。"""
    return ft.AlertDialog(
        modal=True,
        bgcolor=T.CARD_COLOR,
        shape=ft.RoundedRectangleBorder(radius=T.RADIUS_DIALOG),
        title=T.text(
            title_text,
            level=T.TextLevel.TITLE,
            size=18,
            weight=ft.FontWeight.W_600,
        ),
        content=ft.Column(
            width=T.DIALOG_WIDTH,
            tight=True,
            spacing=T.SPACE_MD,
            controls=[
                T.text(message, level=T.TextLevel.BODY),
                *([extra] if extra else []),
            ],
        ),
        actions=[
            text_btn("取消", on_click=on_cancel),
            danger(confirm_label, on_click=on_confirm),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
