"""设计令牌（Design Tokens）与全局主题。

本模块是整个界面**唯一的视觉真源**：间距、圆角、字体层级、语义色、阴影与
组件样式只在这里定义一次，各视图 ``from view import design as T`` 取用，
因此不会出现"同一个间距在十个文件里有十个值"的漂移。

三条约定：

1. **颜色只写语义角色，不写死色值。** 组件使用 ``ft.Colors.SURFACE`` /
   :class:`ToneStyle` 这类"意图"，由浅色 / 深色两套 ``ColorScheme`` 决定最终色值，
   于是深浅色模式共用同一套界面代码，不需要各自维护样式表。
2. **明暗亮度由 :func:`set_dark` 同步。** Material 的角色色在客户端按当前亮度
   解析，而 :func:`tone_style` 是 Python 侧查表，必须知道当前亮度；应用外壳
   每次渲染都会先调用 :func:`set_dark`，保证整棵树取到同一套色板。
3. **字体只有一个来源。** 全局字体是 ``models.settings.FONT_FAMILY``；任何显式
   ``TextStyle`` 都必须由 :func:`text_style` / :func:`text` 产生 —— Material 各处
   的 ``*_text_style`` 是**整体替换**而非 merge，漏一处该处就静默回退系统字体。
4. **显式给了 ``style`` 就必须显式给 ``color``。** 客户端一旦收到 ``style`` 就不再
   继承主题文字色，``color`` 为空会渲染成白色（浅色主题下等于隐形）。:func:`text`
   已经兜底为 ``onSurface``；手写 ``ft.Text(style=...)`` 时务必自己带上颜色。

令牌索引：

======================  ==================================================
栅格与间距               :data:`GRID_COLUMNS` :data:`PAGE_PADDING` :data:`GRID_GUTTER`
圆角                     ``RADIUS_*``（按钮 10 / 输入 8 / 卡片 14 / 对话框 18）
字体层级                 :class:`TextLevel` :func:`text` :func:`text_style`
配色                     :data:`LIGHT_SCHEME` :data:`DARK_SCHEME` :func:`tone_style`
阴影                     :func:`card_shadow` :func:`floating_shadow`
主题                     :func:`build_theme` :func:`build_dark_theme`
======================  ==================================================
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import flet as ft

from models.enums import Tone
from models.settings import FONT_FAMILY

# =========================================================================== 栅格与间距
#: 12 列栅格：``ResponsiveRow`` 的 ``col`` 取值以它为准（12 / 6 / 4 / 3 / 2）。
GRID_COLUMNS = 12

SPACE_XXS = 2
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24
SPACE_XXL = 32
SPACE_3XL = 40

#: 页面边距 24px —— 内容区与窗口边缘的呼吸空间
PAGE_PADDING = SPACE_XL
#: 模块（页头 / 工具栏 / 内容块）之间的纵向间距
SECTION_SPACING = SPACE_XL
#: 栅格间距：卡片与卡片之间
GRID_GUTTER = SPACE_LG
#: 卡片内边距
CARD_PADDING = SPACE_LG
#: 表单字段之间的间距
FIELD_GAP = SPACE_MD

# =========================================================================== 圆角
RADIUS_XS = 6
RADIUS_SM = 8
RADIUS_MD = 10
RADIUS_LG = 14
RADIUS_XL = 18
RADIUS_PILL = 999

RADIUS_INPUT = RADIUS_SM  # 输入框 / 选择器：8px
RADIUS_BUTTON = RADIUS_MD  # 按钮：10px
RADIUS_CARD = RADIUS_LG  # 卡片：14px
RADIUS_DIALOG = RADIUS_XL  # 对话框：18px

# =========================================================================== 尺寸
SIDEBAR_WIDTH = 96
DIALOG_WIDTH = 480
LIST_MAX_HEIGHT = 220
CHART_HEIGHT = 240
STATUS_BAR_HEIGHT = 40

ICON_SM = 15
ICON_MD = 18
ICON_LG = 22

#: 统一过渡时长（150-300ms，ease 曲线）
DURATION_FAST = 150
DURATION_BASE = 200
DURATION_SLOW = 280


# =========================================================================== 字体层级
class TextLevel(StrEnum):
    """五级字体层级：大标题 / 小标题 / 正文 / 辅助文字 / 说明文字。"""

    DISPLAY = "display"
    TITLE = "title"
    BODY = "body"
    LABEL = "label"
    CAPTION = "caption"


@dataclass(frozen=True, slots=True)
class _Level:
    """一级文字的字号 / 字重 / 行高 / 字距。"""

    size: int
    weight: ft.FontWeight
    height: float
    spacing: float = 0.0


LEVELS: dict[TextLevel, _Level] = {
    # 大标题：页面主标题，字重 600 撑起层级
    TextLevel.DISPLAY: _Level(22, ft.FontWeight.W_600, 1.30, -0.30),
    # 小标题：卡片 / 区块标题
    TextLevel.TITLE: _Level(15, ft.FontWeight.W_600, 1.40, -0.10),
    # 正文：行高 1.55，中英混排舒适
    TextLevel.BODY: _Level(13, ft.FontWeight.W_400, 1.55),
    # 辅助文字：标签、徽标、行内次要信息
    TextLevel.LABEL: _Level(12, ft.FontWeight.W_500, 1.45),
    # 说明文字：最小一级，用于路径、快捷键、脚注
    TextLevel.CAPTION: _Level(11, ft.FontWeight.W_400, 1.40, 0.10),
}


def text_style(
    size: int,
    *,
    weight: ft.FontWeight | None = None,
    color: ft.ColorValue | None = None,
    height: float | None = None,
) -> ft.TextStyle:
    """构造带应用字体的文本样式。

    Material 各处的 ``*_text_style``（NavigationRail 标签、DataTable、Chip、
    Dropdown、Tooltip…）在客户端是**整体替换**默认文本样式而非 merge，显式构造的
    ``TextStyle`` 一旦漏掉 ``font_family``，该处就会悄悄退回系统字体。
    因此所有显式文本样式统一从这里出，字体不会漏。
    """
    return ft.TextStyle(
        size=size,
        weight=weight,
        color=color,
        height=height,
        font_family=FONT_FAMILY,
    )


def text(
    value: str,
    *,
    level: TextLevel = TextLevel.BODY,
    color: ft.ColorValue | None = None,
    weight: ft.FontWeight | None = None,
    size: int | None = None,
    **kwargs: object,
) -> ft.Text:
    """按五级层级构造文本：字号 / 字重 / 行高 / 字距由层级统一决定。

    ``color`` 留空时沿用主题的 ``onSurface``；``weight`` / ``size`` 只在少数
    "同级但要再强调一下"的场合覆盖。
    """
    base = LEVELS[level]
    return ft.Text(  # type: ignore[arg-type]
        value,
        size=size or base.size,
        weight=weight or base.weight,
        # ⚠️ 实测（flet 1.0.4）：一旦给 Text 传了 style，客户端不再继承主题文字色，
        #    缺省色会落到白色 —— 浅色主题下就是"看不见的字"。所以这里必须兜底。
        color=color or ft.Colors.ON_SURFACE,
        font_family=FONT_FAMILY,
        style=ft.TextStyle(height=base.height, letter_spacing=base.spacing),
        **kwargs,
    )


# =========================================================================== 色板
# 主色选低饱和靛蓝（稳重、久看不累），辅色取石板灰蓝与青绿，
# 中性色是带一点点冷调的灰阶 —— 冷调中性色比纯灰更"干净"。
LIGHT_SCHEME = ft.ColorScheme(
    primary="#4356C7",
    on_primary="#FFFFFF",
    primary_container="#E6E9FB",
    on_primary_container="#1A2260",
    secondary="#5B6478",
    on_secondary="#FFFFFF",
    secondary_container="#E9ECF3",
    on_secondary_container="#262C3A",
    tertiary="#0E7C6B",
    on_tertiary="#FFFFFF",
    tertiary_container="#DAF1EC",
    on_tertiary_container="#0A3F36",
    error="#B3261E",
    on_error="#FFFFFF",
    error_container="#FCE9E7",
    on_error_container="#601410",
    surface="#F5F6F9",
    on_surface="#1A1C22",
    on_surface_variant="#5C6373",
    outline="#8C93A3",
    outline_variant="#E3E6EE",
    shadow="#0B0E14",
    scrim="#000000",
    inverse_surface="#2F323A",
    on_inverse_surface="#EFF0F4",
    inverse_primary="#B9C2F7",
    surface_tint="#4356C7",
    surface_dim="#F5F6F9",
    surface_bright="#FFFFFF",
    surface_container_lowest="#FFFFFF",
    surface_container_low="#FFFFFF",
    surface_container="#EFF1F6",
    surface_container_high="#E8EBF2",
    surface_container_highest="#E1E5EE",
)

DARK_SCHEME = ft.ColorScheme(
    primary="#A9B6F7",
    on_primary="#16205E",
    primary_container="#2E3A82",
    on_primary_container="#DDE3FF",
    secondary="#B3BACB",
    on_secondary="#262C3A",
    secondary_container="#3A4053",
    on_secondary_container="#E2E6F0",
    tertiary="#63D2BC",
    on_tertiary="#00382F",
    tertiary_container="#0E5248",
    on_tertiary_container="#C9F3E8",
    error="#FFB4AB",
    on_error="#690005",
    error_container="#8C1D18",
    on_error_container="#FFDAD6",
    surface="#101216",
    on_surface="#E5E7ED",
    on_surface_variant="#A6ADBC",
    outline="#6E7687",
    outline_variant="#282C35",
    shadow="#000000",
    scrim="#000000",
    inverse_surface="#E5E7ED",
    on_inverse_surface="#2F323A",
    inverse_primary="#4356C7",
    surface_tint="#A9B6F7",
    surface_dim="#101216",
    surface_bright="#363B45",
    surface_container_lowest="#0B0D11",
    surface_container_low="#171A20",
    surface_container="#1C2028",
    surface_container_high="#262B34",
    surface_container_highest="#323844",
)

# --------------------------------------------------------------------------- 语义角色
#: 卡片底色：浅色下是"浮在灰底上的白"，深色下是"比页面亮一档的灰"。
CARD_COLOR: ft.ColorValue = ft.Colors.SURFACE_CONTAINER_LOW
#: 页面底色
SURFACE_COLOR: ft.ColorValue = ft.Colors.SURFACE
#: 侧栏 / 状态栏底色（与页面同色，靠分隔线划分，追求通透）
SHELL_COLOR: ft.ColorValue = ft.Colors.SURFACE
#: 次级信息文字
MUTED_TEXT: ft.ColorValue = ft.Colors.ON_SURFACE_VARIANT
#: 发丝级分隔线 / 卡片描边
BORDER_COLOR: ft.ColorValue = ft.Colors.OUTLINE_VARIANT
#: 强调描边（需要更清晰边界时）
STRONG_BORDER: ft.ColorValue = ft.Colors.OUTLINE
#: 低对比信息面板底色
PANEL_COLOR: ft.ColorValue = ft.Colors.SURFACE_CONTAINER
#: 代码 / 控制台底色
CODE_COLOR: ft.ColorValue = ft.Colors.SURFACE_CONTAINER_HIGH

#: 终端面板固定使用深底（不随主题切换）：日志这类"原始输出"用深色底更像控制台，
#: 也与周围的浅色卡片形成目的性对比，一眼就能区分"界面"与"机器输出"。
CONSOLE_BG: ft.ColorValue = "#141821"
CONSOLE_TEXT: ft.ColorValue = "#C6CDDB"
CONSOLE_DIM: ft.ColorValue = "#7C879C"

_DARK = False


@dataclass(frozen=True, slots=True)
class ToneStyle:
    """一个语义角色对应的三档颜色与图标。

    ``accent`` 用于图标与强调文字，``container`` 用于底色，``on_container``
    用于落在 container 上的文字 —— 三者的对比度都按 WCAG AA（4.5:1）挑选。
    """

    accent: ft.ColorValue
    container: ft.ColorValue
    on_container: ft.ColorValue
    icon: str


def _tone(
    accent: str,
    container: str,
    on_container: str,
    icon: str,
) -> ToneStyle:
    return ToneStyle(accent=accent, container=container, on_container=on_container, icon=icon)


_LIGHT_TONES: dict[Tone, ToneStyle] = {}
_DARK_TONES: dict[Tone, ToneStyle] = {}

_LIGHT_TONES.update(
    {
        Tone.PRIMARY: _tone(LIGHT_SCHEME.primary, "#E6E9FB", "#1A2260", ft.Icons.BOLT),
        Tone.INFO: _tone("#2F6FB5", "#E6F0FA", "#10395E", ft.Icons.INFO_OUTLINE),
        Tone.SUCCESS: _tone("#1F7A54", "#E2F4EA", "#0C4A32", ft.Icons.CHECK_CIRCLE_OUTLINE),
        Tone.WARNING: _tone("#96690C", "#FBF0D9", "#5C3D00", ft.Icons.WARNING_AMBER_ROUNDED),
        Tone.DANGER: _tone("#B3261E", "#FCE9E7", "#601410", ft.Icons.ERROR_OUTLINE),
        Tone.NEUTRAL: _tone("#5C6373", "#EEF0F4", "#2B2F3A", ft.Icons.CIRCLE_OUTLINED),
    }
)

_DARK_TONES.update(
    {
        Tone.PRIMARY: _tone("#A9B6F7", "#262F63", "#DDE3FF", ft.Icons.BOLT),
        Tone.INFO: _tone("#7FB6F0", "#17324B", "#CFE4FA", ft.Icons.INFO_OUTLINE),
        Tone.SUCCESS: _tone("#6ED8A8", "#123A2B", "#C9F2DE", ft.Icons.CHECK_CIRCLE_OUTLINE),
        Tone.WARNING: _tone("#E9BE6A", "#43330C", "#F7E3B8", ft.Icons.WARNING_AMBER_ROUNDED),
        Tone.DANGER: _tone("#FFB4AB", "#5C1B16", "#FFDAD6", ft.Icons.ERROR_OUTLINE),
        Tone.NEUTRAL: _tone("#B3BACB", "#272B33", "#E1E4EB", ft.Icons.CIRCLE_OUTLINED),
    }
)


def set_dark(value: bool) -> None:
    """同步"当前是深色还是浅色"。应用外壳每次渲染都会调用一次。"""
    global _DARK
    _DARK = bool(value)


def is_dark() -> bool:
    """当前是否为深色模式。"""
    return _DARK


def tone_style(tone: Tone) -> ToneStyle:
    """取语义色样式，未登记时回退中性色。"""
    palette = _DARK_TONES if _DARK else _LIGHT_TONES
    return palette.get(tone, palette[Tone.NEUTRAL])


def addition_color() -> ft.ColorValue:
    """git 约定：新增用绿，深色下提亮以保证对比度。"""
    return "#6ED8A8" if _DARK else "#1F7A54"


def deletion_color() -> ft.ColorValue:
    """git 约定：删除用红，深色下提亮以保证对比度。"""
    return "#FF9B90" if _DARK else "#C0392B"


def brand_gradient() -> ft.LinearGradient:
    """品牌标识的微渐变：低饱和双色，只在 Logo 这种小面积上使用。"""
    colors = ["#3E4EA8", "#6D7BE0"] if _DARK else ["#4356C7", "#6A78E4"]
    return ft.LinearGradient(
        begin=ft.Alignment.TOP_LEFT,
        end=ft.Alignment.BOTTOM_RIGHT,
        colors=colors,
    )


# --------------------------------------------------------------------------- 浮层提示
#: 浮动提示（SnackBar）固定使用深底：两套主题下都能与语义色图标形成足够对比。
NOTIFY_BG: ft.ColorValue = "#22262E"
NOTIFY_TEXT: ft.ColorValue = "#F2F3F7"

#: 深底之上的"亮色版"语义色（与深色主题的 accent 同源）
_NOTIFY_ACCENT: dict[Tone, str] = {
    Tone.PRIMARY: "#A9B6F7",
    Tone.INFO: "#7FB6F0",
    Tone.SUCCESS: "#6ED8A8",
    Tone.WARNING: "#E9BE6A",
    Tone.DANGER: "#FFB4AB",
    Tone.NEUTRAL: "#B3BACB",
}


def notify_accent(tone: Tone) -> ft.ColorValue:
    """浮层图标色：不随明暗变化，保证落在深底上仍然清晰。"""
    return _NOTIFY_ACCENT.get(tone, _NOTIFY_ACCENT[Tone.NEUTRAL])


# =========================================================================== 阴影
def _lift(offset_y: int, blur: int, opacity: float) -> ft.BoxShadow:
    return ft.BoxShadow(
        spread_radius=0,
        blur_radius=blur,
        color=ft.Colors.with_opacity(opacity, "#0B0E14"),
        offset=ft.Offset(0, offset_y),
    )


def card_shadow(*, hover: bool = False) -> ft.BoxShadow:
    """卡片投影：极淡、向下的柔和阴影；悬停时轻微加深。"""
    if _DARK:
        return _lift(6 if hover else 3, 20 if hover else 12, 0.45 if hover else 0.30)
    return _lift(6 if hover else 3, 20 if hover else 12, 0.10 if hover else 0.05)


def floating_shadow() -> ft.BoxShadow:
    """浮层（对话框 / 菜单 / Toast）投影。"""
    return _lift(12, 32, 0.45 if _DARK else 0.16)


def pressed_shadow() -> ft.BoxShadow:
    """按下时的投影：比静止态更贴地，制造"被按下去"的反馈。"""
    return _lift(1, 6, 0.22 if _DARK else 0.06)


# =========================================================================== 状态反馈
def animate(*, duration: int = DURATION_BASE) -> ft.Animation:
    """统一的隐式过渡：150-300ms + ease-out。"""
    return ft.Animation(duration=duration, curve=ft.AnimationCurve.EASE_OUT)


def field_border(radius: int = RADIUS_INPUT) -> dict[ft.ControlState, ft.OutlineInputBorder]:
    """输入类控件（TextField / Dropdown）的圆角描边。

    默认态是 1px 发丝线，聚焦态换成 2px 主色 —— 聚焦反馈固定下来。
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


