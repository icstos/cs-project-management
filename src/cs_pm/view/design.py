"""设计层：cs-ui 令牌在本项目里的**语义投影**。

这里不再定义颜色、字号、排印律 —— 那些是 :mod:`ui.core.tokens` /
:mod:`ui.core.typography` / :mod:`ui.core.theme` 的职责，全应用只有一套。
本模块只回答"这个产品特有的几个决定"：

* **间距与尺寸**：页面边距、模块间距、卡片内边距、侧栏宽度、图表高度……
  值全部取自 4px 网格（``SPACE``），名字说明用途；
* **文字层级**：把 cs-ui 的八个字号档收成本项目用得到的五级
  （``DISPLAY`` / ``TITLE`` / ``BODY`` / ``LABEL`` / ``CAPTION``），
  并保证"任何显式样式都带颜色"；
* **语义色**：``Tone`` → cs-ui 的强调角色（``primary`` / ``success`` …），
  取色走 ``accent_text`` / ``accent_soft``，因此明暗两套主题自动成立；
* **品牌标识**：侧栏 logo 的微渐变，是本产品唯一一处自选色。

三条硬规则（都是踩过的坑，改动前先读）

1. **颜色只写角色名或语义函数**，不写死十六进制 —— 写死的那一刻，深色模式就瞎了。
2. **传了 ``style`` 就必须显式给 ``color``**：Flutter 收到 ``TextStyle`` 是整体
   替换而不是合并，缺色会落到白色（浅色主题下等于隐形）。:func:`text` 已兜底。
3. **明暗不在这里判断**。cs-ui 的 ``semantic_text`` 会读当前主题模式，
   切换主题由外壳的 ``use_theme()`` 触发整棵树重渲染；本模块不维护任何全局状态。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import ui
from ui import (
    ICON_SIZE,
    RADIUS,
    SPACE,
    Alignment,
    Animation,
    AnimationCurve,
    Border,
    BoxShadow,
    Colors,
    ColorValue,
    Control,
    IconData,
    Icons,
    LinearGradient,
    Text,
    TextStyle,
)
from ui.core import typography as tp
from ui.core.tokens import accent_soft, accent_text, overlay

from cs_pm.models.enums import Tone

# =========================================================================== 布局
#: 12 列栅格：``ResponsiveRow`` 的 ``col`` 取值以它为准（12 / 6 / 4 / 3 / 2）。
GRID_COLUMNS = 12

#: 页面边距：内容区与窗口边缘的呼吸空间（cs-ui 的 medium 档）
PAGE_PADDING = SPACE["6"]
#: 模块（页头 / 工具栏 / 内容块）之间的纵向间距
SECTION_GAP = SPACE["6"]
#: 卡片内边距
CARD_PADDING = SPACE["4"]
#: 表单字段之间的间距
FIELD_GAP = SPACE["3"]
#: 栅格间距：卡片与卡片之间
GRID_GUTTER = SPACE["4"]
#: 行内元素（图标与文字、徽标与徽标）的间距
INLINE_GAP = SPACE["2"]

#: 侧栏宽度。图标 + 文字横排（而不是图标下挂小字）：桌面端的侧栏读的是"词"，
#: 210 正好容得下"项目管理"四个字加内边距，又不至于吃掉内容区的宽度。
SIDEBAR_WIDTH = 208
#: 对话框内容区宽度
DIALOG_WIDTH = 480
#: 列表型容器的高度上限（左栏项目列表）
LIST_MAX_HEIGHT = 220
#: 趋势图高度
CHART_HEIGHT = 260
#: 状态栏高度（与 cs-ui StatusBar 一致）
STATUS_BAR_HEIGHT = 30

ICON_SM = ICON_SIZE["sm"]
ICON_MD = ICON_SIZE["md"]
ICON_LG = ICON_SIZE["lg"]

# =========================================================================== 圆角
# 圆角跟 cs-ui 的刻度走：输入框与按钮同档（6），卡片与面板一档（8），对话框一档（12）。
RADIUS_XS = RADIUS["xs"]
RADIUS_SM = RADIUS["sm"]
RADIUS_MD = RADIUS["md"]
RADIUS_LG = RADIUS["lg"]
RADIUS_XL = RADIUS["xl"]
RADIUS_PILL = RADIUS["full"]

RADIUS_INPUT = RADIUS["md"]
RADIUS_BUTTON = RADIUS["md"]
RADIUS_CARD = RADIUS["lg"]
RADIUS_DIALOG = RADIUS["xl"]

# =========================================================================== 动效
DURATION_FAST = 120
DURATION_BASE = 200
DURATION_SLOW = 320


def animate(*, duration: int = DURATION_BASE) -> Animation:
    """统一的隐式过渡：120–320ms + ease-out。"""
    return Animation(duration=duration, curve=AnimationCurve.EASE_OUT)


# =========================================================================== 文字
class TextLevel(StrEnum):
    """五级文字层级：页面标题 / 区块标题 / 正文 / 标签 / 说明。

    名字是**用途**，不是字号 —— 字号由 cs-ui 的排印律按档位给出，
    改字号只改 ``tokens.FONT_SIZE``，这里一个字都不用动。
    """

    DISPLAY = "display"
    TITLE = "title"
    BODY = "body"
    LABEL = "label"
    CAPTION = "caption"


#: 用途 → cs-ui 的排印档位（见 ``ui.core.typography.ROLES``）
_ROLE: dict[TextLevel, str] = {
    TextLevel.DISPLAY: "headline_lg",  # 24
    TextLevel.TITLE: "title",  # 16
    TextLevel.BODY: "body",  # 14
    TextLevel.LABEL: "small",  # 12
    TextLevel.CAPTION: "caption",  # 11
}


def text_style(
    level: TextLevel = TextLevel.BODY,
    *,
    color: ColorValue | None = None,
    weight=None,
    size: int | None = None,
) -> TextStyle:
    """按层级构造文本样式（字号 / 行高 / 字距 / 字重四件套 + 字体）。"""
    return tp.text_style(
        _ROLE[level],
        color=color or Colors.ON_SURFACE,
        weight=weight,
        size=size,
    )


def text(
    value: str,
    *,
    level: TextLevel = TextLevel.BODY,
    color: ColorValue | None = None,
    weight=None,
    size: int | None = None,
    **kwargs: object,
) -> Text:
    """按层级构造文本。``color`` 留空时沿用主题的 ``onSurface``。

    ``style`` 与 ``color`` 同时给：Flutter 收到显式 ``TextStyle`` 后不再继承
    主题文字色，只给 style 会画成白色；只给 color 又会丢掉行高与字距。
    """
    resolved = color or Colors.ON_SURFACE
    return Text(  # type: ignore[arg-type]
        value,
        style=text_style(level, color=resolved, weight=weight, size=size),
        color=resolved,
        **kwargs,
    )


# =========================================================================== 语义色
@dataclass(frozen=True, slots=True)
class ToneStyle:
    """一个语义角色在本项目里的三档表达 + 默认图标。

    ``accent`` 用于图标与强调文字，``container`` 用于淡底，``on_container``
    用于落在淡底上的文字 —— 三者同源，所以"成功"的标签与"成功"的图标是同一个绿。
    """

    accent: ColorValue
    container: ColorValue
    on_container: ColorValue
    icon: IconData


#: ``Tone`` → cs-ui 强调角色。``DANGER`` 在这里叫 ``danger``，与语义色同一套名字。
_ROLE_OF: dict[Tone, str] = {
    Tone.PRIMARY: "primary",
    Tone.INFO: "info",
    Tone.SUCCESS: "success",
    Tone.WARNING: "warning",
    Tone.DANGER: "danger",
    Tone.NEUTRAL: "neutral",
}

_ICON_OF: dict[Tone, IconData] = {
    Tone.PRIMARY: Icons.BOLT,
    Tone.INFO: Icons.INFO_OUTLINE,
    Tone.SUCCESS: Icons.CHECK_CIRCLE_OUTLINE,
    Tone.WARNING: Icons.WARNING_AMBER_ROUNDED,
    Tone.DANGER: Icons.ERROR_OUTLINE,
    Tone.NEUTRAL: Icons.CIRCLE_OUTLINED,
}


def role_of(tone: Tone) -> str:
    """``Tone`` 对应的 cs-ui 强调角色名（给 :class:`ui.Tag` / :class:`ui.MetricCard` 用）。"""
    return _ROLE_OF.get(tone, "neutral")


def tone_style(tone: Tone) -> ToneStyle:
    """取语义色的三档表达。取色在**渲染时**发生，因此跟随当前明暗模式。"""
    role = role_of(tone)
    return ToneStyle(
        accent=accent_text(role),
        container=accent_soft(role),
        on_container=accent_text(role),
        icon=_ICON_OF.get(tone, Icons.CIRCLE_OUTLINED),
    )


# --------------------------------------------------------------------------- 表面
def card_color() -> ColorValue:
    """卡片底色。

    浅色下取**最亮**的一档（白卡浮在灰底上）；深色下取比页面**亮**一档的容器色
    —— 深色里"更低"等于更黑，卡片会陷进背景，看不出层级。
    """
    return (
        Colors.SURFACE_CONTAINER_LOW
        if ui.current_mode() == "dark"
        else Colors.SURFACE_CONTAINER_LOWEST
    )


#: 页面底色
SURFACE_COLOR: ColorValue = Colors.SURFACE
#: 侧栏 / 状态栏底色（与页面同色，靠发丝线划分，追求通透）
SHELL_COLOR: ColorValue = Colors.SURFACE
#: 次级信息文字
MUTED_TEXT: ColorValue = Colors.ON_SURFACE_VARIANT
#: 发丝级分隔线 / 卡片描边
BORDER_COLOR: ColorValue = Colors.OUTLINE_VARIANT
#: 强调描边（需要更清晰边界时）
STRONG_BORDER: ColorValue = Colors.OUTLINE
#: 低对比信息面板底色
PANEL_COLOR: ColorValue = Colors.SURFACE_CONTAINER
#: 骨架屏的灰条底色
CODE_COLOR: ColorValue = Colors.SURFACE_CONTAINER_HIGH

# 控制台固定使用深底：日志这类"原始输出"用深色底更像终端，也与周围的浅色卡片
# 形成目的性对比，一眼分清"界面"与"机器输出"。这两组是**刻意不跟随主题**的
# 少数例外之一，写成模块常量让评审看得见。
CONSOLE_BG: ColorValue = "#141821"
CONSOLE_TEXT: ColorValue = "#C6CDDB"
CONSOLE_DIM: ColorValue = "#7C879C"
#: 等宽字体族：堆栈与命令要按列对齐，中文字体撑不住
MONO_FONTS = ["Consolas", "Cascadia Mono", "monospace"]


# --------------------------------------------------------------------------- git 约定
def addition_color() -> ColorValue:
    """新增行：绿色（深色下提亮，保证在深底上仍可读）。"""
    return accent_text("success")


def deletion_color() -> ColorValue:
    """删除行：红色。"""
    return accent_text("danger")


# --------------------------------------------------------------------------- 品牌
def brand_gradient() -> LinearGradient:
    """侧栏标识的微渐变：小面积使用，作为产品唯一的自选色。"""
    colors = ["#3E4EA8", "#6D7BE0"] if ui.current_mode() == "dark" else ["#4356C7", "#6A78E4"]
    return LinearGradient(
        begin=Alignment.TOP_LEFT,
        end=Alignment.BOTTOM_RIGHT,
        colors=colors,
    )


# =========================================================================== 阴影
def card_shadow(*, hover: bool = False) -> BoxShadow:
    """卡片投影：极淡、向下的柔和阴影；悬停时加深一档。"""
    return ui.elevation(2 if hover else 1)


def floating_shadow() -> BoxShadow:
    """浮层（对话框 / 菜单 / Toast）投影。"""
    return ui.elevation(3)


def pressed_shadow() -> BoxShadow:
    """按下时的投影：比静止态更贴地，制造"被按下去"的反馈。"""
    return ui.elevation(0)


# =========================================================================== 线条与状态层
def hairline() -> Border:
    """1px 发丝线（卡片描边、分隔线）。"""
    return Border.all(1, BORDER_COLOR)


def divider(**kwargs: object) -> Control:
    """一条水平发丝线。"""
    return ui.Divider(height=1, thickness=1, color=BORDER_COLOR, **kwargs)


def hover_layer() -> ColorValue:
    """悬停时的薄底（跟随主题的 8% 面层）。"""
    return overlay(0.08)


def selected_layer() -> ColorValue:
    """选中项的底：主色 12%，比悬停更明确但仍不刺眼。"""
    return ui.selected_layer("normal")
