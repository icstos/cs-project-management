import asyncio
from pathlib import Path

from models.database import (
    CommitRecord,
    Permission,
    Project,
    delete_project,
    get_project,
    get_project_by_path,
    list_commit_records,
    list_projects,
    save_project,
    session_scope,
    upsert_commit_records,
)
from services.git_service import GitService, GitStatus


class ProjectService:
    @staticmethod
    def get_all() -> list[Project]:
        with session_scope() as session:
            return list_projects(session)

    @staticmethod
    def get(project_id: int) -> Project | None:
        with session_scope() as session:
            return get_project(session, project_id)

    @staticmethod
    def create(name: str, local_path: str, permission: Permission) -> Project:
        resolved = str(Path(local_path).resolve())
        if not Path(resolved).is_dir():
            raise ValueError("本地路径不存在")
        if not GitService.is_git_repo(resolved):
            raise ValueError("所选路径不是 Git 仓库")

        with session_scope() as session:
            if get_project_by_path(session, resolved):
                raise ValueError("该路径已添加为项目")
            project = Project(
                name=name.strip(),
                local_path=resolved,
                permission=permission.value,
            )
            return save_project(session, project)

    @staticmethod
    def update(
        project_id: int,
        name: str,
        local_path: str,
        permission: Permission,
    ) -> Project:
        resolved = str(Path(local_path).resolve())
        if not Path(resolved).is_dir():
            raise ValueError("本地路径不存在")
        if not GitService.is_git_repo(resolved):
            raise ValueError("所选路径不是 Git 仓库")

        with session_scope() as session:
            project = get_project(session, project_id)
            if not project:
                raise ValueError("项目不存在")

            existing = get_project_by_path(session, resolved)
            if existing and existing.id != project_id:
                raise ValueError("该路径已被其他项目使用")

            project.name = name.strip()
            project.local_path = resolved
            project.permission = permission.value
            return save_project(session, project)

    @staticmethod
    def remove(project_id: int) -> None:
        with session_scope() as session:
            if not delete_project(session, project_id):
                raise ValueError("项目不存在")

    @staticmethod
    async def refresh_git_status(project: Project) -> Project:
        status = await GitService.get_status(project.local_path)
        return ProjectService._apply_status(project.id, status)

    @staticmethod
    async def refresh_all_git_status() -> list[Project]:
        projects = ProjectService.get_all()
        if not projects:
            return []

        statuses = await asyncio.gather(
            *(GitService.get_status(project.local_path) for project in projects)
        )
        updated: list[Project] = []
        with session_scope() as session:
            for project, status in zip(projects, statuses, strict=True):
                stored = get_project(session, project.id)
                if not stored:
                    continue
                stored.has_remote = status.has_remote
                stored.has_local_changes = status.has_local_changes
                stored.has_gitignore = status.has_gitignore
                updated.append(save_project(session, stored))
        return updated

    @staticmethod
    def _apply_status(project_id: int, status: GitStatus) -> Project:
        with session_scope() as session:
            project = get_project(session, project_id)
            if not project:
                raise ValueError("项目不存在")
            project.has_remote = status.has_remote
            project.has_local_changes = status.has_local_changes
            project.has_gitignore = status.has_gitignore
            return save_project(session, project)

    @staticmethod
    async def commit(project_id: int, message: str) -> Project:
        with session_scope() as session:
            project = get_project(session, project_id)
            if not project:
                raise ValueError("项目不存在")
            repo_path = project.local_path

        result = await GitService.commit_and_push(repo_path, message)
        if not result.ok:
            raise RuntimeError(result.stderr or result.stdout)

        status = await GitService.get_status(repo_path)
        return ProjectService._apply_status(project_id, status)

    @staticmethod
    async def collect_statistics(project_id: int | None = None) -> int:
        with session_scope() as session:
            projects = (
                [get_project(session, project_id)]
                if project_id is not None
                else list_projects(session)
            )
            projects = [project for project in projects if project]

        total_saved = 0
        for project in projects:
            records = await GitService.collect_commits(project.local_path)
            with session_scope() as session:
                total_saved += upsert_commit_records(session, project.id, records)
        return total_saved

    @staticmethod
    def get_commit_records(project_id: int | None = None) -> list[CommitRecord]:
        with session_scope() as session:
            return list_commit_records(session, project_id)

    @staticmethod
    def get_commit_records_with_projects(
        project_id: int | None = None,
    ) -> list[tuple[CommitRecord, Project]]:
        with session_scope() as session:
            projects = {project.id: project for project in list_projects(session)}
            records = list_commit_records(session, project_id)
            return [
                (record, projects[record.project_id])
                for record in records
                if record.project_id in projects
            ]
