"""设置页：``flet build`` 的参数配置。

这一页的形态由 :mod:`cs_pm.models.build_options` 的字段清单决定 —— 视图不知道
"有哪些参数"，只知道"``kind`` 怎么变成控件、``group`` 怎么分组"。新增一个
可配置参数只需要在那张表里加一行，这里不用动。

三条刻意的设计
--------------
1. **左标签 + 右控件**，全部走 ``ui.FormRow``：标签右边缘、控件左边缘各成
   一条竖线，扫读时沿着一条线就能把字段名读完（与项目对话框同一套表单语汇）。
2. **每项都标出对应的命令行参数**（``--template`` …）：用户在界面上改的是
   "模板所在文件夹"，同时也知道它落到哪条命令上 —— 页面底部的命令预览因此
   看得懂、对得上。
3. **命令预览随输入实时重算**（视图模型里是纯计算）：改一项参数，下面的命令
   立刻跟着变，不需要先保存再回打包页确认。
"""

from __future__ import annotations

import ui
from ui import (
    SPACE,
    Alignment,
    Column,
    Container,
    CrossAxisAlignment,
    FontWeight,
    FormRow,
    Icon,
    Icons,
    Padding,
    Row,
    ScrollMode,
    SelectBox,
    Switch,
    Text,
    TextField,
    TextOverflow,
)

from cs_pm.models.build_options import BuildOption, OptionKind, groups_of, options_of
from cs_pm.models.enums import Tone
from cs_pm.view import design as T
from cs_pm.view import widgets
from cs_pm.view.guard import guarded
from cs_pm.view.view_platform import FletPlatform, use_notices, use_platform_requests
from cs_pm.viewmodel.settings_vm import SettingsState, SettingsViewModel

#: 分组 → 图标。用图标给一列卡片一个可扫读的锚点，标题不再是唯一的线索。
_GROUP_ICONS: dict[str, str] = {
    "发布位置": Icons.FOLDER_SPECIAL_OUTLINED,
    "应用元信息": Icons.BADGE_OUTLINED,
    "构建行为": Icons.TUNE,
    "工具": Icons.TERMINAL,
}

_STATUS_CARD_WIDTH = 96
#: 标签列宽。FormRow 默认 96 只放得下四个汉字加冒号，本页有「生成文件夹根目录」
#: 这种七个字的标签 —— 不指定就会折成两行，整列标签看着参差。
_LABEL_WIDTH = 132


@guarded
def SettingsView(*, vm: SettingsViewModel, platform: FletPlatform) -> ui.Control:
    page = ui.context.page
    state = vm.state
    use_notices(page, vm)
    use_platform_requests(platform, vm)

    # 读设置 + 探测 flet 各做一次；两者都是异步的，渲染不等它们
    ui.use_effect(lambda: page.run_task(vm.load), [])
    ui.use_effect(lambda: page.run_task(vm.probe_tool), [])

    header = widgets.page_header(
        "设置",
        "配置 flet build 的打包参数：产物落在哪里、用哪个模板、带哪些元信息与开关",
        actions=[
            widgets.outlined(
                "恢复默认",
                icon=Icons.RESTART_ALT,
                disabled=state.saving,
                on_click=lambda _: vm.restore_defaults(),
            ),
            widgets.outlined(
                "打开根目录",
                icon=Icons.FOLDER_OPEN,
                disabled=state.saving,
                on_click=lambda _: page.run_task(vm.open_output_root),
            ),
            widgets.filled(
                "保存中…" if state.saving else "保存",
                icon=Icons.SAVE,
                disabled=not state.can_save,
                on_click=lambda _: page.run_task(vm.save),
            ),
        ],
    )

    if not state.loaded:
        return widgets.page_shell(header=header, body=widgets.busy_block("正在读取设置…"))

    return widgets.page_shell(
        header=header,
        body=Column(
            expand=True,
            scroll=ScrollMode.AUTO,
            spacing=T.SECTION_GAP,
            controls=[
                _status_card(state, on_probe=lambda: page.run_task(vm.probe_tool)),
                *[_group_card(group, state, vm) for group in groups_of()],
                _command_card(state),
            ],
        ),
    )


