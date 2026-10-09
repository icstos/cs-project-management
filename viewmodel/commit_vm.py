"""提交视图模型：选择项目、查看实时变更、提交并（可选）推送。

与项目管理不同，这里每次切换项目都会重新探测一次工作区，让用户在按下提交前
就能确认"到底会提交哪些文件"；推送开关也会跟随最新探测结果回正 —— 数据库里
缓存的 ``has_remote`` 可能已经过期（刚加过远程、或远程被删掉），订阅它会让
开关被永久锁死。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from models.dtos import Change, ChangeKind, GitStatus, Project
from models.enums import Tone
from service.commit_service import CommitService
from viewmodel.base import ViewModel

logger = logging.getLogger(__name__)

__all__ = ["ChangeSummary", "CommitResult", "CommitState", "CommitViewModel"]


@dataclass(frozen=True, slots=True)
class ChangeSummary:
    """待提交变更按类型聚合后的一行读数。"""

    kind: ChangeKind
    count: int

    @property
    def label(self) -> str:
        return f"{self.kind.label} {self.count}"


@dataclass(frozen=True, slots=True)
class CommitResult:
    """最近一次提交 / 推送的结果。

    浮层只活 3 秒，推送失败的原文可能很长，所以在面板里留一份。
    """

    detail: str
    tone: Tone


@dataclass(frozen=True, slots=True)
class CommitState:
    """提交页的全部状态。"""

    projects: tuple[Project, ...] = ()
    selected_id: int | None = None
    message: str = ""
    #: 用户是否手动拨过推送开关：没拨过就让开关跟随最新探测结果
    push: bool = True
    push_touched: bool = False
    preview: GitStatus | None = None
    preview_error: str | None = None
    loading_preview: bool = False
    committing: bool = False
    result: CommitResult | None = None

    # ------------------------------------------------------------------ 派生
    @property
    def selected(self) -> Project | None:
        return next((p for p in self.projects if p.id == self.selected_id), None)

    @property
    def has_remote(self) -> bool:
        """是否配置了远程仓库，**以实时探测为准**，缓存值可能已过期。"""
        if self.preview is not None:
            return self.preview.has_remote
        return bool(self.selected and self.selected.has_remote)

    @property
    def will_push(self) -> bool:
        return self.push and self.has_remote

    @property
    def changes(self) -> tuple[Change, ...]:
        return self.preview.changes if self.preview else ()

    @property
    def can_submit(self) -> bool:
        return bool(self.message.strip()) and not self.committing and bool(self.changes)

    @property
    def summaries(self) -> tuple[ChangeSummary, ...]:
        """按类型聚合的变更概览，数量多的排前面。"""
        counts: dict[ChangeKind, int] = {}
        for change in self.changes:
            counts[change.kind] = counts.get(change.kind, 0) + 1
        return tuple(
            ChangeSummary(kind, count)
            for kind, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)
        )

    @property
    def change_count(self) -> int:
        """变更文件数：探测结果优先，其次退回台账里的缓存值。"""
        if self.preview is not None:
            return self.preview.change_count
        return self.selected.changed_files if self.selected else 0


class CommitViewModel(ViewModel[CommitState]):
    """提交页的状态与命令。"""

    def __init__(self, service: CommitService) -> None:
        super().__init__(CommitState())
        self._service = service

    # ------------------------------------------------------------------ 同步
    def sync(self, *, projects: tuple[Project, ...]) -> None:
        """接收 App 下发的项目列表，并在必要时重新选中一个项目。

        系统会优先选中"有本地变更"的项目 —— 打开提交页的意图通常就是提交它。
        """
        if self.state.projects == projects:
            return
        self.update(projects=projects)

        if not projects:
            self.update(selected_id=None, preview=None)
            return
        if any(project.id == self.state.selected_id for project in projects):
            return
        preferred = next((p for p in projects if p.has_local_changes), projects[0])
        self._select(preferred.id)

    # ------------------------------------------------------------------ 选择
    def _select(self, project_id: int) -> None:
        self.update(
            selected_id=project_id,
            push_touched=False,
            push=self._has_remote_of(project_id),
            preview=None,
            preview_error=None,
            result=None,
        )

    def _has_remote_of(self, project_id: int) -> bool:
        project = next((p for p in self.state.projects if p.id == project_id), None)
        return bool(project and project.has_remote)

    async def choose(self, project: Project) -> None:
        if project.id == self.state.selected_id:
            return
        self._select(project.id)
        await self.load_preview()

    def toggle_push(self, value: bool) -> None:
        self.update(push=value, push_touched=True)

    def set_message(self, text: str) -> None:
        self.update(message=text)

    # ------------------------------------------------------------------ 预览
    async def load_preview(self) -> None:
        project_id = self.state.selected_id
        if project_id is None:
            self.update(preview=None)
            return
        self.update(loading_preview=True)
        try:
            status = await self._service.preview(project_id)
        except (ValueError, RuntimeError) as exc:
            logger.warning("预览提交内容失败（project_id=%s）：%s", project_id, exc)
            self.update(loading_preview=False, preview=None, preview_error=str(exc))
            return
        changes: dict[str, object] = {
            "loading_preview": False,
            "preview": status,
            "preview_error": None,
        }
        if not self.state.push_touched:
            changes["push"] = status.has_remote
        self.update(**changes)

    # ------------------------------------------------------------------ 提交
    async def submit(self) -> None:
        project = self.state.selected
        if project is None:
            self.notify("请先选择要提交的项目", Tone.WARNING)
            return
        if not self.state.message.strip():
            self.notify("请填写提交说明", Tone.WARNING)
            return

        push = self.state.will_push
        self.update(committing=True, result=None)
        try:
            outcome = await self._service.commit(project.id, self.state.message, push=push)
        except (ValueError, RuntimeError) as exc:
            logger.warning("提交失败（项目「%s」，push=%s）：%s", project.name, push, exc)
            detail = str(exc)
            self.update(committing=False, result=CommitResult(detail, Tone.DANGER))
            self.notify(detail, Tone.DANGER)
            return

        tone = Tone.SUCCESS if outcome.pushed or not push else Tone.WARNING
        self.update(committing=False, message="", result=CommitResult(outcome.detail, tone))
        self.notify(outcome.detail, tone)
        await self.load_preview()
