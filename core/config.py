"""应用级常量：身份信息、数据目录与运行参数。

只在需要"改配置"的地方引入本模块，业务代码不硬编码路径与阈值。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "CS 项目管理"
APP_TAGLINE = "本地 Git 项目的台账、提交与统计"
APP_VERSION = "1.0.0"

PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def _resolve_data_dir() -> Path:
    """打包运行时写入用户目录，开发运行时复用仓库内 data/。"""
    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
        return base / "cs-project-management"
    return PACKAGE_ROOT / "data"


DATA_DIR = _resolve_data_dir()
DB_PATH = DATA_DIR / "app.db"

# 日志：文件按 2MB 滚动保留 5 份，控制台级别可用环境变量 CSPM_LOG_LEVEL 覆盖
LOG_DIR = DATA_DIR / "logs"
LOG_FILE = LOG_DIR / "app.log"
LOG_LEVEL_ENV = "CSPM_LOG_LEVEL"
LOG_MAX_BYTES = 2 * 1024 * 1024
LOG_BACKUPS = 5

# 字体：全应用统一使用本地 "阿里巴巴普惠体"。
# FONT_ASSET_PATH 是相对 **assets 目录** 的路径，Flet 客户端按此加载字体文件；
# FONT_FILE 是本机绝对路径，仅用于启动时校验文件是否存在。
FONT_FAMILY = "AlibabaPuHuiTi"
FONT_FILE_NAME = "AlibabaPuHuiTi-3-55-Regular.otf"
FONT_ASSET_PATH = f"fonts/{FONT_FILE_NAME}"
FONT_FILE = PACKAGE_ROOT / "assets" / "fonts" / FONT_FILE_NAME

# 窗口
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 840
WINDOW_MIN_WIDTH = 1000
WINDOW_MIN_HEIGHT = 660

# git 调用
GIT_EXECUTABLE = "git"
GIT_CONCURRENCY = 6
GIT_TIMEOUT = 60.0
GIT_HISTORY_LIMIT = 5000

# 统计
TREND_DAYS_DEFAULT = 30
TREND_DAYS_MAX = 30
REPORT_ROW_LIMIT = 400
CHANGE_PREVIEW_LIMIT = 200
