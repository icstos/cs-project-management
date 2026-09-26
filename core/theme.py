"""设计令牌与全局主题。

间距、圆角、语义色只在这里定义一次，界面层统一从 ``views.ui`` 取用，
避免魔法数字散落各处；主题对象由 ``main.py`` 挂到 ``page.theme``。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import flet as ft

from core.config import FONT_FAMILY

# --------------------------------------------------------------------------- 间距
SPACE_XXS = 2
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24
SPACE_XXL = 32

PAGE_PADDING = SPACE_XL
CARD_PADDING = SPACE_LG
SECTION_SPACING = SPACE_XL
FIELD_GAP = SPACE_MD

# --------------------------------------------------------------------------- 圆角
RADIUS_SM = 8
RADIUS_MD = 10
RADIUS_LG = 14
RADIUS_XL = 18
RADIUS_PILL = 999

# --------------------------------------------------------------------------- 尺寸
SIDEBAR_WIDTH = 92
DIALOG_WIDTH = 480
STAT_MIN_HEIGHT = 96
LIST_MAX_HEIGHT = 220
CHART_HEIGHT = 240

# --------------------------------------------------------------------------- 颜色
ADDITION_COLOR = ft.Colors.GREEN_700
DELETION_COLOR = ft.Colors.RED_700
BORDER_COLOR = ft.Colors.OUTLINE_VARIANT
SURFACE_COLOR = ft.Colors.SURFACE
SHELL_COLOR = ft.Colors.SURFACE_CONTAINER_LOW
MUTED_TEXT = ft.Colors.ON_SURFACE_VARIANT

CARD_SHADOW = ft.BoxShadow(
    spread_radius=0,
    blur_radius=14,
    color=ft.Colors.with_opacity(0.06, ft.Colors.BLACK),
    offset=ft.Offset(0, 4),
)


class Tone(StrEnum):
    """语义色角色。界面只描述意图，不直接挑颜色。"""

    PRIMARY = "primary"
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    DANGER = "danger"
    NEUTRAL = "neutral"


@dataclass(frozen=True, slots=True)
class ToneStyle:
    accent: ft.ColorValue
    container: ft.ColorValue
    on_container: ft.ColorValue
    icon: str


TONES: dict[Tone, ToneStyle] = {
    Tone.PRIMARY: ToneStyle(
        accent=ft.Colors.PRIMARY,
        container=ft.Colors.PRIMARY_CONTAINER,
        on_container=ft.Colors.ON_PRIMARY_CONTAINER,
        icon=ft.Icons.BOLT,
    ),
    Tone.INFO: ToneStyle(
        accent=ft.Colors.BLUE_600,
        container=ft.Colors.BLUE_50,
        on_container=ft.Colors.BLUE_900,
        icon=ft.Icons.INFO_OUTLINE,
    ),
    Tone.SUCCESS: ToneStyle(
        accent=ft.Colors.GREEN_700,
        container=ft.Colors.GREEN_50,
        on_container=ft.Colors.GREEN_900,
        icon=ft.Icons.CHECK_CIRCLE_OUTLINE,
    ),
    Tone.WARNING: ToneStyle(
        accent=ft.Colors.AMBER_800,
        container=ft.Colors.AMBER_50,
        on_container=ft.Colors.AMBER_900,
        icon=ft.Icons.WARNING_AMBER_ROUNDED,
    ),
    Tone.DANGER: ToneStyle(
        accent=ft.Colors.RED_700,
        container=ft.Colors.RED_50,
        on_container=ft.Colors.RED_900,
        icon=ft.Icons.ERROR_OUTLINE,
    ),
    Tone.NEUTRAL: ToneStyle(
        accent=ft.Colors.BLUE_GREY_600,
        container=ft.Colors.BLUE_GREY_50,
        on_container=ft.Colors.BLUE_GREY_900,
        icon=ft.Icons.CIRCLE_OUTLINED,
    ),
}


def tone_style(tone: Tone) -> ToneStyle:
    """取语义色样式，未登记时回退中性色。"""
    return TONES.get(tone, TONES[Tone.NEUTRAL])


# --------------------------------------------------------------------------- 主题
def text_style(
    size: int,
    *,
    weight: ft.FontWeight | None = None,
    color: ft.ColorValue | None = None,
) -> ft.TextStyle:
    """构造带应用字体的文本样式。

    ``Theme.font_family`` 只兜得住"没有显式样式"的文本；而 Material 各处的
    ``*_text_style``（NavigationRail 标签、DataTable、Chip、Dropdown、Tooltip…）
    在客户端是**整体替换**默认文本样式而非 merge，显式构造的 ``TextStyle``
    一旦漏掉 ``font_family``，该处就会悄悄退回系统默认字体。因此所有显式文本
    样式统一从这里出，字体不会漏。
    """
    return ft.TextStyle(
        size=size,
        weight=weight,
        color=color,
        font_family=FONT_FAMILY,
    )


def _button_style(
    *,
    radius: int = RADIUS_MD,
    horizontal: int = 18,
    vertical: int = 12,
    side: ft.BorderSide | None = None,
) -> ft.ButtonStyle:
    return ft.ButtonStyle(
        shape=ft.RoundedRectangleBorder(radius=radius),
        padding=ft.Padding.symmetric(horizontal=horizontal, vertical=vertical),
        side=side,
    )


def field_border(radius: int = RADIUS_MD) -> dict[ft.ControlState, ft.OutlineInputBorder]:
    """输入类控件（TextField / Dropdown）的圆角描边。

    Flet 1.0 起 ``TextField.border_radius`` 与 ``Dropdown.border_radius`` 已废弃，
    统一改为显式的 ``OutlineInputBorder``：默认使用细分隔线色，聚焦时换成主色，
    既消除了废弃告警，也把聚焦反馈固定下来。
    """
    return {
        ft.ControlState.FOCUSED: ft.OutlineInputBorder(
            border_radius=radius,
            side=ft.BorderSide(2, ft.Colors.PRIMARY),
        ),
        ft.ControlState.DEFAULT: ft.OutlineInputBorder(
            border_radius=radius,
            side=ft.BorderSide(1, BORDER_COLOR),
        ),
    }


def build_theme() -> ft.Theme:
    """构建 Material 3 浅色主题。

    全局字体在 ``font_family`` 上指定一次，覆盖所有未显式声明样式的文本；
    显式声明样式的部件由 :func:`text_style` 统一补齐。
    """
    return ft.Theme(
        color_scheme_seed=ft.Colors.INDIGO,
        font_family=FONT_FAMILY,
        use_material3=True,
        visual_density=ft.VisualDensity.COMFORTABLE,
        card_theme=ft.CardTheme(
            elevation=0,
            margin=0,
            color=ft.Colors.SURFACE_CONTAINER_LOW,
            shape=ft.RoundedRectangleBorder(radius=RADIUS_LG),
        ),
        dialog_theme=ft.DialogTheme(
            shape=ft.RoundedRectangleBorder(radius=RADIUS_XL),
            elevation=2,
        ),
        filled_button_theme=ft.FilledButtonTheme(style=_button_style()),
        outlined_button_theme=ft.OutlinedButtonTheme(
            style=_button_style(side=ft.BorderSide(1, BORDER_COLOR))
        ),
        text_button_theme=ft.TextButtonTheme(
            style=_button_style(radius=RADIUS_SM, horizontal=14, vertical=10)
        ),
        icon_button_theme=ft.IconButtonTheme(
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=RADIUS_SM))
        ),
        navigation_rail_theme=ft.NavigationRailTheme(
            bgcolor=ft.Colors.TRANSPARENT,
            indicator_color=ft.Colors.PRIMARY_CONTAINER,
            indicator_shape=ft.RoundedRectangleBorder(radius=RADIUS_MD),
            label_type=ft.NavigationRailLabelType.ALL,
            selected_label_text_style=text_style(
                12, weight=ft.FontWeight.W_600, color=ft.Colors.ON_SURFACE
            ),
            unselected_label_text_style=text_style(12, color=MUTED_TEXT),
        ),
        snackbar_theme=ft.SnackBarTheme(
            behavior=ft.SnackBarBehavior.FLOATING,
            shape=ft.RoundedRectangleBorder(radius=RADIUS_MD),
            elevation=2,
        ),
        data_table_theme=ft.DataTableTheme(
            heading_row_color=ft.Colors.SURFACE_CONTAINER_HIGH,
            heading_text_style=text_style(13, weight=ft.FontWeight.W_600, color=MUTED_TEXT),
            data_text_style=text_style(13),
            divider_thickness=1,
        ),
        chip_theme=ft.ChipTheme(
            shape=ft.RoundedRectangleBorder(radius=RADIUS_PILL),
            padding=ft.Padding.symmetric(horizontal=10, vertical=2),
            label_text_style=text_style(12, weight=ft.FontWeight.W_500),
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
            border_side=ft.BorderSide(1, BORDER_COLOR),
        ),
        dropdown_theme=ft.DropdownTheme(
            text_style=text_style(14),
            menu_style=ft.MenuStyle(
                bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
                shape=ft.RoundedRectangleBorder(radius=RADIUS_MD),
                elevation=4,
            ),
        ),
        list_tile_theme=ft.ListTileTheme(
            shape=ft.RoundedRectangleBorder(radius=RADIUS_MD),
        ),
        divider_theme=ft.DividerTheme(color=BORDER_COLOR, thickness=1),
        tooltip_theme=ft.TooltipTheme(
            wait_duration=ft.Duration(milliseconds=400),
            text_style=text_style(12),
        ),
        progress_indicator_theme=ft.ProgressIndicatorTheme(
            color=ft.Colors.PRIMARY,
            linear_track_color=ft.Colors.with_opacity(0.12, ft.Colors.PRIMARY),
        ),
    )