# =========================================================================== 组件样式
def _button_shape(radius: int = RADIUS_BUTTON) -> ft.RoundedRectangleBorder:
    return ft.RoundedRectangleBorder(radius=radius)


def _button_states(dark: bool) -> dict[str, object]:
    """按钮共用的状态字典（颜色 / 投影随状态变化，过渡 180ms）。"""
    return {
        "elevation": {
            ft.ControlState.DEFAULT: 0,
            ft.ControlState.HOVERED: 1,
            ft.ControlState.PRESSED: 0,
            ft.ControlState.DISABLED: 0,
        },
        "shadow_color": ft.Colors.with_opacity(0.35 if dark else 0.22, "#0B0E14"),
        "animation_duration": ft.Duration(milliseconds=DURATION_BASE),
        "mouse_cursor": ft.MouseCursor.CLICK,
    }


def _filled_style(dark: bool) -> ft.ButtonStyle:
    return ft.ButtonStyle(
        shape=_button_shape(),
        padding=ft.Padding.symmetric(horizontal=18, vertical=12),
        bgcolor={
            ft.ControlState.DISABLED: ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
        },
        color={
            ft.ControlState.DISABLED: ft.Colors.with_opacity(0.38, ft.Colors.ON_SURFACE),
        },
        overlay_color=ft.Colors.with_opacity(0.12, ft.Colors.ON_PRIMARY),
        **_button_states(dark),  # type: ignore[arg-type]
    )


