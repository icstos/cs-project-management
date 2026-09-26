"""操作系统集成：在文件管理器中定位目录。"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def reveal(path: str) -> tuple[bool, str]:
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
