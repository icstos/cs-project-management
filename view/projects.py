"""项目管理页：搜索、筛选、排序与增删改。

视图只做两件事：**读取状态渲染** 和 **把用户动作交给视图模型**。
过滤与排序的结果由状态自身派生（``state.visible``），因此界面永远不会出现
"筛了但没生效"的中间态。

卡片是页面里最重的视觉元素，因此承担了"悬停轻微抬起"的反馈：悬停中的卡片 id
放在组件本地 ``use_state`` 里，只有投影变化，不触碰任何业务状态。
"""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from models.dtos import Project
from models.enums import Tone
from view import design as T
from view import widgets
from view.dialogs import delete_project_dialog, project_form_dialog
from view.guard import guarded
from view.view_platform import (
    FletPlatform,
    use_notices,
    use_platform_requests,
)
from viewmodel.formatting import format_relative
from viewmodel.projects_vm import ProjectFilter, ProjectsViewModel, SortKey

#: 12 列栅格：手机一列、中等窗口两列、宽窗口三列
CARD_COL = {"xs": 12, "md": 6, "xl": 4}
_SKELETON_CARDS = 6


@guarded
def ProjectsView(
    *,
    vm: ProjectsViewModel,
    platform: FletPlatform,
    on_refresh: Callable[[], None],
) -> ft.Control:
    page = ft.context.page
    state = vm.state
    use_notices(page, vm)
    use_platform_requests(platform, vm)

    # 悬停中的卡片 id —— 纯展示状态，用来把投影从"静止"抬到"悬停"
    hovered, set_hovered = ft.use_state(None)

    # 路径一变就核验一次：手输、粘贴、浏览选目录、打开编辑对话框都汇到这里。
    # 核验本身在线程池里跑（断开的网络盘会让 exists() 阻塞数秒）。
    current_path = state.draft.local_path if state.draft is not None else ""
    ft.use_effect(lambda: page.run_task(vm.verify_path, current_path), [current_path])

    ft.use_dialog(
        project_form_dialog(
            draft=state.draft,
            on_name=vm.change_name,
            on_permission=vm.change_permission,
            on_path_change=vm.change_path,
            on_path_commit=vm.commit_path,
            on_paste_path=vm.request_paste,
            on_pick_path=vm.request_pick_directory,
            on_cancel=vm.close_form,
            on_save=lambda: page.run_task(vm.save),
        )
        if state.draft is not None
        else None
    )
    ft.use_dialog(
        delete_project_dialog(
            project=state.pending_delete,
            on_confirm=lambda _: page.run_task(vm.confirm_delete),
            on_cancel=lambda _: vm.cancel_delete(),
        )
        if state.pending_delete is not None
        else None
    )

    return widgets.page_shell(
        header=widgets.page_header(
            "项目管理",
            "维护本地 Git 仓库台账，自动探测远程配置、分支与变更状态",
            actions=[
                widgets.outlined(
                    "刷新状态",
                    icon=ft.Icons.SYNC,
                    disabled=state.busy,
                    on_click=lambda _: on_refresh(),
                ),
                widgets.filled("添加项目", icon=ft.Icons.ADD, on_click=lambda _: vm.start_create()),
            ],
        ),
        body=ft.Column(
            expand=True,
            spacing=T.SPACE_LG,
            controls=[
                _toolbar(state=state, vm=vm),
                _body(
                    page=page,
                    vm=vm,
                    hovered=hovered,
                    on_hover=lambda project, entering: set_hovered(
                        project.id if entering else None
                    ),
                ),
            ],
        ),
    )


