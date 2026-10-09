"""对话框构件。

都是纯函数：接收当前状态、返回 ``ft.AlertDialog``；由持有状态的视图通过
``ft.use_dialog`` 渲染，因此对话框内容随状态实时刷新。所有回调都把意图报给视图模型，
这里不做任何判断。

对话框统一走 :func:`view.widgets.confirm_dialog` 或同一套头部结构（圆角色块图标 +
标题 + 副标题），保证"弹出来的东西"看起来是同一个系统里的。
"""

from __future__ import annotations

import flet as ft

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
    return ft.Row(
        spacing=T.SPACE_MD,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.Container(
                width=36,
                height=36,
                border_radius=T.RADIUS_MD,
                bgcolor=style.container,
                alignment=ft.Alignment.CENTER,
                content=ft.Icon(icon, size=18, color=style.accent),
            ),
            ft.Column(
                spacing=0,
                tight=True,
                expand=True,
                controls=[
                    T.text(
                        title_text,
                        level=T.TextLevel.TITLE,
                        size=17,
                        weight=ft.FontWeight.W_600,
                    ),
                    widgets.muted(subtitle, size=12, max_lines=2),
                ],
            ),
        ],
    )


def _path_hint(draft: ProjectDraft) -> ft.Control:
    """路径输入框下的状态行：给粘贴进来的路径一个即时反馈。"""
    text = draft.local_path.strip()
    if not text or draft.checked_text != text:
        return widgets.hint_row(ft.Icons.CONTENT_PASTE, _PATH_PENDING_HINT, tone=Tone.NEUTRAL)
    if draft.path_issue is None:
        return widgets.hint_row(
            ft.Icons.CHECK_CIRCLE_OUTLINE, "已识别到 Git 仓库", tone=Tone.SUCCESS
        )
    return widgets.hint_row(ft.Icons.FOLDER_OFF, draft.path_issue, tone=Tone.WARNING)


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
) -> ft.AlertDialog:
    """新增 / 编辑项目。"""
    can_save = draft.can_save

    def submit_path(_=None) -> None:
        """路径框里回车：先整理输入，再按需保存。"""
        on_path_commit()
        if can_save:
            on_save()

    return ft.AlertDialog(
        modal=True,
        bgcolor=T.CARD_COLOR,
        shape=ft.RoundedRectangleBorder(radius=T.RADIUS_DIALOG),
        title=_dialog_title(
            ft.Icons.EDIT_OUTLINED if draft.is_edit else ft.Icons.ADD,
            "编辑项目" if draft.is_edit else "添加项目",
            "修改配置后会自动重新探测仓库状态"
            if draft.is_edit
            else "粘贴路径或选择一个本地 Git 仓库纳入管理",
        ),
        content=ft.Column(
            width=T.DIALOG_WIDTH,
            tight=True,
            spacing=T.FIELD_GAP,
            controls=[
                ft.TextField(
                    key="project-name",
                    label="项目名称",
                    hint_text="例如：cs-project-management",
                    value=draft.name,
                    autofocus=True,
                    border=T.field_border(),
                    fill_color=widgets.field_fill(),
                    filled=True,
                    on_change=lambda e: on_name(widgets.event_value(e) or ""),
                    on_submit=lambda _: on_save() if can_save else None,
                ),
                ft.Row(
                    spacing=T.SPACE_SM,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.TextField(
                            key="project-path",
                            label="本地路径",
                            value=draft.local_path,
                            expand=True,
                            border=T.field_border(),
                            fill_color=widgets.field_fill(),
                            filled=True,
                            prefix_icon=ft.Icons.FOLDER_OUTLINED,
                            hint_text=r"粘贴路径，如 D:\Projects\my-repo",
                            # 输入途中只清理明显的粘贴痕迹（见视图模型 change_path）
                            on_change=lambda e: on_path_change(widgets.event_value(e) or ""),
                            # 失焦事件不携带文本，整理以草稿里的当前值为准
                            on_blur=lambda _: on_path_commit(),
                            on_submit=submit_path,
                        ),
                        widgets.icon_action(
                            ft.Icons.CONTENT_PASTE,
                            "从剪贴板粘贴路径",
                            on_paste_path,
                            tone=Tone.PRIMARY,
                            disabled=draft.saving,
                        ),
                        widgets.outlined(
                            "浏览",
                            icon=ft.Icons.FOLDER_OPEN,
                            on_click=on_pick_path,
                            disabled=draft.saving,
                        ),
                    ],
                ),
                _path_hint(draft),
                ft.Dropdown(
                    key="project-permission",
                    label="可见性",
                    value=draft.permission.value,
                    border=T.field_border(),
                    fill_color=widgets.field_fill(),
                    filled=True,
                    options=[
                        ft.dropdown.Option(Permission.PUBLIC.value, Permission.PUBLIC.label),
                        ft.dropdown.Option(Permission.PRIVATE.value, Permission.PRIVATE.label),
                    ],
                    on_select=lambda e: on_permission(Permission.parse(widgets.event_value(e))),
                ),
                widgets.hint_row(ft.Icons.INFO_OUTLINE, _PERMISSION_HINT),
                *([widgets.inline_error(draft.error)] if draft.error else []),
            ],
        ),
        actions=[
            widgets.text_btn("取消", on_click=on_cancel, disabled=draft.saving),
            widgets.filled(
                "保存中…" if draft.saving else "保存",
                icon=ft.Icons.SAVE,
                on_click=on_save,
                disabled=not can_save,
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )


def delete_project_dialog(
    *,
    project: Project,
    on_confirm,
    on_cancel,
) -> ft.AlertDialog:
    return widgets.confirm_dialog(
        title_text="删除项目",
        message=f"确定要从列表中移除「{project.name}」吗？",
        confirm_label="删除",
        on_confirm=on_confirm,
        on_cancel=on_cancel,
        extra=widgets.flat_panel(
            ft.Column(
                spacing=T.SPACE_XS,
                tight=True,
                controls=[
                    widgets.muted(
                        "仅移除台账记录，不会删除本地仓库或远程仓库。", size=12, max_lines=2
                    ),
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
) -> ft.AlertDialog:
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
            ft.Column(
                spacing=T.SPACE_XS,
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
) -> ft.AlertDialog:
    """删除产物目录失败（多半是文件被占用）。"""
    return ft.AlertDialog(
        modal=True,
        bgcolor=T.CARD_COLOR,
        shape=ft.RoundedRectangleBorder(radius=T.RADIUS_DIALOG),
        title=_dialog_title(
            ft.Icons.FOLDER_OFF,
            "产物目录删除失败",
            "文件可能正被其他程序占用",
            tone=Tone.DANGER,
        ),
        content=ft.Column(
            width=T.DIALOG_WIDTH,
            tight=True,
            spacing=T.SPACE_MD,
            controls=[
                T.text(failure.reason, level=T.TextLevel.BODY),
                widgets.flat_panel(
                    ft.Column(
                        spacing=T.SPACE_XS,
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
                    ft.Icons.LIGHTBULB_OUTLINE,
                    "最常见的原因是这个目录里的程序还在运行；关掉它（以及停在里面的"
                    "资源管理器窗口）后点「重试删除」即可。",
                    tone=Tone.WARNING,
                ),
            ],
        ),
        actions=[
            widgets.text_btn("取消", on_click=on_close),
            widgets.filled("重试删除", icon=ft.Icons.RESTART_ALT, on_click=on_retry),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
