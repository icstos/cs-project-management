"""项目业务编排。

对外只暴露异步方法并返回 DTO，内部统一做三件事：

1. 校验用户输入（名称、路径、是否 Git 仓库、是否重复）；
2. 把阻塞的持久化访问丢进线程池；
3. 把多次 git 探测按并发上限并行执行，最后一次性落库。

只依赖 :mod:`infra.ports` 里的抽象接口，不感知 SQLite、subprocess 或路径规则的具体实现。

日志分工：外部命令的细节由基础设施层记录，这里只记**操作流水**（谁对哪个项目做了什么、
结果如何），两者按时间线拼起来就能还原一次完整的用户操作。
"""

from __future__ import annotations

import itertools
import logging
from collections.abc import Callable
from pathlib import Path

from infra.concurrency import gather_limited, offload
from infra.ports import (
    CommitRepository,
    GitPort,
    PathPort,
    ProjectRepository,
    SystemShellPort,
)
from models.dtos import GitStatus, Project
from models.enums import Permission

logger = logging.getLogger(__name__)

#: ``on_progress(已完成, 总数)``
Progress = Callable[[int, int], None]

__all__ = ["Progress", "ProjectService"]


class ProjectService:
    """项目台账的读写与仓库状态探测。"""

    def __init__(
        self,
        *,
        projects: ProjectRepository,
        commits: CommitRepository,
        git: GitPort,
        paths: PathPort,
        shell: SystemShellPort,
        concurrency: int,
    ) -> None:
        self._projects = projects
        self._commits = commits
        self._git = git
        self._paths = paths
        self._shell = shell
        self._concurrency = concurrency

    # ------------------------------------------------------------------ 只读
    async def list_projects(self) -> list[Project]:
        return await offload(self._projects.list_all)

    async def get(self, project_id: int) -> Project:
        project = await offload(self._projects.get, project_id)
        if project is None:
            raise ValueError("项目不存在或已被删除")
        return project

    async def git_available(self) -> bool:
        return await self._git.available()

    async def check_path(self, raw: str) -> str | None:
        """路径能不能用作项目路径，``None`` 表示可用。

        这是"能不能存进台账"的唯一判据，界面上的即时提示与保存校验都走它；
        存在性判断会碰文件系统（断开的网络盘可能阻塞数秒），所以丢进线程池。
        """
        return await offload(self._paths.problem, raw)

    def normalize_path(self, raw: str) -> str:
        """把用户带来的路径整理成本机写法。"""
        return self._paths.normalize(raw)

    def has_paste_marks(self, raw: str) -> bool:
        """输入里是否带着只有粘贴才可能出现的痕迹（引号、``file:`` 链接、换行）。"""
        return self._paths.has_paste_marks(raw)

    def suggest_name(self, raw: str) -> str:
        """从路径猜一个项目名，新增项目时省得再敲一遍。"""
        return self._paths.suggest_name(raw)

    # ------------------------------------------------------------------ 维护
    async def create(self, *, name: str, local_path: str, permission: Permission) -> Project:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("项目名称不能为空")
        resolved = self._resolve_repo(local_path)

        project = await offload(self._insert, clean_name, resolved, permission)
        logger.info("新增项目「%s」→ %s（%s）", clean_name, resolved, permission.value)
        return await self.refresh(project.id)

    async def update(
        self,
        project_id: int,
        *,
        name: str,
        local_path: str,
        permission: Permission,
    ) -> Project:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("项目名称不能为空")
        resolved = self._resolve_repo(local_path)

        previous = await self.get(project_id)
        project = await offload(self._modify, project_id, clean_name, resolved, permission)
        logger.info(
            "更新项目 #%d →「%s」%s（%s）", project_id, clean_name, resolved, permission.value
        )
        if previous.local_path == project.local_path:  # 路径没变就不用重新探测
            return project
        return await self.refresh(project_id)

    async def delete(self, project_id: int) -> Project:
        project = await self.get(project_id)
        await offload(self._remove, project_id)
        logger.info("删除项目 #%d「%s」（%s）", project_id, project.name, project.local_path)
        return project

    async def refresh(self, project_id: int) -> Project:
        project = await self.get(project_id)
        status = await self._git.probe(project.local_path)
        updated = await offload(self._projects.save_status, project_id, status)
        return updated or project

    async def refresh_all(self, *, on_progress: Progress | None = None) -> list[Project]:
        projects = await self.list_projects()
        if not projects:
            logger.info("刷新全部：暂无项目")
            return []

        total = len(projects)
        logger.info("刷新全部：开始探测 %d 个仓库（并发 %d）", total, self._concurrency)
        _notify(on_progress, 0, total)
        done = itertools.count(1)

        async def probe(project: Project) -> GitStatus:
            status = await self._git.probe(project.local_path)
            _notify(on_progress, next(done), total)
            return status

        statuses = await gather_limited(projects, probe, limit=self._concurrency)
        pairs = [(project.id, status) for project, status in zip(projects, statuses, strict=True)]
        updated = await offload(self._projects.save_statuses, pairs)

        dirty = sum(1 for status in statuses if status.has_local_changes)
        logger.info("刷新全部：完成 %d 个仓库，%d 个有待提交变更", len(updated), dirty)
        for project, status in zip(projects, statuses, strict=True):
            if status.error:
                logger.warning("刷新全部：项目「%s」状态异常", project.name)
        return updated

    # ------------------------------------------------------------------ 系统集成
    async def reveal(self, path: str) -> tuple[bool, str]:
        """在文件管理器中打开目录（成功后返回 True）。"""
        return await offload(self._shell.reveal, path)

    # ------------------------------------------------------------------ 内部
    def _resolve_repo(self, local_path: str) -> str:
        """校验并规范化用户填入的目录。

        路径可能来自浏览按钮，也可能是直接粘贴的（带引号、``file://`` 前缀、
        正斜杠……），所以先走路径端口收敛形态；判据与界面上的即时提示同源
        （``check_path``），界面说可用就不会在这里再被拒。
        """
        issue = self._paths.problem(local_path)
        if issue:
            logger.warning("路径校验未通过：%r → %s", local_path, issue)
            raise ValueError(issue)
        return str(Path(self._paths.normalize(local_path)).resolve())

    def _insert(self, name: str, local_path: str, permission: Permission) -> Project:
        if self._projects.find_by_path(local_path) is not None:
            raise ValueError("该路径已添加为项目")
        return self._projects.create(name=name, local_path=local_path, permission=permission)

    def _modify(
        self,
        project_id: int,
        name: str,
        local_path: str,
        permission: Permission,
    ) -> Project:
        existing = self._projects.find_by_path(local_path)
        if existing is not None and existing.id != project_id:
            raise ValueError("该路径已被其他项目占用")
        project = self._projects.update(
            project_id, name=name, local_path=local_path, permission=permission
        )
        if project is None:
            raise ValueError("项目不存在或已被删除")
        return project

    def _remove(self, project_id: int) -> None:
        # 先清掉提交记录，再删项目本身；两步同处一次线程池调用，避免留下孤儿数据
        self._commits.delete_for_project(project_id)
        if not self._projects.delete(project_id):
            raise ValueError("项目不存在或已被删除")


def _notify(callback: Progress | None, done: int, total: int) -> None:
    if callback is not None:
        callback(done, total)
