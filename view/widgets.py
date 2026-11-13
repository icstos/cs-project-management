"""界面基础件：把 cs-ui 的组件装配成这个产品说话的词汇。

各视图只关心"内容"，不关心"样式"：这里是按钮、标签、卡片、空态、指标卡、
骨架屏与提示的唯一出口。所有取值来自 :mod:`view.design`（它又只取自 cs-ui 的
令牌），因此间距、圆角、字号、语义色在全应用只有一套。

三条约定
--------
1. **按钮四种意图**：主操作 :func:`filled`、次操作 :func:`outlined`、
   低优先级 :func:`text_btn`、破坏性 :func:`danger` —— 一屏只该有一个主操作。
2. **提示统一走 :func:`toast`**，它落到 cs-ui 的 :class:`ui.Message`（顶部居中、
   三秒自走）；不要再用 SnackBar，弹层栈一次只挂一条。
3. **纯构件，不含业务判断**：需要判断的地方都发生在视图模型里。

关于"为什么还要包一层"
----------------------
cs-ui 给的是通用组件（``Button`` 只有三档强调、``Tag`` 只有语气），而本产品有
固定的语汇：主操作叫"添加项目"、状态标签要带勾/叹号图标、指标卡要吃掉栅格列。
包一层的价值是**把这些默认值收在一处**：改一处，八个页面一起变。
"""

from __future__ import annotations

import ui
from ui import (
    SPACE,
    Alignment,
    Border,
    Button,
    ButtonStyle,
    Colors,
    Column,
    Container,
    ControlState,
    CrossAxisAlignment,
    Divider,
    FontWeight,
    Icon,
    IconButton,
    Icons,
    MainAxisAlignment,
    Message,
    MetricCard,
    MouseCursor,
    Padding,
    Row,
    Shimmer,
    StyleType,
    Tag,
    Text,
    TextAlign,
    TextOverflow,
    VerticalDivider,
)

from models.enums import Permission, Tone
from view import design as T
from viewmodel.formatting import format_count

