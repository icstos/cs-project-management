"""操作系统集成：在文件管理器中定位目录。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def reveal(path: str) -> tuple[bool, str]:
    """在系统文件管理器中打开目录，返回 (是否成功, 失败原因)。"""
    target = Path(path)
    if not target.is_dir():
        return (False, "目录不存在或已被移动")

    try:
        match sys.platform:
            case "win32":
                subprocess.Popen(["explorer", str(target)])
            case "darwin":
                subprocess.Popen(["open", str(target)])
            case _:
                subprocess.Popen(["xdg-open", str(target)])
    except OSError as exc:
        return (False, f"无法调用文件管理器：{exc}")
    return (True, "")
