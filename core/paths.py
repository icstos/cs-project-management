"""本地路径的规范化与判定。

用户带来路径的途径很多——资源管理器的「复制为路径」、浏览器地址栏里复制出来的
``file:///D:/repo``、终端输出、文档里的示例——形态各不相同。这里把它们收敛成
同一种形态（Windows 上为 ``D:\\a\\b``，类 Unix 上保持 POSIX 写法），
界面层与业务层共用同一套规则，避免"输入框显示一套、入库又是另一套"。

本模块只做纯路径处理，不启动任何子进程；唯一的文件系统访问是存在性判断，
调用方在界面线程里使用时应通过 ``core.tasks.offload`` 丢进线程池
（断开的网络盘会让 ``Path.exists()`` 阻塞数秒）。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

# 粘贴时容易捎带进来的不可见字符：BOM、零宽字符
_INVISIBLE = dict.fromkeys(map(ord, "\ufeff\u200b\u200c\u200d"), None)
# 包裹引号。Windows 文件名不允许出现 "，但允许 '，所以只在首尾逐个剥。
_QUOTES = "\"'“”‘’"
# 一定属于「粘贴」而非手输中间态的特征：换行、制表符、Windows 长路径前缀
_PASTE_MARKS = re.compile(r"[\r\n\t]|^\\\\\?\\")
_DRIVE_ROOT = re.compile(r"[A-Za-z]:\\")
_DRIVE_PREFIX = re.compile(r"^([a-z]):")
_IS_WINDOWS = os.name == "nt"


def normalize(raw: str) -> str:
    """把用户粘进来的路径整理成本机可用的形式，不判断它是否存在。

    处理：去掉不可见字符与多行内容里的说明文字、还原 ``file://`` 链接、
    剥掉包裹引号、展开 ``~``，并在 Windows 上统一分隔符与盘符大小写。
    """
    text = _strip_text(raw)
    if not text:
        return ""
    text = _from_file_url(text)
    text = _unwrap(text)
    text = os.path.expanduser(text)
    return _to_native(text) if _IS_WINDOWS else text


def has_paste_marks(raw: str) -> bool:
    """文本里是否带着「粘贴痕迹」。

    用来决定要不要把整理结果立刻写回输入框：包裹引号、``file:`` 链接、换行
    这类特征不可能是用户逐字输入的中间态，回写不会打断输入。而正斜杠、
    尾部反斜杠**不在此列**——用户手输 ``D:\\`` 时正处在"还没输完"的状态，
    提前清理会把字符吃掉，那些留给输入完成后的 :func:`normalize` 处理。
    """
    text = raw.strip()
    if not text:
        return False
    if text[:1] in _QUOTES or text[-1:] in _QUOTES:
        return True
    if text.lower().startswith("file:"):
        return True
    return bool(_PASTE_MARKS.search(text))


def is_git_repo(path: str | Path) -> bool:
    """``.git`` 可能是目录（普通仓库）也可能是文件（worktree / submodule）。"""
    return (Path(path) / ".git").exists()


def problem(raw: str) -> str | None:
    """返回路径不能用作项目路径的原因，``None`` 表示可用。

    这是"能不能存进台账"的唯一判据，界面提示与保存校验都走它，
    避免出现界面说没问题、点保存才报错的落差。
    """
    text = normalize(raw)
    if not text:
        return "请选择或粘贴本地路径"
    target = Path(text)
    try:
        if not target.exists():
            return "本地路径不存在"
        if not target.is_dir():
            return "该路径不是目录"
    except OSError as exc:  # 超长路径、断开的网络盘等
        return f"无法访问该路径：{exc}"
    if not is_git_repo(target):
        return "该目录不是 Git 仓库（未找到 .git）"
    return None


def suggest_name(raw: str) -> str:
    """从路径猜一个项目名：取最后一段目录名，盘符根没有可用名字。"""
    text = normalize(raw)
    if not text:
        return ""
    name = Path(text).name
    return "" if re.fullmatch(r"[A-Za-z]:", name) else name


# --------------------------------------------------------------------------- 内部
def _strip_text(raw: str) -> str:
    """去掉不可见字符；多行内容（连同说明文字一起复制）只取第一条非空行。"""
    text = raw.translate(_INVISIBLE)
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def _from_file_url(text: str) -> str:
    """``file:///D:/repo`` → ``D:/repo``；不是 ``file:`` 链接则原样返回。"""
    if not text.lower().startswith("file:"):
        return text
    parsed = urlparse(text)
    path = unquote(parsed.path or "")
    if parsed.netloc and parsed.netloc.lower() != "localhost":
        path = f"//{parsed.netloc}{path}"  # file://server/share → \\server\share
    elif _IS_WINDOWS and re.match(r"^/[A-Za-z]:", path):
        path = path[1:]  # file:///D:/repo 的 path 是 /D:/repo
    return path or text


def _unwrap(text: str) -> str:
    """剥掉包裹引号，允许只剩一侧（粘贴时被截断的情况很常见）。"""
    text = text.strip()
    while len(text) >= 2 and text[0] == text[-1] and text[0] in _QUOTES:
        text = text[1:-1].strip()
    if text[:1] in _QUOTES:
        text = text[1:].strip()
    if text[-1:] in _QUOTES:
        text = text[:-1].strip()
    return text


def _to_native(text: str) -> str:
    """Windows：统一成反斜杠、剥掉 ``\\\\?\\`` 前缀、折叠重复分隔符、大写盘符。"""
    text = text.replace("/", "\\")
    if text.startswith("\\\\?\\"):
        text = text[4:]  # \\?\D:\a → D:\a
        if text.upper().startswith("UNC\\"):
            text = "\\\\" + text[4:]  # \\?\UNC\srv\share → \\srv\share

    unc = text.startswith("\\\\")
    body = re.sub(r"\\{2,}", "\\\\", text[2:] if unc else text)
    body = _trim_trailing(body)
    body = _DRIVE_PREFIX.sub(lambda m: m.group(1).upper() + ":", body)
    return ("\\\\" if unc else "") + body


def _trim_trailing(body: str) -> str:
    """去掉多余的尾部反斜杠，但盘符根（``D:\\``）要保留。"""
    if _DRIVE_ROOT.fullmatch(body):
        return body
    return body.rstrip("\\") or body


__all__ = [
    "has_paste_marks",
    "is_git_repo",
    "normalize",
    "problem",
    "suggest_name",
]