# --------------------------------------------------------------------------- 构件
def _toolbar(*, state, vm: ProjectsViewModel) -> ft.Control:
    counts = state.counts
    projects = state.projects
    matched = len(state.visible)
    # 注意：Row(wrap=True) 的子项不能带 expand（Flutter 会因父数据不匹配而报错），
    # 所以把「需要吃掉剩余宽度」的元素放在不换行的第一行。
    return ft.Column(
        spacing=T.SPACE_MD,
        tight=True,
        controls=[
            ft.Row(
                spacing=T.SPACE_SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Container(
                        width=320,
                        content=ft.TextField(
                            key="project-search",
                            hint_text="搜索名称或路径",
                            prefix_icon=ft.Icons.SEARCH,
                            value=state.query,
                            border=T.field_border(),
                            fill_color=widgets.field_fill(),
                            dense=True,
                            filled=True,
                            expand=True,
                            on_change=lambda e: vm.set_query(widgets.event_value(e) or ""),
                        ),
                    ),
                    *(
                        [
                            widgets.icon_action(
                                ft.Icons.CLOSE,
                                "清空搜索",
                                lambda _: vm.clear_query(),
                                size=16,
                            )
                        ]
                        if state.query
                        else []
                    ),
                    ft.Container(expand=True),
                    T.text(
                        f"显示 {matched}/{len(projects)} 个"
                        if state.filtered
                        else f"共 {len(projects)} 个项目",
                        level=T.TextLevel.CAPTION,
                        size=11,
                        color=T.MUTED_TEXT,
                    ),
                    ft.Container(
                        width=156,
                        content=ft.Dropdown(
                            value=state.sort_key.value,
                            dense=True,
                            filled=True,
                            fill_color=widgets.field_fill(),
                            border=T.field_border(),
                            options=[
                                ft.dropdown.Option(item.value, item.label) for item in SortKey
                            ],
                            on_select=lambda e: vm.set_sort(SortKey(widgets.event_value(e))),
                        ),
                    ),
                ],
            ),
            ft.Row(
                spacing=T.SPACE_SM,
                run_spacing=T.SPACE_SM,
                wrap=True,
                controls=[
                    widgets.filter_chip(
                        f"{item.label} {counts[item]}",
                        selected=state.active_filter is item,
                        on_select=lambda _, target=item: vm.set_filter(target),
                    )
                    for item in ProjectFilter
                ],
            ),
        ],
    )


def _body(*, page: ft.Page, vm: ProjectsViewModel, hovered, on_hover) -> ft.Control:
    state = vm.state
    if state.busy and not state.projects:
        # 骨架屏：结构与真实卡片一致，避免首屏出现大片空白
        return ft.ResponsiveRow(
            spacing=T.GRID_GUTTER,
            run_spacing=T.GRID_GUTTER,
            controls=[widgets.skeleton_card(col=CARD_COL) for _ in range(_SKELETON_CARDS)],
        )
    if not state.projects:
        return widgets.empty_state(
            ft.Icons.FOLDER_OFF,
            "还没有项目",
            "添加一个本地 Git 仓库，开始跟踪分支、变更与提交统计",
            action=widgets.filled(
                "添加项目", icon=ft.Icons.ADD, on_click=lambda _: vm.start_create()
            ),
        )
    if not state.visible:
        return widgets.empty_state(
            ft.Icons.SEARCH_OFF,
            "没有匹配的项目",
            "换个关键词，或把筛选条件切回「全部」",
        )

    return ft.Column(
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        spacing=T.GRID_GUTTER,
        controls=[
            ft.ResponsiveRow(
                spacing=T.GRID_GUTTER,
                run_spacing=T.GRID_GUTTER,
                controls=[
                    _project_card(
                        page=page,
                        vm=vm,
                        project=project,
                        hovered=hovered == project.id,
                        on_hover=on_hover,
                    )
                    for project in state.visible
                ],
            )
        ],
    )