# --------------------------------------------------------------------------- 概览
def _status_card(state: SettingsState, *, on_probe) -> ui.Control:
    """顶部概览：保存状态、关键读数、示例产物目录与校验问题。"""
    tool = state.tool
    pills: list[ui.Control] = [
        widgets.pill(
            f"{len(state.changed_keys)} 项未保存",
            tone=Tone.WARNING,
            icon=Icons.EDIT_NOTE,
            dense=True,
        )
        if state.dirty
        else widgets.pill("已保存", tone=Tone.NEUTRAL, icon=Icons.CHECK, dense=True),
        widgets.pill(
            f"目标 {state.values.get('target', 'windows')}",
            icon=Icons.LAPTOP_WINDOWS,
            dense=True,
        ),
        widgets.pill(
            f"Python {state.values.get('python_version') or '默认'}",
            icon=Icons.CODE,
            dense=True,
        ),
    ]
    if tool is not None:
        # detail 形如 ``flet: 1.1.2``，前面不要再写一遍产品名
        label = (tool.detail or "flet 可用") if tool.available else "未找到 flet 命令"
        pills.append(
            widgets.pill(
                label,
                tone=Tone.INFO if tool.available else Tone.DANGER,
                icon=Icons.CHECK_CIRCLE_OUTLINE if tool.available else Icons.ERROR_OUTLINE,
                dense=True,
            )
        )

    notes: list[ui.Control] = [widgets.inline_error(issue) for issue in state.problems]
    if state.dirty and not state.problems:
        notes.append(
            widgets.hint_row(
                Icons.SAVE_OUTLINED,
                "参数已改但还没保存：点右上角「保存」后才会入库，打包页也会立刻按新参数执行。",
                tone=Tone.INFO,
            )
        )

    return widgets.surface(
        content=Column(
            spacing=T.FIELD_GAP,
            tight=True,
            controls=[
                Row(
                    spacing=SPACE["2"],
                    vertical_alignment=CrossAxisAlignment.CENTER,
                    controls=[
                        Container(
                            width=28,
                            height=28,
                            border_radius=T.RADIUS_SM,
                            bgcolor=T.tone_style(Tone.PRIMARY).container,
                            alignment=Alignment.CENTER,
                            content=Icon(
                                Icons.TUNE,
                                size=16,
                                color=T.tone_style(Tone.PRIMARY).accent,
                            ),
                        ),
                        T.text(
                            "打包参数",
                            level=T.TextLevel.TITLE,
                            weight=FontWeight.W_600,
                        ),
                        Container(expand=True),
                        widgets.icon_action(
                            Icons.REFRESH,
                            "重新探测 flet 命令",
                            lambda _: on_probe(),
                        ),
                        widgets.muted("改完点保存即生效", size=11),
                    ],
                ),
                Row(spacing=SPACE["2"], wrap=True, run_spacing=SPACE["2"], controls=pills),
                _path_row(Icons.INVENTORY_2_OUTLINED, "产物示例", state.sample or "—"),
                *notes,
            ],
        )
    )


def _path_row(icon: str, label: str, value: str) -> Row:
    return Row(
        spacing=SPACE["2"],
        vertical_alignment=CrossAxisAlignment.CENTER,
        controls=[
            Icon(icon, size=T.ICON_SM, color=T.MUTED_TEXT),
            T.text(label, level=T.TextLevel.CAPTION, color=T.MUTED_TEXT, width=_STATUS_CARD_WIDTH),
            Text(
                value,
                size=12,
                expand=True,
                max_lines=1,
                overflow=TextOverflow.ELLIPSIS,
                tooltip=value,
                selectable=True,
            ),
        ],
    )


# --------------------------------------------------------------------------- 分组
def _group_card(group: str, state: SettingsState, vm: SettingsViewModel) -> ui.Control:
    options = options_of(group)
    changed = sum(1 for option in options if option.key in state.changed_keys)
    return widgets.surface(
        content=Column(
            spacing=T.FIELD_GAP,
            tight=True,
            controls=[
                Row(
                    spacing=SPACE["2"],
                    vertical_alignment=CrossAxisAlignment.CENTER,
                    controls=[
                        Icon(
                            _GROUP_ICONS.get(group, Icons.CIRCLE_OUTLINED),
                            size=T.ICON_SM,
                            color=T.MUTED_TEXT,
                        ),
                        T.text(group, level=T.TextLevel.TITLE, weight=FontWeight.W_600),
                        Container(expand=True),
                        *(
                            [widgets.pill(f"{changed} 项改动", tone=Tone.WARNING, dense=True)]
                            if changed
                            else []
                        ),
                    ],
                ),
                *[_field(option, state, vm) for option in options],
            ],
        )
    )


