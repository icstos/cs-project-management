"""运行时位置解析。

"数据放哪、产物落在哪个盘" 取决于运行环境（是否被 flet 打包、
当前是什么操作系统），这属于基础设施的判断，所以集中在这里；
业务代码只接收已经算好的路径。

所有结果都是纯计算，不创建目录、不探测存在性 —— 需要校验的地方由调用方
显式判断，避免"导入即产生副作用"。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _find_package_root() -> Path:
    """向上找到项目根目录（开发态的仓库根 / 打包态的程序目录）。

    src 布局下本文件位于 ``<root>/src/cs_pm/infra/locations.py``，比扁平布局多两层；
    若仍用固定的 ``parent.parent``，会指到 ``<root>/src/cs_pm``，让 ``data/`` 与
    ``assets/`` 静默错位（不报错，只是读写到错误的地方）。改为向上找真实存在的
    锚点，扁平 / src / 打包三种目录形态都能命中，不依赖固定层数。
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "assets").is_dir() or (parent / "pyproject.toml").is_file():
            return parent
    # 锚点都不存在时的兜底：有 src 那层就取它的上一级，否则取包的上一级。
    parents = here.parents
    for i, parent in enumerate(parents):
        if parent.name == "src":
            return parents[i + 1] if i + 1 < len(parents) else parent
    return parents[1]


#: 仓库根目录。开发态指向项目根，打包后指向解压出来的程序目录。
PACKAGE_ROOT = _find_package_root()


def is_frozen() -> bool:
    """是否运行在 flet 打包出来的程序里。"""
    return bool(getattr(sys, "frozen", False))


def data_dir() -> Path:
    """打包运行时写入用户目录，开发运行时复用仓库内 ``data/``。"""
    if is_frozen():
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
        return base / "cs-project-management"
    return PACKAGE_ROOT / "data"


def database_file() -> Path:
    return data_dir() / "app.db"


def log_dir() -> Path:
    return data_dir() / "logs"


def assets_dir() -> Path:
    return PACKAGE_ROOT / "assets"


def build_output_root(default: str) -> Path:
    """打包产物的落盘根目录。

    环境变量 ``CSPM_BUILD_OUTPUT`` 优先，便于换盘或做隔离验证；
    未设置时使用配置给出的默认发布目录，非 Windows 退回用户主目录下的
    ``Softwares``。
    """
    override = os.environ.get("CSPM_BUILD_OUTPUT")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        return Path(default)
    return Path.home() / "Softwares"


def build_template_dir(output_root: Path, override_env: str = "CSPM_FLET_TEMPLATE") -> Path:
    """Flutter bootstrap 模板目录（对应 ``flet build --template``）。"""
    configured = os.environ.get(override_env)
    if configured:
        return Path(configured).expanduser()
    return output_root / "dev" / "flet-build-template" / "build"


__all__ = [
    "PACKAGE_ROOT",
    "assets_dir",
    "build_output_root",
    "build_template_dir",
    "data_dir",
    "database_file",
    "is_frozen",
    "log_dir",
]
