"""Git 命令封装。

职责边界：只负责"调用 git 并把输出解析成 DTO"，不碰数据库、不碰界面。
所有方法都是异步的，子进程并行执行不会阻塞 Flet 事件循环。

命令执行统一走 ``core.proc.run_command``（命令、退出码、耗时与输出都进日志）；
这里只在"一次业务动作"的边界上补一条人话日志，日志读起来就是操作流水。

解析要点：

* ``git status --porcelain -b`` 一条命令同时拿到分支、上游、领先/落后与变更文件；
* ``git log`` 使用 ``%x1e`` / ``%x1f`` 作为分隔符，提交说明里出现 ``|`` 也不会解析错乱。
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from core.config import GIT_EXECUTABLE, GIT_TIMEOUT
from core.paths import is_git_repo
from core.proc import CommandError, CommandNotFound, CommandResult, CommandTimeout, run_command
from models.dto import Change, Commit, GitStatus, as_local_naive

logger = logging.getLogger(__name__)

_LOG_FORMAT = "%x1e%H%x1f%an%x1f%aI%x1f%s"
_AHEAD = re.compile(r"ahead (\d+)")
_BEHIND = re.compile(r"behind (\d+)")
_NO_UPSTREAM_REASON = "尚未设置上游分支，已自动关联"
_NON_FAST_FORWARD_REASON = "远程有更新的提交，请先拉取合并再推送"
_AUTH_REASON = "认证失败，请检查远程仓库的凭据"
_UNREACHABLE_REASON = "无法访问远程仓库（地址错误或无权限）"
_MISMATCH_REASON = "上游分支名与本地分支名不一致，已按同名分支推送"
_GIT_MISSING = "未找到 git 命令，请安装 Git 并确认已加入 PATH"
_HISTORY_EMPTY = ("does not have any commits", "unknown revision")
_MESSAGE_WIDTH = 60


class GitError(RuntimeError):
    """git 不可用、目录不是仓库或命令执行失败。"""


class GitService:
    def __init__(self, executable: str = GIT_EXECUTABLE) -> None:
        self._executable = executable

    # ------------------------------------------------------------------ 基础
    @staticmethod
    def is_repo(path: str | Path) -> bool:
        """目录是否是 Git 仓库（实现在 ``core.paths``，界面层也用它）。"""
        return is_git_repo(path)

    async def run(self, cwd: str | None, *args: str) -> CommandResult:
        """执行 git 子命令；超时或找不到可执行文件时抛出 ``GitError``。

        命令本身的日志（argv、退出码、耗时、stdout/stderr）由 ``core.proc`` 负责，
        这里只把"跑不起来"的异常翻译成业务层认得的 ``GitError``。
        """
        try:
            return await run_command((self._executable, *args), cwd=cwd, timeout=GIT_TIMEOUT)
        except CommandNotFound as exc:
            raise GitError(_GIT_MISSING) from exc
        except CommandTimeout as exc:
            raise GitError(str(exc)) from exc
        except CommandError as exc:
            raise GitError(str(exc)) from exc

    async def require(self, cwd: str, *args: str) -> str:
        result = await self.run(cwd, *args)
        if not result.ok:
            raise GitError(result.message)
        return result.stdout

    async def is_available(self) -> bool:
        try:
            available = (await self.run(None, "--version")).ok
        except GitError as exc:
            logger.warning("检测 git 可用性失败：%s", exc)
            return False
        logger.debug("git 可用性：%s", "可用" if available else "不可用")
        return available

    # ------------------------------------------------------------------ 探测
    async def snapshot(self, repo_path: str) -> GitStatus:
        """一次探测：远程配置 + 工作区状态。两条命令并行执行。"""
        has_gitignore = (Path(repo_path) / ".gitignore").is_file()
        if not self.is_repo(repo_path):
            logger.debug("探测 %s：不是 Git 仓库", repo_path)
            return GitStatus(has_gitignore=has_gitignore)

        remote_result, status_result = await asyncio.gather(
            self.run(repo_path, "remote"),
            self.run(repo_path, "status", "--porcelain", "-b"),
        )
        if not status_result.ok:
            logger.warning("探测 %s 失败：%s", repo_path, status_result.message)
            return GitStatus(
                is_repo=True,
                has_gitignore=has_gitignore,
                error=status_result.message,
            )

        branch, upstream, ahead, behind, changes = _parse_status(status_result.stdout)
        logger.debug(
            "探测 %s：分支=%s 上游=%s 领先=%d 落后=%d 变更=%d",
            repo_path,
            branch or "-",
            upstream or "-",
            ahead,
            behind,
            len(changes),
        )
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
            logger.warning("探测 %s 异常：%s", repo_path, exc)
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
            if _is_empty_history(result):
                logger.debug("采集 %s 历史：空仓库，暂无提交", repo_path)
                return []
            logger.warning("采集 %s 历史失败：%s", repo_path, result.message)
            raise GitError(result.message)

        commits = list(_parse_log(result.stdout))
        logger.debug("采集 %s 历史：解析出 %d 条提交（上限 %d）", repo_path, len(commits), limit)
        return commits

    # ------------------------------------------------------------------ 远程
    async def remotes(self, repo_path: str) -> list[str]:
        """已配置的远程名（``git remote`` 按字母序返回，不是配置顺序）。"""
        result = await self.run(repo_path, "remote")
        return result.stdout.split() if result.ok else []

    # ------------------------------------------------------------------ 提交
    async def commit(
        self,
        repo_path: str,
        message: str,
        *,
        push: bool = True,
    ) -> tuple[bool, bool, str, GitStatus]:
        """暂存全部变更 -> 提交 ->（可选）推送，返回 (是否已提交, 是否已推送, 说明, 最新状态)。

        ``已推送`` 的含义是"**所有**远程都推成功"，只推成功一部分时为 False。
        """
        text = message.strip()
        if not text:
            raise GitError("提交说明不能为空")
        if not self.is_repo(repo_path):
            raise GitError("目标目录不是 Git 仓库")

        status = await self.snapshot(repo_path)
        if not status.changes:
            raise GitError("没有需要提交的变更")

        logger.info(
            "提交 %s：%d 个文件，说明「%s」%s",
            repo_path,
            len(status.changes),
            _one_line(text),
            "（不推送）" if not push else "",
        )

        await self.require(repo_path, "add", "--all")
        await self.require(repo_path, "commit", "-m", text)

        pushed = False
        detail = "已提交（未推送）"
        if push:
            pushed, detail = await self._push(repo_path, status)

        logger.info("提交 %s → %s", repo_path, detail)
        return (True, pushed, detail, await self.snapshot(repo_path))

    async def _push(self, repo_path: str, status: GitStatus) -> tuple[bool, str]:
        """把当前分支推送到**所有**已配置的远程。

        ``git push`` 只认一个上游，多远程仓库必然漏推；因此这里逐个远程显式推送，
        并显式给出 ``<远程> <本地分支>:<目标分支>`` 引用，绕开 ``push.default``
        对上游名的挑剔（本地分支名与上游分支名不一致时裸 ``git push`` 会直接报错）。

        单个远程失败不影响其余远程：失败原因被压成一句人话后参与汇总。
        """
        remotes = await self.remotes(repo_path)
        if not remotes:
            logger.warning("推送 %s 被跳过：未配置任何远程", repo_path)
            return (
                False,
                "已提交，但该仓库未配置任何远程仓库，无法推送"
                "（先在仓库目录执行 git remote add origin <地址>，再「重新探测」）",
            )

        branch = status.branch
        if not branch:
            logger.warning("推送 %s 被跳过：游离 HEAD，没有分支", repo_path)
            return (False, "已提交，但当前处于游离 HEAD 状态，没有分支可推送")

        upstream = await self._upstream_of(repo_path, branch)
        tracked_remote, _, tracked_branch = upstream.partition("/")
        logger.info(
            "推送 %s：分支=%s，目标远程=%s，上游=%s",
            repo_path,
            branch,
            "、".join(remotes),
            upstream or "（未设置）",
        )

        succeeded: list[str] = []
        failed: list[str] = []
        linked = ""

        for remote in _preferred_first(remotes):
            target = tracked_branch if remote == tracked_remote and tracked_branch else branch
            args = ["push"]
            # 只在还没有上游时建立一次跟踪关系，否则 git status 永远显示不出领先/落后
            if not upstream and not linked:
                args.append("--set-upstream")
            args.append(remote)
            args.append(f"{branch}:{target}" if target != branch else branch)

            try:
                result = await self.run(repo_path, *args)
            except GitError as exc:  # 超时 / git 不可用：不该拖累其余远程
                logger.warning("推送 %s → %s 失败：%s", repo_path, remote, exc)
                failed.append(f"{remote}（{exc}）")
                continue

            if result.ok:
                succeeded.append(remote)
                if not upstream and not linked:
                    linked = f"{remote}/{target}"
                logger.info("推送 %s → %s 成功（%s:%s）", repo_path, remote, branch, target)
            else:
                reason = _push_reason(result)
                logger.warning("推送 %s → %s 失败：%s", repo_path, remote, reason)
                failed.append(f"{remote}（{reason}）")

        return (not failed, _push_summary(branch, succeeded, failed, linked))

    async def _upstream_of(self, repo_path: str, branch: str) -> str:
        """当前分支的上游，形如 ``origin/main``；未配置时返回空串。"""
        result = await self.run(
            repo_path,
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            f"{branch}@{{upstream}}",
        )
        return result.stdout.strip() if result.ok else ""


# --------------------------------------------------------------------------- 解析
def _one_line(text: str, *, width: int = _MESSAGE_WIDTH) -> str:
    """提交说明进日志前压成一行，过长截断。"""
    flat = " ".join(text.split())
    return flat if len(flat) <= width else f"{flat[:width]}…"


def _is_empty_history(result: CommandResult) -> bool:
    """空仓库（还没有任何提交）不是错误。"""
    text = f"{result.stderr}\n{result.stdout}"
    return any(token in text for token in _HISTORY_EMPTY)


def _preferred_first(remotes: list[str]) -> list[str]:
    """把 ``origin`` 提到最前。

    ``git remote`` 是字母序，直接用它选上游会挑中 ``backup`` 之类的名字；
    排在最前会让 ``--set-upstream`` 优先落在约定俗成的 ``origin`` 上，
    推送到多个远程的顺序则不受影响。
    """
    if "origin" in remotes:
        return ["origin", *(remote for remote in remotes if remote != "origin")]
    return remotes


def _push_reason(result: CommandResult) -> str:
    """把 git 推送失败的输出压成一句人话，认不出来就退回最后一行原文。"""
    text = f"{result.stderr}\n{result.stdout}"
    low = text.lower()
    reason = ""
    if "non-fast-forward" in low or "[rejected]" in low:
        reason = _NON_FAST_FORWARD_REASON
    elif "no upstream branch" in low:
        reason = _NO_UPSTREAM_REASON
    elif "upstream branch of your current" in low:
        reason = _MISMATCH_REASON
    elif (
        "authentication failed" in low
        or "could not read username" in low
        or "permission denied" in low
        or "invalid credentials" in low
    ):
        reason = _AUTH_REASON
    elif "could not read from remote repository" in low or "not appear to be a git repo" in low:
        reason = _UNREACHABLE_REASON

    if reason:
        return reason
    tail = [line.strip() for line in result.message.splitlines() if line.strip()]
    return tail[-1] if tail else "未知错误"


def _push_summary(
    branch: str,
    succeeded: list[str],
    failed: list[str],
    linked: str,
) -> str:
    """推送汇总：成功几个、失败几个、失败分别是什么原因。"""
    if not succeeded:
        return "已提交，但推送失败：" + "；".join(failed)

    names = "、".join(succeeded)
    detail = (
        f"已提交，并已推送到 {names}"
        if len(succeeded) == 1
        else f"已提交，并已推送到 {len(succeeded)} 个远程（{names}）"
    )
    if linked:
        detail += f"，{branch} 已关联 {linked}"
    if failed:
        detail += f"；另 {len(failed)} 个失败：{'；'.join(failed)}"
    return detail


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