def _outlined_style(dark: bool) -> ft.ButtonStyle:
    return ft.ButtonStyle(
        shape=_button_shape(),
        padding=ft.Padding.symmetric(horizontal=18, vertical=12),
        side={
            ft.ControlState.DEFAULT: ft.BorderSide(1, BORDER_COLOR),
            ft.ControlState.HOVERED: ft.BorderSide(1, ft.Colors.PRIMARY),
            ft.ControlState.DISABLED: ft.BorderSide(
                1, ft.Colors.with_opacity(0.24, ft.Colors.ON_SURFACE)
            ),
        },
        color={
            ft.ControlState.DEFAULT: ft.Colors.ON_SURFACE,
            ft.ControlState.HOVERED: ft.Colors.PRIMARY,
            ft.ControlState.DISABLED: ft.Colors.with_opacity(0.38, ft.Colors.ON_SURFACE),
        },
        overlay_color=ft.Colors.with_opacity(0.06, ft.Colors.PRIMARY),
        **_button_states(dark),  # type: ignore[arg-type]
    )


def _text_style(dark: bool) -> ft.ButtonStyle:
    return ft.ButtonStyle(
        shape=_button_shape(RADIUS_SM),
        padding=ft.Padding.symmetric(horizontal=14, vertical=10),
        color={
            ft.ControlState.DEFAULT: ft.Colors.PRIMARY,
            ft.ControlState.DISABLED: ft.Colors.with_opacity(0.38, ft.Colors.ON_SURFACE),
        },
        overlay_color=ft.Colors.with_opacity(0.08, ft.Colors.PRIMARY),
        animation_duration=ft.Duration(milliseconds=DURATION_FAST),
        mouse_cursor=ft.MouseCursor.CLICK,
    )