def _field(option: BuildOption, state: SettingsState, vm: SettingsViewModel) -> ui.Control:
    """一个字段：按 ``kind`` 选控件，标签与说明交给 FormRow 对齐。"""
    value = state.values.get(option.key, "")
    hint = _hint(option)

    match option.kind:
        case OptionKind.BOOL:
            # Switch 自己是一整行（主轴 max），不套 tight 的 Row 会被撑到卡片最右，
            # 和左边一列标签之间空出一大片 —— 开关的左边因此也贴着控件的竖线。
            return FormRow(
                label=option.label,
                label_width=_LABEL_WIDTH,
                control=Row(
                    spacing=SPACE["2"],
                    tight=True,
                    vertical_alignment=CrossAxisAlignment.CENTER,
                    controls=[
                        Switch(
                            value=value == "1",
                            on_toggle=lambda enabled, key=option.key: vm.set_flag(key, enabled),
                            disabled=state.saving,
                        ).ui(),
                        widgets.muted("已启用" if value == "1" else "已关闭", size=11),
                    ],
                ),
                hint=hint,
            )
        case OptionKind.CHOICE:
            return FormRow(
                label=option.label,
                label_width=_LABEL_WIDTH,
                control=SelectBox(
                    value=value or None,
                    options=[ui.SelectOption(key=key, text=text) for key, text in option.choices],
                    editable=False,
                    # None = 吃掉标签右边的全部宽度
                    width=None,
                    disabled=state.saving,
                    on_change=lambda e, key=option.key: vm.choose(
                        key, widgets.event_value(e) or ""
                    ),
                ).ui(),
                hint=hint,
            )
        case OptionKind.MULTILINE:
            return FormRow(
                label=option.label,
                label_width=_LABEL_WIDTH,
                # 多行输入把标签挪到上方：左侧一列标签会把输入区挤窄
                vertical=True,
                control=TextField(
                    key=f"setting-{option.key}",
                    value=value,
                    multiline=True,
                    min_lines=2,
                    max_lines=6,
                    dense=True,
                    hint_text=option.placeholder,
                    text_size=12,
                    disabled=state.saving,
                    on_change=lambda e, key=option.key: vm.change(
                        key, widgets.event_value(e) or ""
                    ),
                ),
                hint=hint,
            )
        case OptionKind.PATH:
            return FormRow(
                label=option.label,
                label_width=_LABEL_WIDTH,
                control=Row(
                    spacing=SPACE["2"],
                    vertical_alignment=CrossAxisAlignment.CENTER,
                    controls=[
                        TextField(
                            key=f"setting-{option.key}",
                            value=value,
                            expand=True,
                            dense=True,
                            hint_text=option.placeholder,
                            prefix_icon=Icons.FOLDER_OUTLINED,
                            disabled=state.saving,
                            on_change=lambda e, key=option.key: vm.change(
                                key, widgets.event_value(e) or ""
                            ),
                        ),
                        widgets.outlined(
                            "浏览",
                            icon=Icons.FOLDER_OPEN,
                            disabled=state.saving,
                            on_click=lambda _, key=option.key: vm.request_pick(key),
                        ),
                    ],
                ),
                hint=hint,
            )
        case _:
            return FormRow(
                label=option.label,
                label_width=_LABEL_WIDTH,
                control=TextField(
                    key=f"setting-{option.key}",
                    value=value,
                    dense=True,
                    hint_text=option.placeholder,
                    disabled=state.saving,
                    on_change=lambda e, key=option.key: vm.change(
                        key, widgets.event_value(e) or ""
                    ),
                ),
                hint=hint,
            )


def _hint(option: BuildOption) -> ui.Control:
    """说明行：左边是对应的命令行参数，右边是白话解释。"""
    text = widgets.muted(option.hint, size=11, expand=True, max_lines=2)
    if not option.flag:
        return Row(controls=[text])
    return Row(
        spacing=SPACE["2"],
        vertical_alignment=CrossAxisAlignment.START,
        controls=[
            Container(
                padding=Padding.symmetric(horizontal=SPACE["1"], vertical=0),
                border_radius=T.RADIUS_XS,
                bgcolor=T.PANEL_COLOR,
                border=T.hairline(),
                content=Text(
                    option.flag,
                    size=10,
                    color=T.MUTED_TEXT,
                    font_family=T.MONO_FONTS[0],
                    font_family_fallback=T.MONO_FONTS,
                    no_wrap=True,
                ),
            ),
            text,
        ],
    )


# --------------------------------------------------------------------------- 命令预览
def _command_card(state: SettingsState) -> ui.Control:
    """生效后会执行的命令。与打包页同源，改一项参数立刻反映在这里。"""
    if state.steps:
        body: ui.Control = widgets.command_steps(state.steps)
    else:
        body = widgets.flat_panel(
            widgets.hint_row(
                Icons.INFO_OUTLINE,
                "在「项目」页添加一个项目后，这里会显示用当前参数推导出的命令",
                tone=Tone.NEUTRAL,
            )
        )

    return widgets.surface(
        content=Column(
            spacing=T.FIELD_GAP,
            tight=True,
            controls=[
                Row(
                    spacing=SPACE["2"],
                    vertical_alignment=CrossAxisAlignment.CENTER,
                    controls=[
                        T.text(
                            "保存后将要执行的命令",
                            level=T.TextLevel.TITLE,
                            weight=FontWeight.W_600,
                        ),
                        Container(expand=True),
                        widgets.muted(
                            "以第一个项目为例；实际打包时按各自的项目名与目录推导",
                            size=11,
                        ),
                    ],
                ),
                body,
            ],
        )
    )
