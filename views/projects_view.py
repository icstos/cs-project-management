"""项目管理视图：搜索、筛选、排序与增删改。

数据来自 AppShell（单一数据源），本视图只负责展示与上报意图；
表单弹窗用 ``ft.use_dialog`` 承载，内容随草稿状态实时刷新。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from enum import StrEnum

import flet as ft

from core import paths, shell
from core import theme as T
from core.paths import problem
from core.tasks import offload
from models.dto import Project
from services.project_service import ProjectService
from views import ui
from views.dialogs import PathCheck, ProjectDraft, delete_project_dialog, project_form_dialog
from views.guard import guarded

logger = logging.getLogger(__name__)

CARD_COL = {"xs": 12, "md": 6, "xl": 4}


class ProjectFilter(StrEnum):
    ALL = "all"
    DIRTY = "dirty"
    ATTENTION = "attention"

    @property
    def label(self) -> str:
        match self:
            case ProjectFilter.DIRTY:
                return "有本地变更"
            case ProjectFilter.ATTENTION:
                return "需关注"
            case _:
                return "全部"


class SortKey(StrEnum):
    NAME = "name"
    UPDATED = "updated"
    DIRTY = "dirty"

    @property
    def label(self) -> str:
        match self:
            case SortKey.UPDATED:
                return "最近更新"
            case SortKey.DIRTY:
                return "待提交文件"
            case _:
                return "名称"


@guarded
def ProjectsView(
    *,
    projects: list[Project],
    service: ProjectService,
    picker: ft.FilePicker,
    busy: bool,
    new_request: int,
    refresh: Callable[..., object],
):
    page = ft.context.page
    clipboard = ft.use_ref(ft.Clipboard).current

    query, set_query = ft.use_state("")
    active_filter, set_filter = ft.use_state(ProjectFilter.ALL)
    sort_key, set_sort = ft.use_state(SortKey.NAME)
    draft, set_draft = ft.use_state(None)
    path_check, set_path_check = ft.use_state(None)
    form_error, set_form_error = ft.use_state(None)
    saving, set_saving = ft.use_state(False)
    pending_delete, set_pending_delete = ft.use_state(None)
    busy_project, set_busy_project = ft.use_state(None)

    # 搜索框是受控输入：文本的唯一真相是 query 状态。
    # 不要在渲染后回写控件属性（已下发的控件会被标记为 frozen 并抛异常），
    # 清空搜索只需 set_query("")。
    visible = ft.use_memo(
        lambda: _shape(projects, query, active_filter, sort_key),
        [projects, query, active_filter, sort_key],
    )

    # ------------------------------------------------------------------ 表单
    def open_create() -> None:
        set_form_error(None)
        set_path_check(None)
        set_draft(ProjectDraft.blank())

    def open_edit(project: Project) -> None:
        set_form_error(None)
        set_path_check(None)
        set_draft(ProjectDraft.from_project(project))

    def close_form() -> None:
        set_draft(None)
        set_path_check(None)
        set_form_error(None)

    def open_new_on_request() -> None:
        if new_request:
            open_create()

    ft.use_effect(open_new_on_request, [new_request])

    def change_draft(**changes: object) -> None:
        set_draft(lambda current: current.with_fields(**changes) if current else current)

    # ------------------------------------------------------------------ 路径输入
    # 路径既可以点「浏览」选，也可以直接粘贴：资源管理器的「复制为路径」会带一层
    # 引号，浏览器地址栏复制出来的是 file:///D:/repo，形态都由 core.paths 收敛。
    # 核验丢进线程池——断开的网络盘会让 stat 阻塞数秒，压在界面线程上就是卡死。
    async def verify_path(text: str) -> None:
        text = text.strip()
        if not text:
            return
        set_path_check(PathCheck(text, await offload(problem, text)))

    # 路径一变就核验一次：手输、粘贴、浏览选目录、打开编辑对话框都汇到这里
    current_path = draft.local_path if draft is not None else ""
    ft.use_effect(lambda: page.run_task(verify_path, current_path), [current_path])

    def change_path(raw: str) -> None:
        """输入框变化：立刻整理明显的粘贴痕迹（包裹引号 / file: 链接 / 换行）。

        只处理"绝不可能是手输中间态"的特征；正斜杠与尾部反斜杠留给
        ``commit_path``，否则用户敲到 ``D:\\`` 时字符会被当场吃掉。
        """
        text = paths.normalize(raw) if paths.has_paste_marks(raw) else raw.strip()
        set_draft(lambda current: _with_path(current, text))

    def commit_path() -> None:
        """失焦 / 回车：把分隔符、盘符大小写、多余的反斜杠统一成本机写法。

        取值以草稿为准——blur 事件不携带文本，而 change 已经把最新值写进来了。
        """
        if draft is None:
            return
        text = paths.normalize(draft.local_path)
        if text and text != draft.local_path:
            set_draft(lambda current: _with_path(current, text))

    async def clipboard_path() -> str:
        """取剪贴板里的路径：优先「复制的文件夹」，其次纯文本。"""
        try:
            picked = await clipboard.get_files()
        except Exception:  # 平台不支持，或剪贴板里放的本来就不是文件
            picked = []
        for item in picked:
            cleaned = paths.normalize(item)
            if cleaned:
                return cleaned
        try:
            return paths.normalize(await clipboard.get() or "")
        except Exception as exc:
            logger.warning("读取剪贴板失败：%s", exc)
            ui.toast(page, f"读取剪贴板失败：{exc}", tone=T.Tone.DANGER)
            return ""

    async def paste_path(_=None) -> None:
        """从剪贴板填入路径。

        在资源管理器里复制文件夹时，剪贴板里放的是「文件对象」而不是文本，
        输入框里直接 Ctrl+V 未必粘得出来，所以先按文件列表取、再退回纯文本。
        """
        text = await clipboard_path()
        if not text:
            ui.toast(page, "剪贴板里没有可用的路径", tone=T.Tone.WARNING)
            return
        logger.debug("从剪贴板填入路径：%s", text)
        set_draft(lambda current: _with_path(current, text))

    async def pick_directory(_) -> None:
        selected = await picker.get_directory_path(dialog_title="选择 Git 仓库目录")
        if selected:
            logger.debug("浏览选择目录：%s", selected)
            set_draft(lambda current: _with_path(current, selected))
            set_form_error(None)

    async def save(_) -> None:
        if draft is None:
            return
        set_saving(True)
        set_form_error(None)
        try:
            if draft.is_edit:
                await service.update(
                    draft.project_id,
                    name=draft.name,
                    local_path=draft.local_path,
                    permission=draft.permission,
                )
                ui.toast(page, "项目已更新")
            else:
                await service.create(
                    name=draft.name,
                    local_path=draft.local_path,
                    permission=draft.permission,
                )
                ui.toast(page, "项目已添加")
            close_form()
            await refresh()
        except (ValueError, RuntimeError) as exc:
            logger.warning(
                "保存项目失败（%s，路径=%r）：%s",
                "编辑" if draft.is_edit else "新增",
                draft.local_path,
                exc,
            )
            set_form_error(str(exc))
        finally:
            set_saving(False)

    async def confirm_delete(_) -> None:
        project = pending_delete
        if project is None:
            return
        try:
            await service.delete(project.id)
            set_pending_delete(None)
            ui.toast(page, f"已移除「{project.name}」")
            await refresh()
        except (ValueError, RuntimeError) as exc:
            logger.warning("删除项目失败（#%d「%s」）：%s", project.id, project.name, exc)
            set_pending_delete(None)
            ui.toast(page, str(exc), tone=T.Tone.DANGER)

    # ------------------------------------------------------------------ 单项操作
    async def refresh_one(project: Project) -> None:
        set_busy_project(project.id)
        try:
            logger.debug("重新探测项目「%s」（%s）", project.name, project.local_path)
            await service.refresh(project.id)
            await refresh()
        except (ValueError, RuntimeError) as exc:
            logger.warning("重新探测项目「%s」失败：%s", project.name, exc)
            ui.toast(page, str(exc), tone=T.Tone.DANGER)
        finally:
            set_busy_project(None)

    def open_in_explorer(project: Project) -> None:
        ok, reason = shell.reveal(project.local_path)
        if not ok:
            ui.toast(page, reason, tone=T.Tone.DANGER)

    def copy_path(project: Project) -> None:
        try:
            clipboard.set(project.local_path)
            ui.toast(page, "路径已复制到剪贴板", tone=T.Tone.INFO)
        except Exception as exc:
            logger.warning("复制路径到剪贴板失败：%s", exc)
            ui.toast(page, f"复制失败：{exc}", tone=T.Tone.DANGER)

    def clear_search(_=None) -> None:
        set_query("")

    # ------------------------------------------------------------------ 弹窗
    ft.use_dialog(
        project_form_dialog(
            draft=draft,
            error=form_error,
            path_check=path_check,
            saving=saving,
            on_change=change_draft,
            on_path_change=change_path,
            on_path_commit=commit_path,
            on_paste_path=paste_path,
            on_pick_path=pick_directory,
            on_cancel=close_form,
            on_save=save,
        )
        if draft is not None
        else None
    )
    ft.use_dialog(
        delete_project_dialog(
            project=pending_delete,
            on_confirm=confirm_delete,
            on_cancel=lambda _: set_pending_delete(None),
        )
        if pending_delete is not None
        else None
    )

    return ui.page_shell(
        header=ui.page_header(
            "项目管理",
            "维护本地 Git 仓库台账，自动探测远程配置、分支与变更状态",
            actions=[
                ui.outlined(
                    "刷新状态",
                    icon=ft.Icons.SYNC,
                    disabled=busy,
                    on_click=lambda _: page.run_task(refresh, True),
                ),
                ui.filled("添加项目", icon=ft.Icons.ADD, on_click=lambda _: open_create()),
            ],
        ),
        body=ft.Column(
            expand=True,
            spacing=T.SPACE_MD,
            controls=[
                _toolbar(
                    query=query,
                    on_query=set_query,
                    on_clear=clear_search,
                    active=active_filter,
                    on_filter=set_filter,
                    sort_key=sort_key,
                    on_sort=set_sort,
                    projects=projects,
                    matched=len(visible),
                ),
                _body(
                    page=page,
                    projects=projects,
                    visible=visible,
                    busy=busy,
                    busy_project=busy_project,
                    on_create=open_create,
                    on_edit=open_edit,
                    on_delete=set_pending_delete,
                    on_refresh=refresh_one,
                    on_reveal=open_in_explorer,
                    on_copy=copy_path,
                ),
            ],
        ),
    )


# --------------------------------------------------------------------------- 构件
def _toolbar(
    *,
    query: str,
    on_query,
    on_clear,
    active: ProjectFilter,
    on_filter,
    sort_key: SortKey,
    on_sort,
    projects: list[Project],
    matched: int,
) -> ft.Control:
    counts = {
        ProjectFilter.ALL: len(projects),
        ProjectFilter.DIRTY: sum(1 for p in projects if p.has_local_changes),
        ProjectFilter.ATTENTION: sum(1 for p in projects if p.warnings),
    }
    # 注意：Row(wrap=True) 的子项不能带 expand（Flutter 会因父数据不匹配而报错），
    # 所以把「需要吃掉剩余宽度」的元素放在不换行的第一行。
    return ft.Column(
        spacing=T.SPACE_SM,
        tight=True,
        controls=[
            ft.Row(
                spacing=T.SPACE_SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Container(
                        width=300,
                        content=ft.TextField(
                            key="project-search",
                            hint_text="搜索名称或路径",
                            prefix_icon=ft.Icons.SEARCH,
                            value=query,
                            border=T.field_border(),
                            dense=True,
                            expand=True,
                            on_change=lambda e: on_query(ui.event_value(e) or ""),
                        ),
                    ),
                    *(
                        [
                            ft.IconButton(
                                icon=ft.Icons.CLOSE,
                                tooltip="清空搜索",
                                icon_size=18,
                                on_click=on_clear,
                            )
                        ]
                        if query
                        else []
                    ),
                    ft.Container(expand=True),
                    ft.Text(
                        f"显示 {matched}/{len(projects)} 个"
                        if query or active is not ProjectFilter.ALL
                        else f"共 {len(projects)} 个项目",
                        size=11,
                        color=T.MUTED_TEXT,
                    ),
                    ft.Dropdown(
                        width=150,
                        value=sort_key.value,
                        dense=True,
                        border=T.field_border(),
                        options=[ft.dropdown.Option(item.value, item.label) for item in SortKey],
                        on_select=lambda e: on_sort(SortKey(ui.event_value(e))),
                    ),
                ],
            ),
            ft.Row(
                spacing=T.SPACE_SM,
                run_spacing=T.SPACE_SM,
                wrap=True,
                controls=[
                    ft.Chip(
                        label=ft.Text(f"{item.label} {counts[item]}"),
                        selected=active is item,
                        show_checkmark=False,
                        on_select=lambda _, target=item: on_filter(target),
                    )
                    for item in ProjectFilter
                ],
            ),
        ],
    )


def _body(
    *,
    page: ft.Page,
    projects: list[Project],
    visible: list[Project],
    busy: bool,
    busy_project: int | None,
    on_create,
    on_edit,
    on_delete,
    on_refresh,
    on_reveal,
    on_copy,
) -> ft.Control:
    if busy and not projects:
        return ui.busy_block("正在读取项目列表…")
    if not projects:
        return ui.empty_state(
            ft.Icons.FOLDER_OFF,
            "还没有项目",
            "添加一个本地 Git 仓库，开始跟踪分支、变更与提交统计",
            action=ui.filled("添加项目", icon=ft.Icons.ADD, on_click=lambda _: on_create()),
        )
    if not visible:
        return ui.empty_state(
            ft.Icons.SEARCH_OFF,
            "没有匹配的项目",
            "换个关键词，或把筛选条件切回「全部」",
        )

    return ft.Column(
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        spacing=T.SPACE_MD,
        controls=[
            ft.ResponsiveRow(
                spacing=T.SPACE_MD,
                run_spacing=T.SPACE_MD,
                controls=[
                    _project_card(
                        project,
                        refreshing=busy_project == project.id,
                        on_edit=on_edit,
                        on_delete=on_delete,
                        on_refresh=lambda p: page.run_task(on_refresh, p),
                        on_reveal=on_reveal,
                        on_copy=on_copy,
                    )
                    for project in visible
                ],
            )
        ],
    )


def _project_card(
    project: Project,
    *,
    refreshing: bool,
    on_edit,
    on_delete,
    on_refresh,
    on_reveal,
    on_copy,
) -> ft.Container:
    warnings = project.warnings
    dirty_text = f"{project.changed_files} 个文件待提交" if project.changed_files else "工作区干净"

    return ui.surface(
        col=CARD_COL,
        key=f"project-{project.id}",
        content=ft.Column(
            spacing=T.SPACE_SM,
            tight=True,
            controls=[
                ft.Row(
                    spacing=T.SPACE_SM,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    controls=[
                        ft.Column(
                            spacing=T.SPACE_XXS,
                            tight=True,
                            expand=True,
                            controls=[
                                ft.Text(
                                    project.name,
                                    size=16,
                                    weight=ft.FontWeight.W_600,
                                    max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                ),
                                ui.muted(project.local_path, size=11, max_lines=1),
                            ],
                        ),
                        ui.permission_pill(project.permission),
                    ],
                ),
                ft.Row(
                    spacing=T.SPACE_SM,
                    wrap=True,
                    run_spacing=T.SPACE_SM,
                    controls=[
                        *(
                            [ui.pill(project.branch, icon=ft.Icons.ALT_ROUTE, dense=True)]
                            if project.branch
                            else []
                        ),
                        ui.flag_pill("已配置远程", project.has_remote, bad_label="未配置远程"),
                        ui.flag_pill("工作区干净", project.is_clean, bad_label="有未提交变更"),
                        ui.flag_pill(
                            "含 .gitignore", project.has_gitignore, bad_label="缺少 .gitignore"
                        ),
                        *(
                            [
                                ui.pill(
                                    f"{project.ahead} 个提交待推送",
                                    tone=T.Tone.INFO,
                                    icon=ft.Icons.UPLOAD,
                                    dense=True,
                                )
                            ]
                            if project.ahead
                            else []
                        ),
                        *(
                            [
                                ui.pill(
                                    f"{project.behind} 个提交待拉取",
                                    tone=T.Tone.WARNING,
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
                        ui.flat_panel(
                            ui.hint_row(
                                ft.Icons.WARNING_AMBER_ROUNDED,
                                "；".join(warnings),
                                tone=T.Tone.WARNING,
                            ),
                            padding=T.SPACE_SM,
                        )
                    ]
                    if warnings
                    else []
                ),
                ui.divider(),
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Column(
                            spacing=0,
                            tight=True,
                            controls=[
                                ft.Text(
                                    dirty_text,
                                    size=12,
                                    color=(
                                        T.tone_style(T.Tone.WARNING).accent
                                        if project.changed_files
                                        else T.MUTED_TEXT
                                    ),
                                ),
                                ui.muted(
                                    f"更新于 {ui.format_relative(project.updated_at)}", size=11
                                ),
                            ],
                        ),
                        ft.Row(
                            spacing=0,
                            tight=True,
                            controls=[
                                ft.ProgressRing(width=16, height=16, stroke_width=2)
                                if refreshing
                                else ui.icon_action(
                                    ft.Icons.REFRESH,
                                    "刷新该仓库状态",
                                    on_refresh,
                                ),
                                ui.icon_action(
                                    ft.Icons.EDIT_OUTLINED,
                                    "编辑",
                                    lambda _, p=project: on_edit(p),
                                ),
                                ft.PopupMenuButton(
                                    tooltip="更多操作",
                                    items=[
                                        ft.PopupMenuItem(
                                            content=ft.Text("在文件管理器中打开"),
                                            icon=ft.Icons.FOLDER_OPEN,
                                            on_click=lambda _, p=project: on_reveal(p),
                                        ),
                                        ft.PopupMenuItem(
                                            content=ft.Text("复制本地路径"),
                                            icon=ft.Icons.CONTENT_COPY,
                                            on_click=lambda _, p=project: on_copy(p),
                                        ),
                                    ],
                                ),
                                ui.icon_action(
                                    ft.Icons.DELETE_OUTLINE,
                                    "移除",
                                    lambda _, p=project: on_delete(p),
                                    tone=T.Tone.DANGER,
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        ),
    )


# --------------------------------------------------------------------------- 纯函数
def _with_path(draft: ProjectDraft | None, text: str) -> ProjectDraft | None:
    """更新草稿里的路径。

    新增项目时名称多半还空着，顺手用目录名补一个，省得对着路径再敲一遍；
    编辑项目时不动名称——改路径不等于想改名。
    """
    if draft is None:
        return None
    changes: dict[str, object] = {"local_path": text}
    if not draft.is_edit and not draft.name.strip():
        changes["name"] = paths.suggest_name(text)
    return draft.with_fields(**changes)


def _shape(
    projects: list[Project],
    query: str,
    active: ProjectFilter,
    sort_key: SortKey,
) -> list[Project]:
    """过滤 + 排序，逻辑与界面解耦，便于单独验证。"""
    keyword = query.strip().casefold()
    matched = [project for project in projects if _matches(project, keyword, active)]
    match sort_key:
        case SortKey.UPDATED:
            matched.sort(key=lambda p: p.updated_at, reverse=True)
        case SortKey.DIRTY:
            matched.sort(key=lambda p: (p.changed_files, p.name), reverse=True)
        case _:
            matched.sort(key=lambda p: p.name.casefold())
    return matched


def _matches(project: Project, keyword: str, active: ProjectFilter) -> bool:
    if (
        keyword
        and keyword not in project.name.casefold()
        and keyword not in project.local_path.casefold()
    ):
        return False
    match active:
        case ProjectFilter.DIRTY:
            return project.has_local_changes
        case ProjectFilter.ATTENTION:
            return bool(project.warnings)
        case _:
            return True


__all__ = ["ProjectFilter", "ProjectsView", "SortKey"]