def _icon_button_style() -> ft.ButtonStyle:
    return ft.ButtonStyle(
        shape=_button_shape(RADIUS_SM),
        padding=8,
        overlay_color=ft.Colors.with_opacity(0.10, ft.Colors.PRIMARY),
        animation_duration=ft.Duration(milliseconds=DURATION_FAST),
        mouse_cursor=ft.MouseCursor.CLICK,
    )


# =========================================================================== 主题
def _build_theme(*, dark: bool) -> ft.Theme:
    """浅色 / 深色共用一套结构，只有色板与个别透明度不同。"""
    scheme = DARK_SCHEME if dark else LIGHT_SCHEME
    on_surface = scheme.on_surface
    muted = scheme.on_surface_variant

    # ⚠️ 实测（flet 1.0.4）：NavigationRail / Chip / TextField 的若干外观字段
    #    不会从这个 Theme 里取（客户端有自己的默认值），所以这些控件的外观一律
    #    在控件上显式指定（见 view/app.py、view/widgets.filter_chip）。这里的
    #    theme 只负责"控件没显式指定时"的兜底。
    return ft.Theme(
        color_scheme=scheme,
        font_family=FONT_FAMILY,
        use_material3=True,
        visual_density=ft.VisualDensity.COMFORTABLE,
        # ---- 文字层级：让"没显式写样式"的文本也落在统一的行高上
        text_theme=ft.TextTheme(
            body_large=text_style(15, color=on_surface, height=1.5),
            body_medium=text_style(13, color=on_surface, height=1.55),
            body_small=text_style(12, color=on_surface, height=1.5),
            title_large=text_style(20, weight=ft.FontWeight.W_600, color=on_surface, height=1.3),
            title_medium=text_style(16, weight=ft.FontWeight.W_600, color=on_surface, height=1.35),
            title_small=text_style(14, weight=ft.FontWeight.W_600, color=on_surface, height=1.4),
            label_large=text_style(13, weight=ft.FontWeight.W_500, color=on_surface, height=1.4),
            label_medium=text_style(12, weight=ft.FontWeight.W_500, color=muted, height=1.4),
            label_small=text_style(11, weight=ft.FontWeight.W_500, color=muted, height=1.35),
            headline_small=text_style(
                24, weight=ft.FontWeight.W_600, color=on_surface, height=1.25
            ),
            headline_medium=text_style(
                28, weight=ft.FontWeight.W_600, color=on_surface, height=1.25
            ),
        ),
        # ---- 卡片：极淡填充 + 超细边框 + 柔和投影
        card_theme=ft.CardTheme(
            elevation=0,
            margin=0,
            color=CARD_COLOR,
            shadow_color=ft.Colors.with_opacity(0.1, "#0B0E14"),
            shape=ft.RoundedRectangleBorder(radius=RADIUS_CARD),
        ),
        dialog_theme=ft.DialogTheme(
            bgcolor=CARD_COLOR,
            shape=ft.RoundedRectangleBorder(radius=RADIUS_DIALOG),
            elevation=0,
            shadow_color=ft.Colors.with_opacity(0.4 if dark else 0.16, "#0B0E14"),
            title_text_style=text_style(
                18, weight=ft.FontWeight.W_600, color=on_surface, height=1.35
            ),
            content_text_style=text_style(13, color=on_surface, height=1.55),
            actions_padding=ft.Padding.symmetric(horizontal=SPACE_XL, vertical=SPACE_MD),
            inset_padding=ft.Padding.symmetric(horizontal=SPACE_XL, vertical=SPACE_XL),
        ),
        # ---- 按钮：三态齐备，过渡 200ms
        filled_button_theme=ft.FilledButtonTheme(style=_filled_style(dark)),
        outlined_button_theme=ft.OutlinedButtonTheme(style=_outlined_style(dark)),
        text_button_theme=ft.TextButtonTheme(style=_text_style(dark)),
        icon_button_theme=ft.IconButtonTheme(style=_icon_button_style()),
        button_theme=ft.ButtonTheme(style=_filled_style(dark)),
        # ---- 导航栏：只靠圆角指示块标识选中项，保持通透
        navigation_rail_theme=ft.NavigationRailTheme(
            bgcolor=ft.Colors.TRANSPARENT,
            indicator_color=ft.Colors.PRIMARY_CONTAINER,
            indicator_shape=ft.RoundedRectangleBorder(radius=RADIUS_MD),
            elevation=0,
            label_type=ft.NavigationRailLabelType.ALL,
            selected_label_text_style=text_style(
                11, weight=ft.FontWeight.W_600, color=ft.Colors.ON_PRIMARY_CONTAINER
            ),
            unselected_label_text_style=text_style(11, weight=ft.FontWeight.W_500, color=muted),
        ),
        # ---- 浮层：圆角 12、浮起投影
        snackbar_theme=ft.SnackBarTheme(
            behavior=ft.SnackBarBehavior.FLOATING,
            shape=ft.RoundedRectangleBorder(radius=RADIUS_MD),
            elevation=0,
            inset_padding=ft.Padding.all(SPACE_LG),
            content_text_style=text_style(13, color=ft.Colors.ON_INVERSE_SURFACE),
        ),
        popup_menu_theme=ft.PopupMenuTheme(
            shape=ft.RoundedRectangleBorder(radius=RADIUS_MD),
            elevation=8,
            shadow_color=ft.Colors.with_opacity(0.4 if dark else 0.14, "#0B0E14"),
            color=CARD_COLOR,
            mouse_cursor=ft.MouseCursor.CLICK,
            label_text_style=text_style(13, color=on_surface),
        ),
        tooltip_theme=ft.TooltipTheme(
            wait_duration=ft.Duration(milliseconds=400),
            text_style=text_style(12, color=ft.Colors.ON_INVERSE_SURFACE),
            padding=ft.Padding.symmetric(horizontal=SPACE_SM, vertical=SPACE_XS),
            decoration=ft.BoxDecoration(
                bgcolor=ft.Colors.INVERSE_SURFACE,
                border_radius=RADIUS_XS,
            ),
        ),
        # ---- 数据表格：表头弱底、行高舒展
        data_table_theme=ft.DataTableTheme(
            heading_row_color=ft.Colors.with_opacity(0.04, ft.Colors.ON_SURFACE),
            heading_row_height=44,
            heading_text_style=text_style(12, weight=ft.FontWeight.W_600, color=muted),
            data_text_style=text_style(12, color=on_surface, height=1.4),
            data_row_min_height=44,
            data_row_max_height=52,
            divider_thickness=1,
            heading_cell_cursor=ft.MouseCursor.CLICK,
        ),
        # ---- 标签：胶囊形，浅底 + 发丝描边
        chip_theme=ft.ChipTheme(
            shape=ft.RoundedRectangleBorder(radius=RADIUS_PILL),
            padding=ft.Padding.symmetric(horizontal=10, vertical=2),
            label_text_style=text_style(12, weight=ft.FontWeight.W_500, color=on_surface),
            bgcolor=ft.Colors.with_opacity(0.04, ft.Colors.ON_SURFACE),
            selected_color=ft.Colors.PRIMARY_CONTAINER,
            check_color=ft.Colors.ON_PRIMARY_CONTAINER,
            border_side=ft.BorderSide(1, ft.Colors.TRANSPARENT),
            elevation=0,
            elevation_on_click=0,
            show_checkmark=False,
        ),
        dropdown_theme=ft.DropdownTheme(
            text_style=text_style(13, color=on_surface),
            menu_style=ft.MenuStyle(
                bgcolor=CARD_COLOR,
                shape=ft.RoundedRectangleBorder(radius=RADIUS_MD),
                elevation=8,
                shadow_color=ft.Colors.with_opacity(0.4 if dark else 0.14, "#0B0E14"),
                padding=ft.Padding.symmetric(vertical=SPACE_XS, horizontal=SPACE_XS),
                mouse_cursor=ft.MouseCursor.CLICK,
            ),
        ),
        list_tile_theme=ft.ListTileTheme(
            shape=ft.RoundedRectangleBorder(radius=RADIUS_MD),
            title_text_style=text_style(13, color=on_surface),
            subtitle_text_style=text_style(12, color=muted),
        ),
        divider_theme=ft.DividerTheme(color=BORDER_COLOR, thickness=1, space=1),
        progress_indicator_theme=ft.ProgressIndicatorTheme(
            color=ft.Colors.PRIMARY,
            linear_track_color=ft.Colors.with_opacity(0.12, ft.Colors.PRIMARY),
            border_radius=RADIUS_PILL,
            stroke_width=3,
        ),
        scrollbar_theme=ft.ScrollbarTheme(
            thickness=6,
            radius=RADIUS_PILL,
            track_visibility=False,
            interactive=True,
        ),
        switch_theme=ft.SwitchTheme(
            mouse_cursor=ft.MouseCursor.CLICK,
        ),
        checkbox_theme=ft.CheckboxTheme(mouse_cursor=ft.MouseCursor.CLICK),
    )


def build_theme() -> ft.Theme:
    """浅色主题。"""
    return _build_theme(dark=False)


def build_dark_theme() -> ft.Theme:
    """深色主题。"""
    return _build_theme(dark=True)