__all__ = [
    "busy_block",
    "choice_chip",
    "command_steps",
    "confirm_dialog",
    "danger",
    "diff_text",
    "empty_state",
    "event_value",
    "filled",
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

    Flet 客户端在抛出 ``change`` / ``select`` 时先把新值作为事件数据送出，而回写
    ``value`` 属性走另一条消息、不保证先到达。所以事件处理器一律以 ``event.data``
    为准，不要读 ``event.control.value``，否则可能读到旧值。
    """
    return getattr(event, "data", None)


# --------------------------------------------------------------------------- 文本
def muted(
    value: str,
    *,
    size: int | None = None,
    expand: bool = False,
    max_lines: int = 1,
    selectable: bool = False,
) -> Text:
    """次级信息：LABEL 层级 + 中性色，保持全应用统一的视觉重量。"""
    return T.text(
        value,
        level=T.TextLevel.LABEL,
        size=size,
        color=T.MUTED_TEXT,
        expand=expand,
        max_lines=max_lines,
        overflow=TextOverflow.ELLIPSIS,
        selectable=selectable,
    )


def key_hint(keys: str) -> ui.Kbd:
    """快捷键角标（cs-ui 的键帽，按 ``+`` 自动拆成多顶）。"""
    return ui.Kbd(keys)


# --------------------------------------------------------------------------- 按钮
def filled(
    text: str,
    *,
    icon: str | None = None,
    on_click=None,
    disabled: bool = False,
    tooltip: str | None = None,
) -> Button:
    """主操作：实色填充，一屏只该有一个。"""
    return Button(
        text,
        icon=icon,
        on_click=on_click,
        disabled=disabled,
        tooltip=tooltip,
        style_type=StyleType.PRIMARY,
    )


def outlined(
    text: str,
    *,
    icon: str | None = None,
    on_click=None,
    disabled: bool = False,
    tooltip: str | None = None,
) -> Button:
    """次操作：镂空（表面底 + 主色描边），与主操作同高。"""
    return Button(
        text,
        icon=icon,
        on_click=on_click,
        disabled=disabled,
        tooltip=tooltip,
        style_type=StyleType.PRIMARY,
        plain=True,
    )


def text_btn(
    text: str,
    *,
    icon: str | None = None,
    on_click=None,
    disabled: bool = False,
) -> Button:
    """文字按钮：最轻的一档，用于"取消"这类低优先级动作。"""
    return Button(text, icon=icon, on_click=on_click, disabled=disabled)


def danger(
    text: str,
    *,
    icon: str = Icons.DELETE_OUTLINE,
    on_click=None,
    disabled: bool = False,
) -> Button:
    """破坏性操作：错误色实心，形状与内边距跟主按钮一致。"""
    return Button(
        text,
        icon=icon,
        on_click=on_click,
        disabled=disabled,
        style_type=StyleType.ERROR,
    )


def icon_action(
    icon: str,
    tooltip: str,
    on_click,
    *,
    tone: Tone = Tone.NEUTRAL,
    disabled: bool = False,
    size: int = T.ICON_MD,
) -> IconButton:
    """图标按钮：默认透明，悬停时浮出一层语义色薄底。"""
    accent = T.tone_style(tone).accent
    return IconButton(
        icon=icon,
        tooltip=tooltip,
        on_click=on_click,
        disabled=disabled,
        icon_size=size,
        icon_color=accent,
        style=ButtonStyle(
            shape=ui.RoundedRectangleBorder(radius=T.RADIUS_SM),
            padding=6,
            bgcolor={
                ControlState.HOVERED: ui.Colors.with_opacity(0.10, accent),
                ControlState.DEFAULT: Colors.TRANSPARENT,
            },
            overlay_color=ui.Colors.with_opacity(0.10, accent),
            animation_duration=ui.Duration(milliseconds=T.DURATION_FAST),
            mouse_cursor=MouseCursor.CLICK,
        ),
    )


def choice_chip(label: str, *, selected: bool, on_click) -> Container:
    """可点的筛选胶囊（单选）。

    为什么不用 ``ui.Chip``：那个组件的值是**它自己的文案**，而筛选要的是
    "标签给人看、值给逻辑用"（``全部 8`` 对应 ``ProjectFilter.ALL``）。
    这里只是把两种状态画对：选中用主色实底 + 反白字，未选中是透明底 + 中性字，
    切换时重量接近，整行不会跳动。
    """
    fg = Colors.ON_PRIMARY if selected else T.MUTED_TEXT
    return Container(
        on_click=on_click,
        border_radius=T.RADIUS_PILL,
        padding=Padding.symmetric(horizontal=SPACE["3"], vertical=SPACE["1"]),
        bgcolor=Colors.PRIMARY if selected else ui.overlay(0.04),
        border=Border.all(1, Colors.PRIMARY if selected else T.BORDER_COLOR),
        ink=True,
        ink_color=ui.Colors.with_opacity(0.08, Colors.PRIMARY),
        animate=T.animate(duration=T.DURATION_FAST),
        content=T.text(
            label,
            level=T.TextLevel.LABEL,
            color=fg,
            weight=ui.FontWeight.W_500,
        ),
    )


# --------------------------------------------------------------------------- 容器
def surface(
    content,
    *,
    padding: int = T.CARD_PADDING,
    expand: bool = False,
    key: str | None = None,
    col=None,
    height: int | None = None,
    on_click=None,
    on_hover=None,
    hovered: bool = False,
    tooltip: str | None = None,
    bgcolor=None,
) -> Container:
    """卡片容器：卡片底色 + 发丝描边 + 极淡投影。

    ``hovered=True`` 时投影加深一档，配合 :func:`design.animate` 形成"悬停轻微
    抬起"的反馈；交互式卡片（``on_click``）另外拿到水波纹。
    """
    interactive = on_click is not None
    return Container(
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
        bgcolor=bgcolor or T.card_color(),
        border=T.hairline(),
        shadow=T.card_shadow(hover=hovered),
        ink=interactive,
        ink_color=ui.overlay(0.06, role=Colors.PRIMARY) if interactive else None,
        animate=T.animate(),
        clip_behavior=ui.ClipBehavior.ANTI_ALIAS,
    )


def flat_panel(content, *, padding: int = SPACE["3"]) -> Container:
    """低对比度的信息面板，用于承载次要说明（比卡片再浅一档）。"""
    return Container(
        content=content,
        padding=padding,
        border_radius=T.RADIUS_MD,
        bgcolor=T.PANEL_COLOR,
        border=T.hairline(),
    )


def command_steps(steps: tuple[str, ...]) -> Container:
    """编号 + 等宽文本的命令列表。

    打包页的「将要执行的步骤」与设置页的命令预览共用它：两边看到的东西
    与真正执行的命令同源（都由打包端口生成），只是所在页面不同。
    """
    return flat_panel(
        Column(
            spacing=SPACE["2"],
            tight=True,
            controls=[
                Row(
                    spacing=SPACE["2"],
                    vertical_alignment=CrossAxisAlignment.START,
                    controls=[
                        Container(
                            width=20,
                            height=20,
                            border_radius=T.RADIUS_XS,
                            bgcolor=T.card_color(),
                            border=T.hairline(),
                            alignment=Alignment.CENTER,
                            content=T.text(
                                str(index),
                                level=T.TextLevel.CAPTION,
                                weight=FontWeight.W_700,
                                color=T.MUTED_TEXT,
                            ),
                        ),
                        Text(
                            command,
                            size=11,
                            expand=True,
                            selectable=True,
                            font_family=T.MONO_FONTS[0],
                            font_family_fallback=T.MONO_FONTS,
                            style=ui.TextStyle(height=1.5),
                        ),
                    ],
                )
                for index, command in enumerate(steps, start=1)
            ],
        ),
        padding=SPACE["3"],
    )


def divider(*, vertical: bool = False) -> ui.Control:
    """发丝分隔线。"""
    if vertical:
        return VerticalDivider(width=1, thickness=1, color=T.BORDER_COLOR)
    return Divider(height=1, thickness=1, color=T.BORDER_COLOR)


# --------------------------------------------------------------------------- 标签
def pill(
    label: str,
    *,
    tone: Tone = Tone.NEUTRAL,
    icon: str | None = None,
    dense: bool = False,
) -> Tag:
    """语义状态标签（cs-ui 的 Tag）：淡底 + 同色描边 + 可选图标。"""
    return Tag(label, role=T.role_of(tone), icon=icon, dense=dense)


def flag_pill(
    label: str,
    ok: bool,
    *,
    bad_label: str | None = None,
    bad_tone: Tone = Tone.WARNING,
) -> Tag:
    """布尔状态角标。

    ``bad_label`` 给出否定说法：否则会出现"已配置远程"配一个警告图标的怪状态。
    """
    return pill(
        label if ok else (bad_label or label),
        tone=Tone.NEUTRAL if ok else bad_tone,
        icon=Icons.CHECK_CIRCLE if ok else Icons.WARNING_AMBER_ROUNDED,
        dense=True,
    )


def permission_pill(permission: Permission) -> Tag:
    """可见性角标：公开用信息色 + 地球，私有用中性色 + 锁。"""
    public = permission is Permission.PUBLIC
    return pill(
        permission.label,
        tone=Tone.INFO if public else Tone.NEUTRAL,
        icon=Icons.PUBLIC if public else Icons.LOCK,
        dense=True,
    )


def diff_text(insertions: int, deletions: int, *, size: int | None = None) -> Row:
    """git 约定：新增绿、删除红。"""
    return Row(
        spacing=SPACE["2"],
        tight=True,
        vertical_alignment=CrossAxisAlignment.CENTER,
        controls=[
            T.text(
                f"+{format_count(insertions)}",
                level=T.TextLevel.LABEL,
                size=size,
                color=T.addition_color(),
                weight=ui.FontWeight.W_600,
            ),
            T.text(
                f"-{format_count(deletions)}",
                level=T.TextLevel.LABEL,
                size=size,
                color=T.deletion_color(),
                weight=ui.FontWeight.W_600,
            ),
        ],
    )


# --------------------------------------------------------------------------- 骨架
def page_header(
    title_text: str,
    subtitle: str | None = None,
    *,
    actions: list[ui.Control] | None = None,
) -> Row:
    """页面头部：左侧标题组，右侧动作区，两端对齐。"""
    head: list[ui.Control] = [T.text(title_text, level=T.TextLevel.DISPLAY)]
    if subtitle:
        head.append(
            T.text(
                subtitle,
                level=T.TextLevel.BODY,
                color=T.MUTED_TEXT,
                max_lines=2,
            )
        )
    return Row(
        spacing=T.INLINE_GAP * 2,
        vertical_alignment=CrossAxisAlignment.START,
        controls=[
            Column(spacing=SPACE["1"], tight=True, expand=True, controls=head),
            Row(spacing=SPACE["2"], tight=True, controls=actions or []),
        ],
    )


def page_shell(*, header: ui.Control, body: ui.Control) -> Container:
    """页面骨架：统一边距、统一底色、统一模块间距。"""
    return Container(
        expand=True,
        padding=T.PAGE_PADDING,
        bgcolor=T.SURFACE_COLOR,
        content=Column(expand=True, spacing=T.SECTION_GAP, controls=[header, body]),
    )


def hint_row(icon: str, text: str, *, tone: Tone = Tone.INFO) -> Row:
    """一行"图标 + 说明"，用于提示、警告与错误。"""
    style = T.tone_style(tone)
    return Row(
        spacing=SPACE["2"],
        vertical_alignment=CrossAxisAlignment.CENTER,
        controls=[
            Icon(icon, size=T.ICON_SM, color=style.accent),
            T.text(
                text,
                level=T.TextLevel.LABEL,
                color=T.MUTED_TEXT,
                expand=True,
                max_lines=3,
            ),
        ],
    )


def inline_error(message: str) -> Row:
    """表单内的实时错误提示（错误色图标 + 说明，不改变布局高度）。"""
    return hint_row(Icons.ERROR_OUTLINE, message, tone=Tone.DANGER)


# --------------------------------------------------------------------------- 指标卡
def metric(
    label: str,
    value: str,
    *,
    tone: Tone = Tone.PRIMARY,
    icon: str | None = None,
    hint: str | None = None,
    col=None,
) -> MetricCard:
    """指标卡（cs-ui 的 MetricCard）：图标承担语义色，数值用最高层级。"""
    return MetricCard(
        label=label,
        value=value,
        role=T.role_of(tone),
        icon=icon,
        hint=hint or "",
        col=col or {"xs": 6, "sm": 4, "md": 4, "lg": 2},
    )


# --------------------------------------------------------------------------- 状态
def empty_state(
    icon: str,
    title_text: str,
    hint: str,
    *,
    action: ui.Control | None = None,
) -> Container:
    """空状态：柔和图标 + 标题 + 一句引导 + 可选主操作。

    比 cs-ui 的 ``empty_block`` 多一个"下一步"按钮 —— 空态的价值就在于告诉用户
    现在该做什么，只有文字没有入口等于没说完。
    """
    return Container(
        expand=True,
        alignment=Alignment.CENTER,
        padding=SPACE["8"],
        content=Column(
            horizontal_alignment=CrossAxisAlignment.CENTER,
            spacing=SPACE["3"],
            tight=True,
            controls=[
                Container(
                    width=56,
                    height=56,
                    border_radius=T.RADIUS_XL,
                    bgcolor=T.PANEL_COLOR,
                    border=T.hairline(),
                    alignment=Alignment.CENTER,
                    content=Icon(icon, size=T.ICON_LG + 6, color=T.MUTED_TEXT),
                ),
                T.text(title_text, level=T.TextLevel.TITLE),
                T.text(
                    hint,
                    level=T.TextLevel.BODY,
                    color=T.MUTED_TEXT,
                    text_align=TextAlign.CENTER,
                    max_lines=3,
                ),
                *(
                    [Container(content=action, margin=Padding.only(top=SPACE["2"]))]
                    if action
                    else []
                ),
            ],
        ),
    )


def busy_block(text: str = "正在加载…") -> Container:
    """柔和加载动画：进度环 + 一行说明，用于"确实在忙"的整块占位。"""
    return Container(
        expand=True,
        alignment=Alignment.CENTER,
        content=Column(
            horizontal_alignment=CrossAxisAlignment.CENTER,
            spacing=SPACE["3"],
            tight=True,
            controls=[
                ui.Loading(size_name="normal"),
                muted(text, size=13),
            ],
        ),
    )


def _bone(width: int | None = None, *, height: int = 12, expand: bool = False) -> Container:
    return Container(
        width=width,
        height=height,
        expand=expand,
        border_radius=T.RADIUS_XS,
        bgcolor=T.CODE_COLOR,
    )


def _shimmer(content: ui.Control) -> Shimmer:
    """微光扫过的占位：骨架屏的"在动"比静态灰块更像加载中。"""
    return Shimmer(
        base_color=ui.Colors.with_opacity(0.0, T.MUTED_TEXT),
        highlight_color=ui.Colors.with_opacity(0.12, T.MUTED_TEXT),
        period=1400,
        content=content,
    )


def skeleton_block(*, rows: int = 3, title: bool = True, text: str = "正在加载…") -> Container:
    """骨架屏：结构与真实卡片一致，首屏不会出现大片空白。"""
    placeholder = Column(
        spacing=SPACE["3"],
        tight=True,
        controls=[
            _bone(180, height=16) if title else Container(),
            *[
                Row(
                    spacing=SPACE["3"],
                    controls=[
                        Container(
                            width=32,
                            height=32,
                            border_radius=T.RADIUS_SM,
                            bgcolor=T.CODE_COLOR,
                        ),
                        Column(
                            spacing=SPACE["2"],
                            tight=True,
                            expand=True,
                            controls=[_bone(expand=True), _bone(160)],
                        ),
                    ],
                )
                for _ in range(rows)
            ],
        ],
    )
    return Container(
        expand=True,
        content=Column(
            spacing=SPACE["4"],
            controls=[
                Container(
                    padding=T.CARD_PADDING,
                    border_radius=T.RADIUS_CARD,
                    bgcolor=T.card_color(),
                    border=T.hairline(),
                    content=_shimmer(placeholder),
                ),
                Row(
                    spacing=SPACE["2"],
                    alignment=MainAxisAlignment.CENTER,
                    controls=[
                        ui.Loading(size_name="small"),
                        muted(text, size=12),
                    ],
                ),
            ],
        ),
    )


def skeleton_card(*, col=None, height: int = 168) -> Container:
    """卡片骨架：与真实项目卡片同宽同高，加载完成时布局不跳动。"""
    return Container(
        col=col,
        height=height,
        padding=T.CARD_PADDING,
        border_radius=T.RADIUS_CARD,
        bgcolor=T.card_color(),
        border=T.hairline(),
        content=_shimmer(
            Column(
                spacing=SPACE["3"],
                tight=True,
                controls=[
                    Row(
                        spacing=SPACE["3"],
                        controls=[
                            Column(
                                spacing=SPACE["2"],
                                tight=True,
                                expand=True,
                                controls=[_bone(140, height=15), _bone(expand=True, height=10)],
                            ),
                            Container(
                                width=44,
                                height=20,
                                border_radius=T.RADIUS_PILL,
                                bgcolor=T.CODE_COLOR,
                            ),
                        ],
                    ),
                    Row(
                        spacing=SPACE["2"],
                        controls=[
                            Container(
                                width=64,
                                height=20,
                                border_radius=T.RADIUS_PILL,
                                bgcolor=T.CODE_COLOR,
                            ),
                            Container(
                                width=88,
                                height=20,
                                border_radius=T.RADIUS_PILL,
                                bgcolor=T.CODE_COLOR,
                            ),
                        ],
                    ),
                    Container(height=1, bgcolor=T.BORDER_COLOR),
                    Row(
                        spacing=SPACE["3"],
                        controls=[_bone(120, height=11), Container(expand=True)],
                    ),
                ],
            )
        ),
    )


# --------------------------------------------------------------------------- 反馈
#: ``Tone`` → cs-ui 的 ``StyleType``（Message 用的语气）。中性没有对应档，
#: 退回信息色 —— 它本来就是"说明"，不是"结论"。
_TOAST_STYLE: dict[Tone, StyleType] = {
    Tone.PRIMARY: StyleType.INFO,
    Tone.INFO: StyleType.INFO,
    Tone.SUCCESS: StyleType.SUCCESS,
    Tone.WARNING: StyleType.WARNING,
    Tone.DANGER: StyleType.ERROR,
    Tone.NEUTRAL: StyleType.INFO,
}


def toast(page: ui.Page, message: str, *, tone: Tone = Tone.SUCCESS) -> None:
    """顶部居中的一次性回执（cs-ui 的 Message），三秒自走、同款合并。"""
    Message(message, style_type=_TOAST_STYLE.get(tone, StyleType.INFO)).show(page)


def confirm_dialog(
    *,
    title_text: str,
    message: str,
    confirm_label: str,
    on_confirm,
    on_cancel,
    extra: ui.Control | None = None,
    destructive: bool = True,
) -> ui.AlertDialog:
    """确认框：标题条 + 说明 + 可选补充面板 + "取消 / 确认"。

    按钮手工给（而不是让 AlertDialog 自动铺）：本产品的确认文案是"删除并打包"、
    "重试删除"这类**具体动作**，不是通用的"确定"。
    """
    return ui.AlertDialog(
        modal=True,
        title=title_text,
        msg=Column(
            width=T.DIALOG_WIDTH,
            tight=True,
            spacing=T.FIELD_GAP,
            controls=[
                T.text(message, level=T.TextLevel.BODY, color=T.MUTED_TEXT),
                *([extra] if extra else []),
            ],
        ),
        actions=[
            text_btn("取消", on_click=on_cancel),
            danger(confirm_label, on_click=on_confirm)
            if destructive
            else filled(confirm_label, on_click=on_confirm),
        ],
        style_type=StyleType.ERROR if destructive else StyleType.PRIMARY,
    )
