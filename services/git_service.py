import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from models.database import CommitRecord


@dataclass(frozen=True)
class GitStatus:
    has_remote: bool
    has_local_changes: bool
    has_gitignore: bool


@dataclass(frozen=True)
class GitCommandResult:
    ok: bool
    stdout: str
    stderr: str


class GitService:
    @staticmethod
    def is_git_repo(path: str) -> bool:
        return (Path(path) / ".git").exists()

    @staticmethod
    async def _run(cwd: str, *args: str) -> GitCommandResult:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
        stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
        return GitCommandResult(proc.returncode == 0, stdout, stderr)

    @staticmethod
    def has_gitignore_file(path: str) -> bool:
        return (Path(path) / ".gitignore").is_file()

    @classmethod
    async def get_status(cls, repo_path: str) -> GitStatus:
        has_gitignore = cls.has_gitignore_file(repo_path)
        if not cls.is_git_repo(repo_path):
            return GitStatus(
                has_remote=False,
                has_local_changes=False,
                has_gitignore=has_gitignore,
            )

        remote_result = await cls._run(repo_path, "remote")
        status_result = await cls._run(repo_path, "status", "--porcelain")
        return GitStatus(
            has_remote=bool(remote_result.stdout.strip()),
            has_local_changes=bool(status_result.stdout.strip()),
            has_gitignore=has_gitignore,
        )

    @classmethod
    async def commit_and_push(cls, repo_path: str, message: str) -> GitCommandResult:
        if not message.strip():
            return GitCommandResult(False, "", "提交说明不能为空")

        steps = [
            ("add", ".", "暂存变更失败"),
            ("commit", "-m", message, "提交失败"),
            ("push-all", "推送失败"),
        ]
        for step in steps:
            if step[0] == "add":
                result = await cls._run(repo_path, "add", step[1])
                error_hint = step[2]
            elif step[0] == "commit":
                result = await cls._run(repo_path, "commit", "-m", step[2])
                error_hint = step[3]
            else:
                result = await cls._run(repo_path, "push-all")
                error_hint = step[1]

            if not result.ok:
                detail = result.stderr or result.stdout or error_hint
                return GitCommandResult(False, result.stdout, detail)

        return GitCommandResult(True, "提交并推送成功", "")

    @classmethod
    async def collect_commits(cls, repo_path: str) -> list[CommitRecord]:
        result = await cls._run(
            repo_path,
            "log",
            "--pretty=format:%H|%s|%ai",
            "--numstat",
        )
        if not result.ok:
            raise RuntimeError(result.stderr or result.stdout or "读取提交历史失败")

        records: list[CommitRecord] = []
        current_hash: str | None = None
        current_message = ""
        current_date: datetime | None = None
        insertions = 0
        deletions = 0
        files_changed = 0

        def flush() -> None:
            nonlocal current_hash, current_message, current_date
            nonlocal insertions, deletions, files_changed
            if not current_hash or not current_date:
                return
            records.append(
                CommitRecord(
                    project_id=0,
                    commit_hash=current_hash,
                    message=current_message,
                    committed_at=current_date,
                    insertions=insertions,
                    deletions=deletions,
                    files_changed=files_changed,
                )
            )
            current_hash = None
            current_message = ""
            current_date = None
            insertions = 0
            deletions = 0
            files_changed = 0

        for line in result.stdout.splitlines():
            if "|" in line and len(line.split("|", 2)) == 3:
                flush()
                commit_hash, message, date_text = line.split("|", 2)
                current_hash = commit_hash.strip()
                current_message = message.strip()
                try:
                    current_date = datetime.fromisoformat(date_text.strip())
                except ValueError:
                    current_date = datetime.strptime(
                        date_text.strip(), "%Y-%m-%d %H:%M:%S %z"
                    )
                continue

            parts = line.split("\t")
            if len(parts) >= 3 and current_hash:
                added, deleted = parts[0], parts[1]
                if added != "-" and deleted != "-":
                    insertions += int(added)
                    deletions += int(deleted)
                    files_changed += 1

        flush()
        return records
