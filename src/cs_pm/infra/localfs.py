"""目录占用统计、"能删得掉"的递归删除，以及"整目录搬进历史版本"。

打包前要先把产物目录腾出来，而在 Windows 上失败几乎只有两类原因：

* **只读属性**——git 的 object 文件、从压缩包里解出来的文件都带只读位，
  ``shutil.rmtree`` 遇到它们直接报 ``Access denied``；
* **文件被占用**——上一次打包出来的程序还在运行、或资源管理器/终端把工作目录
  停在里面，内核会拒绝删除（共享冲突）。

这里把两类都处理掉：只读先去掉只读位再重试一次，被占用的则记下具体路径与原因，
交给上层给出"关掉程序再重试"这种能直接照做的提示 —— 而不是一个裸的
``PermissionError`` 让用户一头雾水。

:func:`archive_tree` 是"腾空"的另一种做法：不动内容、只把整个目录挪进历史版本
文件夹。存档目录与产物目录同属一个父级（同一个卷），所以那里的移动是一次改名：
瞬间完成、不额外占空间，只读文件也不碍事（不像删除要先去掉只读位）。

纯文件系统操作，不碰数据库也不碰界面；统计、删除与移动都可能涉及上万个文件，
调用方负责把它丢进线程池。
"""

from __future__ import annotations

import contextlib
import errno
import logging
import os
import shutil
import stat
from pathlib import Path

from cs_pm.models.dtos import ArchiveReport, Blocker, RemoveReport, TreeStats

logger = logging.getLogger(__name__)

#: 统计时列出多少个顶层条目（用于"这个目录里都是什么"的预览）
TOP_SAMPLE = 6

#: Windows 上表示"文件正被占用/没有权限"的错误码：拒绝访问、共享冲突、区域被锁
_LOCKED_WINERROR = frozenset({5, 32, 33})


class LocalFileSystem:
    """本机文件系统实现（:class:`~cs_pm.infra.ports.FileSystemPort`）。"""

    def tree_stats(self, root: str) -> TreeStats:
        return tree_stats(root)

    def remove_tree(self, root: str) -> RemoveReport:
        return remove_tree(root)

    def archive_tree(self, source: str, target: str) -> ArchiveReport:
        return archive_tree(source, target)


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


def archive_tree(source: str | Path, target: str | Path) -> ArchiveReport:
    """把 ``source`` 整个搬到 ``target``（旧版本进「历史版本」文件夹）。

    为什么先试 ``os.rename`` 再退回 ``shutil.move``：存档目录与产物目录同父级，
    正常情况下这一步就是同一卷上的改名 —— 瞬间完成，读文件与占空间都不发生。
    只有确实跨卷（``EXDEV``，例如父目录是映射盘）才交给 ``shutil.move`` 做复制 +
    删除。**不能**对任何 ``OSError`` 都退回 ``shutil``：目标已存在时它会把源目录
    塞进目标里面（``dst/src``），那是另一种"搬了一半"。

    目标已存在时自动追加 ``-2`` / ``-3``……：同一秒里连点两次打包，第二份不会
    覆盖第一份。失败时返回 ``ok=False`` 与可直接展示的 ``reason``，**原目录保持
    原样**（同卷改名是原子的，不存在"搬了一半"）。
    """
    src, requested = Path(source), Path(target)
    if not src.exists():
        return ArchiveReport(ok=True, source=str(src), target=str(requested))

    files = tree_stats(src).files
    dst = _unique_target(requested)
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.rename(src, dst)
        except OSError as exc:
            if not _is_cross_device(exc):
                raise
            shutil.move(str(src), str(dst))
    except (OSError, shutil.Error) as exc:
        logger.warning("移入历史版本失败 %s → %s：%s", src, dst, exc)
        return ArchiveReport(
            ok=False,
            source=str(src),
            target=str(dst),
            files=files,
            reason=_move_reason(exc, dst),
        )

    logger.info("已移入历史版本：%s → %s（%d 个文件）", src, dst, files)
    return ArchiveReport(ok=True, source=str(src), target=str(dst), files=files)


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


def _unique_target(target: Path) -> Path:
    """目标已存在时在名字后补 ``-2`` / ``-3``……，避免覆盖既有存档。"""
    if not target.exists():
        return target
    index = 1
    while True:
        index += 1
        candidate = target.with_name(f"{target.name}-{index}")
        if not candidate.exists():
            return candidate


def _is_cross_device(exc: OSError) -> bool:
    """改名失败是不是"跨卷"造成的（只有这种情况才值得退回复制 + 删除）。"""
    return exc.errno == errno.EXDEV or getattr(exc, "winerror", None) == 17


def _move_reason(exc: BaseException, target: Path) -> str:
    """把移动失败翻译成一句能直接照做的提示。"""
    match exc:
        case FileExistsError():
            if target.exists():
                return "历史版本里已经有同名目录，且无法追加序号"
            return f"没法创建存档目录：{target.parent} 不可用（可能被同名文件占住了）"
        case NotADirectoryError():
            return f"存档路径不可用：{target.parent} 不是一个文件夹"
        case PermissionError():
            winerror = getattr(exc, "winerror", None)
            if winerror == 32:
                return "目录正被其他程序占用：先关掉里面的程序再重试"
            return "没有移动权限（目录可能被占用，或存档目录不可写）"
        case OSError():
            return f"移动失败：{exc.strerror or exc}"
        case _:
            return str(exc)


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


__all__ = ["LocalFileSystem", "archive_tree", "remove_tree", "tree_stats"]
