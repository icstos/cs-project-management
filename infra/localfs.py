"""目录占用统计与"能删得掉"的递归删除。

打包前要先腾空产物目录，而 Windows 上删除失败几乎只有两类原因：

* **只读属性**——git 的 object 文件、从压缩包里解出来的文件都带只读位，
  ``shutil.rmtree`` 遇到它们直接报 ``Access denied``；
* **文件被占用**——上一次打包出来的程序还在运行、或资源管理器/终端把工作目录
  停在里面，内核会拒绝删除（共享冲突）。

这里把两类都处理掉：只读先去掉只读位再重试一次，被占用的则记下具体路径与原因，
交给上层给出"关掉程序再重试"这种能直接照做的提示 —— 而不是一个裸的
``PermissionError`` 让用户一头雾水。

纯文件系统操作，不碰数据库也不碰界面；统计与删除都可能遍历上万个文件，
调用方负责把它丢进线程池。
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import stat
from pathlib import Path

from models.dtos import Blocker, RemoveReport, TreeStats

logger = logging.getLogger(__name__)

#: 统计时列出多少个顶层条目（用于"这个目录里都是什么"的预览）
TOP_SAMPLE = 6

#: Windows 上表示"文件正被占用/没有权限"的错误码：拒绝访问、共享冲突、区域被锁
_LOCKED_WINERROR = frozenset({5, 32, 33})


class LocalFileSystem:
    """本机文件系统实现（:class:`~infra.ports.FileSystemPort`）。"""

    def tree_stats(self, root: str) -> TreeStats:
        return tree_stats(root)

    def remove_tree(self, root: str) -> RemoveReport:
        return remove_tree(root)


def tree_stats(root: str | Path, *, top_sample: int = TOP_SAMPLE) -> TreeStats:
    """统计 ``root`` 下的文件数、目录数与总字节数。

    单个条目读不到（权限、被删掉）就跳过，统计这类"看一眼"的操作不该整体失败。
    """
    target = Path(root)
    if not target.is_dir():
        return TreeStats(exists=target.exists())

    files = directories = total = 0
    top: list[str] = []

    def on_error(exc: OSError) -> None:
        logger.debug("统计目录时跳过 %s：%s", exc.filename, exc)

    for entry in os.scandir(target):
        if len(top) < top_sample:
            top.append(entry.name + ("/" if entry.is_dir(follow_symlinks=False) else ""))
        if entry.is_dir(follow_symlinks=False):
            for walk_root, dir_names, file_names in os.walk(entry.path, onerror=on_error):
                directories += len(dir_names)
                for name in file_names:
                    files += 1
                    with contextlib.suppress(OSError):
                        total += os.stat(os.path.join(walk_root, name)).st_size
        elif entry.is_file(follow_symlinks=False):
            files += 1
            with contextlib.suppress(OSError):
                total += entry.stat().st_size

    return TreeStats(
        exists=True,
        files=files,
        directories=directories,
        bytes=total,
        top=tuple(top),
    )


def remove_tree(root: str | Path) -> RemoveReport:
    """递归删除 ``root``，尽量删干净，并把删不掉的原因说清楚。

    返回 ``ok=False`` 时 ``blockers`` 里至少有一条具体路径 —— 这正是界面需要
    告诉用户"先关掉哪个程序"的依据。
    """
    target = Path(root)
    if not target.exists():
        return RemoveReport(ok=True)

    before = tree_stats(target).files
    blockers: list[Blocker] = []
    seen: set[str] = set()

    def record(exc: BaseException, path: str) -> None:
        if path in seen:  # 一个目录失败会连带上报多次，去重
            return
        seen.add(path)
        blockers.append(Blocker(path=path, reason=_reason(exc), locked=_is_locked(exc)))
        logger.debug("删除失败 %s：%s", path, exc)

    def on_error(func, path: str, exc: BaseException) -> None:
        # 只读位是最常见的失败原因，去掉后原地重试一次；仍失败才记下来
        if _make_writable(path):
            try:
                func(path)
                return
            except OSError as retry_exc:
                record(retry_exc, path)
                return
        record(exc, path)

    logger.info("删除目录 %s（约 %d 个文件）", target, before)
    try:
        # onexc 是 3.12 起推荐的签名，onerror 已废弃
        shutil.rmtree(target, onexc=on_error)
    except OSError as exc:  # rmtree 自身抛错（例如根目录被占用）
        record(exc, str(target))

    remaining = tree_stats(target).files if target.exists() else 0
    ok = not target.exists()
    removed = max(0, before - remaining)

    if ok:
        logger.info("目录已删除 %s（%d 个文件）", target, removed)
    else:
        logger.warning(
            "目录未删净 %s：剩余 %d 个文件，%d 处被阻塞（首个：%s）",
            target,
            remaining,
            len(blockers),
            blockers[0].path if blockers else "未知",
        )
    return RemoveReport(ok=ok, removed=removed, total=before, blockers=tuple(blockers))


# --------------------------------------------------------------------------- 内部
def _make_writable(path: str) -> bool:
    """给文件补上写权限，返回是否真的改动成功。"""
    try:
        mode = os.stat(path, follow_symlinks=False).st_mode
        if mode & stat.S_IWRITE:
            return True  # 本来就是可写的，说明失败另有原因，别再试
        os.chmod(path, mode | stat.S_IWRITE)
        return True
    except OSError:
        return False


def _is_locked(exc: BaseException) -> bool:
    """是否属于"文件被占用"（而不是单纯的权限不足）。"""
    winerror = getattr(exc, "winerror", None)
    if winerror is not None:
        return winerror in _LOCKED_WINERROR
    return isinstance(exc, PermissionError)


def _reason(exc: BaseException) -> str:
    match exc:
        case FileNotFoundError():
            return "文件已经不在了"
        case PermissionError():
            winerror = getattr(exc, "winerror", None)
            if winerror == 32:
                return "文件正被其他程序占用"
            return "没有删除权限（可能被占用或受保护）"
        case OSError():
            return f"删除失败：{exc.strerror or exc}"
        case _:
            return str(exc)


__all__ = ["LocalFileSystem", "remove_tree", "tree_stats"]
