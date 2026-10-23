"""操作系统集成：在文件管理器中定位目录，并让外壳重新读取仓库状态。

提交还有一个界面之外的副作用要处理：TortoiseGit 的角标由后台的 ``TGitCache.exe``
维护，而它只在**工作区**发生变化时才失效重扫。``git commit`` 只改动 ``.git`` 里的
index / HEAD，工作区文件一个字节都没动，缓存因此一直停在"已修改"—— ``git status``
早已干净，资源管理器里却还是红叹号。TortoiseGit 没有对外提供"刷新角标"的命令，
能可靠复位这套缓存的方式就是重启那个缓存进程（社区公认的做法，它本身只是个可重建
的缓存，Explorer 需要时会自动再拉起来）。

所以提交之后这里做两步：先 ``SHChangeNotify`` 让资源管理器重画，再重启缓存进程
让它重新扫描。整个过程只碰外壳，不碰仓库里的任何文件。
"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

#: ``SHCNE_UPDATEDIR``：目录内容变了
_SHCNE_UPDATEDIR = 0x00001000
#: ``SHCNF_PATHW``：路径是宽字符；``SHCNF_FLUSH``：等外壳处理完再返回
_SHCNF_PATHW = 0x0005
_SHCNF_FLUSH = 0x1000

#: TortoiseGit 的状态缓存进程（TortoiseSVN 的 TSVNCache 与它无关）
_CACHE_IMAGE = "TGitCache.exe"
_CACHE_FOLDER = "TortoiseGit"

__all__ = ["ExplorerShell"]


class ExplorerShell:
    """本机文件管理器实现（:class:`~infra.ports.SystemShellPort`）。"""

    def reveal(self, path: str) -> tuple[bool, str]:
        """在系统文件管理器中打开目录，返回 (是否成功, 失败原因)。"""
        target = Path(path)
        if not target.is_dir():
            logger.warning("打开目录被跳过，路径不可用：%s", target)
            return (False, "目录不存在或已被移动")

        command = {
            "win32": ["explorer", str(target)],
            "darwin": ["open", str(target)],
        }.get(sys.platform, ["xdg-open", str(target)])
        logger.info("调用文件管理器：%s", " ".join(command))

        try:
            subprocess.Popen(command)
        except OSError as exc:
            logger.warning("无法调用文件管理器：%s", exc)
            return (False, f"无法调用文件管理器：{exc}")
        return (True, "")

    def notify_changed(self, path: str) -> None:
        """通知外壳该目录变了，并让 TortoiseGit 的角标缓存重扫。"""
        if sys.platform != "win32":
            return
        if _refresh_disabled():
            logger.debug("外壳刷新已被 CSPM_SHELL_REFRESH=off 关闭：%s", path)
            return

        _notify_shell(Path(path))
        _reset_cache()


# --------------------------------------------------------------------------- 内部
def _refresh_disabled() -> bool:
    """``CSPM_SHELL_REFRESH=off`` 时不再动外壳（给不想被动到 TortoiseGit 的人留的口子）。"""
    value = os.environ.get("CSPM_SHELL_REFRESH", "").strip().lower()
    return value in {"off", "0", "false", "no"}


def _notify_shell(target: Path) -> None:
    """``SHChangeNotify(SHCNE_UPDATEDIR)``：资源管理器立刻重画这个目录。"""
    # 外壳只认本机反斜杠写法，别把 Python 的正斜杠直接递过去
    path = os.path.normpath(str(target))
    try:
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        shell32.SHChangeNotify(
            _SHCNE_UPDATEDIR,
            _SHCNF_PATHW | _SHCNF_FLUSH,
            ctypes.c_wchar_p(path),
            None,
        )
        logger.debug("已通知外壳刷新目录：%s", path)
    except OSError as exc:  # 通知失败不影响提交本身
        logger.debug("通知外壳失败（%s）：%s", path, exc)


def _reset_cache() -> None:
    """重启 TortoiseGit 的状态缓存：停了旧的才有必要再拉起来。"""
    if not _stop_cache():
        logger.debug("%s 未在运行，角标本来就无需刷新", _CACHE_IMAGE)
        return
    logger.info("已重启 TortoiseGit 状态缓存，让角标重新扫描仓库")
    _start_cache()


def _stop_cache() -> bool:
    """停掉缓存进程；本来就没在跑时返回 False（此时什么都没做）。

    ``taskkill`` 的输出是系统代码页（GBK），这里只关心退出码，干脆不读它 ——
    用 ``text=True`` 收下来反而可能在解码时炸掉。
    """
    try:
        result = subprocess.run(
            ["taskkill", "/F", "/IM", _CACHE_IMAGE],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("停止 %s 失败：%s", _CACHE_IMAGE, exc)
        return False
    return result.returncode == 0


def _start_cache() -> None:
    """把缓存进程拉起来；找不到安装位置时交给资源管理器按需启动。"""
    executable = _cache_executable()
    if executable is None:
        logger.debug("未找到 %s，角标缓存交给资源管理器按需启动", _CACHE_IMAGE)
        return
    try:
        subprocess.Popen([str(executable)], close_fds=True)
        logger.debug("已启动 %s：%s", _CACHE_IMAGE, executable)
    except OSError as exc:
        logger.debug("启动 %s 失败：%s", _CACHE_IMAGE, exc)


def _cache_executable() -> Path | None:
    """TortoiseGit 的缓存程序位置：PATH 里没有，只能查默认安装目录。"""
    for base in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
        root = os.environ.get(base)
        if not root:
            continue
        candidate = Path(root) / _CACHE_FOLDER / "bin" / _CACHE_IMAGE
        if candidate.is_file():
            return candidate
    return None
