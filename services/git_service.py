"""Git 命令封装。

职责边界：只负责"调用 git 并把输出解析成 DTO"，不碰数据库、不碰界面。
所有方法都是异步的，子进程并行执行不会阻塞 Flet 事件循环。

解析要点：

* ``git status --porcelain -b`` 一条命令同时拿到分支、上游、领先/落后与变更文件；
* ``git log`` 使用 ``%x1e`` / ``%x1f`` 作为分隔符，提交说明里出现 ``|`` 也不会解析错乱。
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.config import GIT_EXECUTABLE, GIT_TIMEOUT
from models.dto import Change, Commit, GitStatus, as_local_naive

_LOG_FORMAT = "%x1e%H%x1f%an%x1f%aI%x1f%s"
_AHEAD = re.compile(r"ahead (\d+)")
_BEHIND = re.compile(r"behind (\d+)")
_NO_UPSTREAM = ("no upstream branch", "no upstream", "has no upstream")


class GitError(RuntimeError):
    """git 不可用、目录不是仓库或命令执行失败。"""


@dataclass(frozen=True, slots=True)
class CommandResult:
    ok: bool
    stdout: str
    stderr: str

    @property
    def message(self) -> str:
        return self.stderr or self.stdout or "git 命令执行失败"


class GitService:
    def __init__(self, executable: str = GIT_EXECUTABLE) -> None:
        self._executable = executable

    # ------------------------------------------------------------------ 基础
    @staticmethod
    def is_repo(path: str | Path) -> bool:
        """``.git`` 可能是目录（普通仓库）也可能是文件（worktree / submodule）。"""
        return (Path(path) / ".git").exists()

    async def run(self, cwd: str | None, *args: str) -> CommandResult:
        """执行 git 子命令，超时或找不到可执行文件时抛出 ``GitError``。"""
        try:
            process = await asyncio.create_subprocess_exec(
                self._executable,
                *args,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise GitError("未找到 git 命令，请安装 Git 并确认已加入 PATH") from exc

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), GIT_TIMEOUT)
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise GitError(f"git {' '.join(args)} 执行超时（>{GIT_TIMEOUT:.0f}s）") from exc

        return CommandResult(process.returncode == 0, _decode(stdout), _decode(stderr))

    async def require(self, cwd: str, *args: str) -> str:
        result = await self.run(cwd, *args)
        if not result.ok:
            raise GitError(result.message)
        return result.stdout

    async def is_available(self) -> bool:
        try:
            return (await self.run(None, "--version")).ok
        except GitError:
            return False

    # ------------------------------------------------------------------ 探测
    async def snapshot(self, repo_path: str) -> GitStatus:
        """一次探测：远程配置 + 工作区状态。两条命令并行执行。"""
        has_gitignore = (Path(repo_path) / ".gitignore").is_file()
        if not self.is_repo(repo_path):
            return GitStatus(has_gitignore=has_gitignore)

        remote_result, status_result = await asyncio.gather(
            self.run(repo_path, "remote"),
            self.run(repo_path, "status", "--porcelain", "-b"),
        )
        if not status_result.ok:
            return GitStatus(
                is_repo=True,
                has_gitignore=has_gitignore,
                error=status_result.message,
            )

        branch, upstream, ahead, behind, changes = _parse_status(status_result.stdout)
        return GitStatus(
            is_repo=True,
            has_remote=bool(remote_result.stdout.strip()),
            has_local_changes=bool(changes),
            has_gitignore=has_gitignore,
            branch=branch,
            upstream=upstream,
            ahead=ahead,
            behind=behind,
            changes=changes,
        )

    async def probe(self, repo_path: str) -> GitStatus:
        """探测包装：任何 git 异常都转成带 error 描述的状态，不中断批量刷新。"""
        try:
            return await self.snapshot(repo_path)
        except GitError as exc:
            return GitStatus(
                is_repo=self.is_repo(repo_path),
                has_gitignore=(Path(repo_path) / ".gitignore").is_file(),
                error=str(exc),
            )

    # ------------------------------------------------------------------ 历史
    async def history(self, repo_path: str, *, limit: int) -> list[Commit]:
        result = await self.run(
            repo_path,
            "log",
            f"--pretty=format:{_LOG_FORMAT}",
            "--numstat",
            "--no-color",
            "-n",
            str(limit),
        )
        if not result.ok:
            if "does not have any commits" in result.stderr or "unknown revision" in result.stderr:
                return []  # 空仓库属于正常情况
            raise GitError(result.message)
        return list(_parse_log(result.stdout))

    # ------------------------------------------------------------------ 提交
    async def commit(
        self,
        repo_path: str,
        message: str,
        *,
        push: bool = True,
    ) -> tuple[bool, bool, str, GitStatus]:
        """暂存全部变更 -> 提交 ->（可选）推送，返回 (是否已提交, 是否已推送, 说明, 最新状态)。"""
        text = message.strip()
        if not text:
            raise GitError("提交说明不能为空")
        if not self.is_repo(repo_path):
            raise GitError("目标目录不是 Git 仓库")

        status = await self.snapshot(repo_path)
        if not status.changes:
            raise GitError("没有需要提交的变更")

        await self.require(repo_path, "add", "--all")
        await self.require(repo_path, "commit", "-m", text)

        pushed = False
        detail = "已提交（未推送）"
        if push:
            if not status.has_remote:
                detail = "已提交；该仓库未配置远程，已跳过推送"
            else:
                pushed, detail = await self._push(repo_path, status)

        return (True, pushed, detail, await self.snapshot(repo_path))

    async def _push(self, repo_path: str, status: GitStatus) -> tuple[bool, str]:
        result = await self.run(repo_path, "push")
        if result.ok:
            return (True, "已提交并推送成功")

        stderr = result.stderr.lower()
        if any(token in stderr for token in _NO_UPSTREAM):
            remotes = (await self.run(repo_path, "remote")).stdout.split()
            branch = status.branch or "main"
            if remotes:
                retry = await self.run(repo_path, "push", "--set-upstream", remotes[0], branch)
                if retry.ok:
                    return (True, f"已提交，并把 {branch} 关联到 {remotes[0]}")
                return (False, f"已提交，但推送失败：{retry.message}")

        return (False, f"已提交，但推送失败：{result.message}")


# --------------------------------------------------------------------------- 解析
def _decode(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace").strip()


def _parse_status(output: str) -> tuple[str, str, int, int, tuple[Change, ...]]:
    """解析 ``git status --porcelain -b``。"""
    branch = upstream = ""
    ahead = behind = 0
    changes: list[Change] = []

    for line in output.splitlines():
        if line.startswith("## "):
            head = line[3:]
            head, _, tracking = head.partition(" [")
            branch, _, upstream = head.partition("...")
            branch = branch.strip()
            if branch.startswith("No commits yet"):
                branch = branch.rsplit(" ", 1)[-1]
            if tracking:
                ahead = int(match.group(1)) if (match := _AHEAD.search(tracking)) else 0
                behind = int(match.group(1)) if (match := _BEHIND.search(tracking)) else 0
            continue

        if len(line) > 3:
            path = line[3:]
            if " -> " in path:  # 重命名：R  old -> new
                path = path.split(" -> ", 1)[1]
            changes.append(Change(code=line[:2], path=path.strip().strip('"')))

    return (branch, upstream.strip(), ahead, behind, tuple(changes))


def _parse_log(output: str) -> Iterator[Commit]:
    """解析 ``--pretty=format:%x1e...`` + ``--numstat`` 的组合输出。"""
    for record in output.split("\x1e"):
        if not record.strip():
            continue
        header, _, body = record.partition("\n")
        fields = header.split("\x1f")
        if len(fields) < 4:
            continue

        insertions = deletions = files_changed = 0
        for line in body.splitlines():
            columns = line.split("\t")
            if len(columns) < 3:
                continue
            added, removed = columns[0].strip(), columns[1].strip()
            if added.isdigit() and removed.isdigit():
                insertions += int(added)
                deletions += int(removed)
                files_changed += 1

        yield Commit(
            commit_hash=fields[0].strip(),
            message="\x1f".join(fields[3:]).strip(),
            committed_at=_parse_datetime(fields[2]),
            author=fields[1].strip(),
            insertions=insertions,
            deletions=deletions,
            files_changed=files_changed,
        )


def _parse_datetime(value: str) -> datetime:
    try:
        return as_local_naive(datetime.fromisoformat(value.strip()))
    except ValueError:
        return datetime.now()
