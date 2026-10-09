"""应用级常量与可注入的配置对象。

这里只有"值"没有"行为"：默认参数、尺寸、阈值、外部工具约定。
凡是需要探测运行环境（冻结判定、盘符、平台分支）才能得出的路径，
一律放在 ``infra.locations`` —— 那属于基础设施，不属于模型。

配置对象（``GitSettings`` / ``BuildSettings`` / ``ReportSettings``）是冻结
数据类，由组合根在启动时用 ``infra.locations`` 与环境变量装好，再注入服务层。
服务层因此只认识这些"参数包"，不感知它们从哪来。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

APP_NAME = "CS 项目管理"
APP_TAGLINE = "本地 Git 项目的台账、提交与统计"
APP_VERSION = "1.0.0"

# --------------------------------------------------------------------------- 窗口
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 840
WINDOW_MIN_WIDTH = 1000
WINDOW_MIN_HEIGHT = 660

# --------------------------------------------------------------------------- 字体
#: 全应用统一使用本地 "阿里巴巴普惠体"。
#: ``FONT_ASSET_PATH`` 是相对 **assets 目录** 的路径，Flet 客户端按此加载；
#: 绝对路径由 ``infra.locations.font_file()`` 给出，仅用于启动时校验。
FONT_FAMILY = "AlibabaPuHuiTi"
FONT_FILE_NAME = "AlibabaPuHuiTi-3-55-Regular.otf"
FONT_ASSET_PATH = f"fonts/{FONT_FILE_NAME}"

# --------------------------------------------------------------------------- 统计
TREND_DAYS_DEFAULT = 30
TREND_DAYS_MAX = 30
REPORT_ROW_LIMIT = 400
CHANGE_PREVIEW_LIMIT = 200


@dataclass(frozen=True, slots=True)
class GitSettings:
    """调用 git 时用到的全部参数。"""

    executable: str = "git"
    timeout: float = 60.0
    #: 批量探测仓库时的并发上限：既要并行提速，又不能一次拉起几十个子进程
    concurrency: int = 6
    #: 单个仓库最多采集多少条提交
    history_limit: int = 5000


@dataclass(frozen=True, slots=True)
class BuildSettings:
    """``flet build`` 的全部参数。界面预览与实际执行同源，看到的必然是真跑的。"""

    output_root: str = r"D:\Softwares"
    template_dir: str = ""
    target: str = "windows"
    company: str = "cstos.com"
    copyright: str = "ShawnChen"
    python_version: str = "3.12"
    #: ``flet build`` 的 ``--cleanup-*-files`` 与预清理目录同名，两处必须一致
    cleanup_globs: tuple[str, ...] = ("build",)
    #: flet CLI 位置。留空则自动探测（先找当前解释器同目录，再找 PATH）
    executable: str = ""
    executable_env: str = "CSPM_FLET_EXECUTABLE"
    #: 打包很慢（首次构建要下载 Flutter 依赖），超时给足余量
    build_timeout: float = 3600.0
    clean_timeout: float = 300.0
    probe_timeout: float = 60.0


@dataclass(frozen=True, slots=True)
class LogSettings:
    """滚动日志参数。目录由 ``infra.locations`` 按运行环境给出。"""

    file_name: str = "app.log"
    max_bytes: int = 2 * 1024 * 1024
    backups: int = 5
    level_env: str = "CSPM_LOG_LEVEL"
    default_level: str = "INFO"
    #: 按名字**前缀**降噪的框架 logger（运行期才创建的 logger 也管得住）
    noise: tuple[tuple[str, str], ...] = field(
        default=(
            ("flet", "INFO"),
            ("asyncio", "INFO"),
            ("sqlalchemy", "WARNING"),
            ("PIL", "WARNING"),
        )
    )


# --------------------------------------------------------------------------- 环境变量
def env_flag(name: str, default: str) -> str:
    """读一个环境变量，空串视为未设置。"""
    return os.environ.get(name) or default


__all__ = [
    "APP_NAME",
    "APP_TAGLINE",
    "APP_VERSION",
    "CHANGE_PREVIEW_LIMIT",
    "FONT_ASSET_PATH",
    "FONT_FAMILY",
    "FONT_FILE_NAME",
    "REPORT_ROW_LIMIT",
    "TREND_DAYS_DEFAULT",
    "TREND_DAYS_MAX",
    "WINDOW_HEIGHT",
    "WINDOW_MIN_HEIGHT",
    "WINDOW_MIN_WIDTH",
    "WINDOW_WIDTH",
    "BuildSettings",
    "GitSettings",
    "LogSettings",
    "env_flag",
]
