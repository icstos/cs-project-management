"""对话框构件。

都是纯函数：接收当前状态、返回一个 ``ui.AlertDialog``；由持有状态的视图通过
``use_dialog`` 渲染，因此对话框内容随状态实时刷新。所有回调都把意图报给视图模型，
这里不做任何判断。

对话框统一走 :func:`view.widgets.confirm_dialog` 或同一套头部结构（语义色图标块 +
标题 + 副标题），保证"弹出来的东西"看起来是同一个系统里的。
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
    Row,
    SelectBox,
    TextField,
)

from models.dtos import Project
from models.enums import Permission, Tone
from view import design as T
from view import widgets
from viewmodel.build_vm import OutputConflict, RemovalFailure
from viewmodel.projects_vm import ProjectDraft

__all__ = [
    "delete_project_dialog",
    "output_conflict_dialog",
    "output_locked_dialog",
    "project_form_dialog",
]

_PERMISSION_HINT = "公开项目会在报表中标注为可共享；私有项目仅本机可见。"
# 空态与"核验中"共用一句话：两种情况都成立，用户继续输入时也不会看到误导性的报错
_PATH_PENDING_HINT = "粘贴路径后会自动核验是否为 Git 仓库"


def _dialog_title(icon: str, title_text: str, subtitle: str, *, tone: Tone = Tone.PRIMARY):
    """对话框统一的头部：语义色圆角图标 + 标题 + 副标题。"""
    style = T.tone_style(tone)
    return Row(
        spacing=T.FIELD_GAP,
        vertical_alignment=CrossAxisAlignment.CENTER,
        controls=[
            Container(
                width=36,
                height=36,
                border_radius=T.RADIUS_MD,
                bgcolor=style.container,
                alignment=Alignment.CENTER,
                content=Icon(icon, size=T.ICON_MD, color=style.accent),
            ),
            Column(
                spacing=0,
                tight=True,
                expand=True,
                controls=[
                    T.text(
                        title_text,
                        level=T.TextLevel.TITLE,
                        weight=FontWeight.W_600,
                    ),
                    widgets.muted(subtitle, size=12, max_lines=2),
                ],
            ),
        ],
    )


def _path_hint(draft: ProjectDraft) -> ui.Control:
    """路径输入框下的状态行：给粘贴进来的路径一个即时反馈。"""
    text = draft.local_path.strip()
    if not text or draft.checked_text != text:
        return widgets.hint_row(Icons.CONTENT_PASTE, _PATH_PENDING_HINT, tone=Tone.NEUTRAL)
    if draft.path_issue is None:
        return widgets.hint_row(Icons.CHECK_CIRCLE_OUTLINE, "已识别到 Git 仓库", tone=Tone.SUCCESS)
    return widgets.hint_row(Icons.FOLDER_OFF, draft.path_issue, tone=Tone.WARNING)


def project_form_dialog(
    *,
    draft: ProjectDraft,
    on_name,
    on_permission,
    on_path_change,
    on_path_commit,
    on_paste_path,
    on_pick_path,
    on_cancel,
    on_save,
) -> ui.AlertDialog:
    """新增 / 编辑项目。"""
    can_save = draft.can_save

    def submit_path(_=None) -> None:
        """路径框里回车：先整理输入，再按需保存。"""
        on_path_commit()
        if can_save:
            on_save()

    return ui.AlertDialog(
        modal=True,
        title=_dialog_title(
            Icons.EDIT_OUTLINED if draft.is_edit else Icons.ADD,
            "编辑项目" if draft.is_edit else "添加项目",
            "修改配置后会自动重新探测仓库状态"
            if draft.is_edit
            else "粘贴路径或选择一个本地 Git 仓库纳入管理",
        ),
        content=Column(
            width=T.DIALOG_WIDTH,
            tight=True,
            spacing=T.FIELD_GAP,
            controls=[
                # 每一行都是「左标签 + 右控件」：三个字段的标签右边缘、控件左边缘
                # 各自对齐成一条竖线。做法统一交给 cs-ui 的 FormRow —— 标签宽度、
                # 冒号、必填星号、说明缩进都在那一处定死。
                FormRow(
                    label="项目名称",
                    required=True,
                    control=TextField(
                        key="project-name",
                        hint_text="例如：cs-project-management",
                        value=draft.name,
                        autofocus=True,
                        dense=True,
                        on_change=lambda e: on_name(widgets.event_value(e) or ""),
                        on_submit=lambda _: on_save() if can_save else None,
                    ),
                ),
                FormRow(
                    label="本地路径",
                    required=True,
                    control=Row(
                        spacing=SPACE["2"],
                        vertical_alignment=CrossAxisAlignment.CENTER,
                        controls=[
                            TextField(
                                key="project-path",
                                value=draft.local_path,
                                expand=True,
                                dense=True,
                                prefix_icon=Icons.FOLDER_OUTLINED,
                                hint_text=r"D:\Projects\my-repo",
                                # 输入途中只清理明显的粘贴痕迹（见视图模型 change_path）
                                on_change=lambda e: on_path_change(
                                    widgets.event_value(e) or ""
                                ),
                                # 失焦事件不携带文本，整理以草稿里的当前值为准
                                on_blur=lambda _: on_path_commit(),
                                on_submit=submit_path,
                            ),
                            widgets.icon_action(
                                Icons.CONTENT_PASTE,
                                "从剪贴板粘贴路径",
                                on_paste_path,
                                tone=Tone.PRIMARY,
                                disabled=draft.saving,
                            ),
                            widgets.outlined(
                                "浏览",
                                icon=Icons.FOLDER_OPEN,
                                on_click=on_pick_path,
                                disabled=draft.saving,
                            ),
                        ],
                    ),
                    hint=_path_hint(draft),
                ),
                FormRow(
                    label="可见性",
                    control=SelectBox(
                        value=draft.permission.value,
                        options=[
                            ui.SelectOption(
                                key=Permission.PUBLIC.value, text=Permission.PUBLIC.label
                            ),
                            ui.SelectOption(
                                key=Permission.PRIVATE.value, text=Permission.PRIVATE.label
                            ),
                        ],
                        editable=False,
                        # None = 吃掉标签右边的全部宽度，不写死 480
                        width=None,
                        on_change=lambda e: on_permission(
                            Permission.parse(widgets.event_value(e))
                        ),
                    ).ui(),
                    hint=widgets.hint_row(Icons.INFO_OUTLINE, _PERMISSION_HINT),
                ),
                *([widgets.inline_error(draft.error)] if draft.error else []),
            ],
        ),
        actions=[
            widgets.text_btn("取消", on_click=on_cancel, disabled=draft.saving),
            widgets.filled(
                "保存中…" if draft.saving else "保存",
                icon=Icons.SAVE,
                on_click=on_save,
                disabled=not can_save,
            ),
        ],
    )


def delete_project_dialog(
    *,
    project: Project,
    on_confirm,
    on_cancel,
) -> ui.AlertDialog:
    return widgets.confirm_dialog(
        title_text="删除项目",
        message=f"确定要从列表中移除「{project.name}」吗？",
        confirm_label="删除",
        on_confirm=on_confirm,
        on_cancel=on_cancel,
        extra=widgets.flat_panel(
            Column(
                spacing=SPACE["1"],
                tight=True,
                controls=[
                    widgets.muted("仅移除台账记录，不会删除本地仓库或远程仓库。", max_lines=2),
                    widgets.muted(project.local_path, size=11, max_lines=2),
                ],
            )
        ),
    )


# --------------------------------------------------------------------------- 打包
def output_conflict_dialog(
    *,
    conflict: OutputConflict,
    on_confirm,
    on_cancel,
) -> ui.AlertDialog:
    """产物目录非空时的确认框（对应"提示是否删除"）。"""
    return widgets.confirm_dialog(
        title_text="产物目录已存在",
        message=(
            f"该目录下已有 {conflict.files} 个文件（约 {conflict.size}）。"
            "继续打包会把新旧文件混在一起，建议先删除再构建。"
        ),
        confirm_label="删除并打包",
        on_confirm=on_confirm,
        on_cancel=on_cancel,
        extra=widgets.flat_panel(
            Column(
                spacing=SPACE["1"],
                tight=True,
                controls=[
                    widgets.muted(conflict.path, size=11, max_lines=2),
                    *(
                        [
                            widgets.muted(
                                "包含："
                                + "、".join(conflict.top)
                                + ("…" if conflict.files > len(conflict.top) else ""),
                                size=11,
                                max_lines=2,
                            )
                        ]
                        if conflict.top
                        else []
                    ),
                ],
            )
        ),
    )


def output_locked_dialog(
    *,
    failure: RemovalFailure,
    on_retry,
    on_close,
) -> ui.AlertDialog:
    """删除产物目录失败（多半是文件被占用）。"""
    return ui.AlertDialog(
        modal=True,
        title=_dialog_title(
            Icons.FOLDER_OFF,
            "产物目录删除失败",
            "文件可能正被其他程序占用",
            tone=Tone.DANGER,
        ),
        content=Column(
            width=T.DIALOG_WIDTH,
            tight=True,
            spacing=T.FIELD_GAP,
            controls=[
                T.text(failure.reason, level=T.TextLevel.BODY),
                widgets.flat_panel(
                    Column(
                        spacing=SPACE["1"],
                        tight=True,
                        controls=[
                            widgets.muted(failure.path, size=11, max_lines=2),
                            *(
                                [widgets.muted(f"仍剩 {failure.remaining} 个文件未删除", size=11)]
                                if failure.remaining
                                else []
                            ),
                            *(
                                [
                                    widgets.muted(
                                        f"被阻塞：{failure.blocked_path}", size=11, max_lines=3
                                    )
                                ]
                                if failure.blocked_path
                                else []
                            ),
                        ],
                    )
                ),
                widgets.hint_row(
                    Icons.LIGHTBULB_OUTLINE,
                    "最常见的原因是这个目录里的程序还在运行；关掉它（以及停在里面的"
                    "资源管理器窗口）后点「重试删除」即可。",
                    tone=Tone.WARNING,
                ),
            ],
        ),
        actions=[
            widgets.text_btn("取消", on_click=on_close),
            widgets.filled("重试删除", icon=Icons.RESTART_ALT, on_click=on_retry),
        ],
    )
