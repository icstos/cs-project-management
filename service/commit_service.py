"""提交与推送的业务编排。

流程很短，但界面对它有明确预期，所以单独成服务：

* :meth:`CommitService.preview` 在切换项目时重新探测工作区，让用户在按下提交前
  就能确认"到底会提交哪些文件"；
* :meth:`CommitService.commit` 执行提交并把最新状态回写台账，让列表页立刻同步。
"""

from __future__ import annotations

import logging

from infra.concurrency import offload
from infra.ports import GitPort, ProjectRepository, SystemShellPort
from models.dtos import CommitOutcome, GitStatus

logger = logging.getLogger(__name__)

__all__ = ["CommitService"]


class CommitService:
    """暂存、提交、推送，以及提交前的工作区预览。"""

    def __init__(
        self,
        *,
        projects: ProjectRepository,
        git: GitPort,
        shell: SystemShellPort,
    ) -> None:
        self._projects = projects
        self._git = git
        self._shell = shell

    async def _require(self, project_id: int):
        project = await offload(self._projects.get, project_id)
        if project is None:
            raise ValueError("项目不存在或已被删除")
        return project

    async def preview(self, project_id: int) -> GitStatus:
        """提交前的实时预览：分支、领先/落后、待提交文件清单。"""
        project = await self._require(project_id)
        return await self._git.probe(project.local_path)

    async def commit(self, project_id: int, message: str, *, push: bool = True) -> CommitOutcome:
        project = await self._require(project_id)
        outcome = await self._git.commit(project.local_path, message, push=push)
        if outcome.status is not None:
            await offload(self._projects.save_status, project_id, outcome.status)
        # 提交只改 .git（index / HEAD），工作区文件一个都没动。TortoiseGit 的角标缓存
        # 只跟随工作区事件失效，不主动通知的话它会一直显示"已修改"，而 git status 早已干净。
        if outcome.committed:
            await offload(self._shell.notify_changed, project.local_path)
        # git 层记的是仓库路径，这里补上项目名，日志里才对得上界面
        level = logging.INFO if outcome.pushed or not push else logging.WARNING
        logger.log(level, "项目「%s」提交结果：%s", project.name, outcome.detail)
        return outcome