def _project_card(
    *,
    page: ft.Page,
    vm: ProjectsViewModel,
    project: Project,
    hovered: bool,
    on_hover,
) -> ft.Container:
    warnings = project.warnings
    dirty_text = f"{project.changed_files} 个文件待提交" if project.changed_files else "工作区干净"
    refreshing = vm.state.busy_project == project.id

    def handle_hover(event) -> None:
        entering = str(widgets.event_value(event)).lower() == "true"
        on_hover(project, entering)

    return widgets.surface(
        col=CARD_COL,
        key=f"project-{project.id}",
        hovered=hovered,
        on_hover=handle_hover,
        content=ft.Column(
            spacing=T.SPACE_MD,
            tight=True,
            controls=[
                # ---- 标题行：名称 / 路径 / 可见性
                ft.Row(
                    spacing=T.SPACE_MD,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    controls=[
                        ft.Column(
                            spacing=T.SPACE_XXS,
                            tight=True,
                            expand=True,
                            controls=[
                                T.text(
                                    project.name,
                                    level=T.TextLevel.TITLE,
                                    size=15,
                                    weight=ft.FontWeight.W_600,
                                    max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                ),
                                widgets.muted(project.local_path, size=11, max_lines=1),
                            ],
                        ),
                        widgets.permission_pill(project.permission),
                    ],
                ),
                # ---- 状态角标组
                ft.Row(
                    spacing=T.SPACE_SM,
                    wrap=True,
                    run_spacing=T.SPACE_SM,
                    controls=[
                        *(
                            [widgets.pill(project.branch, icon=ft.Icons.ALT_ROUTE, dense=True)]
                            if project.branch
                            else []
                        ),
                        widgets.flag_pill("已配置远程", project.has_remote, bad_label="未配置远程"),
                        widgets.flag_pill("工作区干净", project.is_clean, bad_label="有未提交变更"),
                        widgets.flag_pill(
                            "含 .gitignore", project.has_gitignore, bad_label="缺少 .gitignore"
                        ),
                        *(
                            [
                                widgets.pill(
                                    f"{project.ahead} 个提交待推送",
                                    tone=Tone.INFO,
                                    icon=ft.Icons.UPLOAD,
                                    dense=True,
                                )
                            ]
                            if project.ahead
                            else []
                        ),
                        *(
                            [
                                widgets.pill(
                                    f"{project.behind} 个提交待拉取",
                                    tone=Tone.WARNING,
                                    icon=ft.Icons.DOWNLOAD,
                                    dense=True,
                                )
                            ]
                            if project.behind
                            else []
                        ),
                    ],
                ),
                *(
                    [
                        widgets.flat_panel(
                            widgets.hint_row(
                                ft.Icons.WARNING_AMBER_ROUNDED,
                                "；".join(warnings),
                                tone=Tone.WARNING,
                            ),
                            padding=T.SPACE_MD,
                        )
                    ]
                    if warnings
                    else []
                ),
                widgets.divider(),
                # ---- 页脚：变更摘要 + 行内操作
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Column(
                            spacing=0,
                            tight=True,
                            controls=[
                                T.text(
                                    dirty_text,
                                    level=T.TextLevel.LABEL,
                                    size=12,
                                    color=(
                                        T.tone_style(Tone.WARNING).accent
                                        if project.changed_files
                                        else T.MUTED_TEXT
                                    ),
                                ),
                                widgets.muted(
                                    f"更新于 {format_relative(project.updated_at)}", size=11
                                ),
                            ],
                        ),
                        ft.Row(
                            spacing=0,
                            tight=True,
                            controls=[
                                ft.ProgressRing(width=16, height=16, stroke_width=2)
                                if refreshing
                                else widgets.icon_action(
                                    ft.Icons.REFRESH,
                                    "刷新该仓库状态",
                                    lambda _, p=project: page.run_task(vm.refresh_one, p),
                                ),
                                widgets.icon_action(
                                    ft.Icons.EDIT_OUTLINED,
                                    "编辑",
                                    lambda _, p=project: vm.start_edit(p),
                                ),
                                ft.PopupMenuButton(
                                    tooltip="更多操作",
                                    icon=ft.Icons.MORE_VERT,
                                    icon_size=T.ICON_MD,
                                    icon_color=T.MUTED_TEXT,
                                    items=[
                                        ft.PopupMenuItem(
                                            content=ft.Text("在文件管理器中打开"),
                                            icon=ft.Icons.FOLDER_OPEN,
                                            on_click=lambda _, p=project: page.run_task(
                                                vm.reveal, p
                                            ),
                                        ),
                                        ft.PopupMenuItem(
                                            content=ft.Text("复制本地路径"),
                                            icon=ft.Icons.CONTENT_COPY,
                                            on_click=lambda _, p=project: vm.request_copy_path(p),
                                        ),
                                    ],
                                ),
                                widgets.icon_action(
                                    ft.Icons.DELETE_OUTLINE,
                                    "移除",
                                    lambda _, p=project: vm.ask_delete(p),
                                    tone=Tone.DANGER,
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        ),
    )
