"""应用级常量与可注入的配置对象。

这里只有"值"没有"行为"：默认参数、尺寸、阈值、外部工具约定。
凡是需要探测运行环境（冻结判定、盘符、平台分支）才能得出的路径，
一律放在 ``cs_pm.infra.locations`` —— 那属于基础设施，不属于模型。

配置对象（``GitSettings`` / ``BuildSettings`` / ``ReportSettings``）是冻结
数据类，由组合根在启动时用 ``cs_pm.infra.locations`` 与环境变量装好，再注入服务层。
服务层因此只认识这些"参数包"，不感知它们从哪来。
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field

APP_NAME = "CS 项目管理"
APP_TAGLINE = "本地 Git 项目的台账、提交与统计"
APP_VERSION = "1.0.0"

# --------------------------------------------------------------------------- 窗口
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 840
WINDOW_MIN_WIDTH = 1000
WINDOW_MIN_HEIGHT = 660

# --------------------------------------------------------------------------- 打包存档
#: 旧版本存到产物目录的**同级**文件夹里，例如 ``D:\Softwares\历史版本``。
#: 与产物目录同父级意味着同一个卷：移动只是改个名，瞬间完成、不额外占空间。
HISTORY_DIR_NAME = "历史版本"
#: 存档名 = 原目录名 + 后缀，例如 ``cs-markdown-editor-before-2026-09-05_10-30-22``
ARCHIVE_SUFFIX_PREFIX = "-before-"
ARCHIVE_STAMP_FORMAT = "%Y-%m-%d_%H-%M-%S"

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


#: 目标平台的可选值（与 ``flet build`` 的位置参数一致）。
BUILD_TARGETS: tuple[tuple[str, str], ...] = (
    ("windows", "Windows 桌面"),
    ("macos", "macOS 桌面"),
    ("linux", "Linux 桌面"),
    ("web", "Web"),
    ("apk", "Android APK"),
    ("aab", "Android AAB"),
    ("ipa", "iOS IPA"),
    ("ios-simulator", "iOS 模拟器"),
)


@dataclass(frozen=True, slots=True)
class BuildSettings:
    """``flet build`` 的全部参数。界面预览与实际执行同源，看到的必然是真跑的。

    字段分成三组：

    * **可在「设置」页修改**（每一项都在 :mod:`cs_pm.models.build_options` 里有登记，
      保存后落库）：发布位置、应用元信息、构建行为；
    * **由运行环境推导**（``output_root`` / ``template_dir`` 的默认值、
      ``executable``）：只在没有保存值时生效，见 ``cs_pm.infra.locations``；
    * **纯运行期**（三个超时）：不进界面、也不落库。
    """

    output_root: str = r"D:\Softwares"
    template_dir: str = ""
    target: str = "windows"
    python_version: str = "3.12"

    # ---- 应用元信息
    company: str = "cstos.com"
    copyright: str = "ShawnChen"
    org: str = ""
    description: str = ""
    build_version: str = ""
    build_number: str = ""
    module_name: str = ""

    # ---- 构建行为
    #: ``flet build`` 的 ``--cleanup-*-files`` 与预清理目录同名，两处必须一致
    cleanup_globs: tuple[str, ...] = ("build",)
    cleanup_app: bool = True
    cleanup_packages: bool = True
    compile_app: bool = True
    compile_packages: bool = True
    #: 自动回答 flet 的交互提问（``--yes``）。关掉时遇到 "Proceed? [y/n]" 会直接失败
    assume_yes: bool = True
    skip_flutter_doctor: bool = False
    #: ``-v`` 的重复次数：0 不输出、1 标准、2 详细
    verbose: int = 0
    exclude_globs: tuple[str, ...] = ()
    include_globs: tuple[str, ...] = ()

    # ---- 运行期
    #: flet CLI 位置。留空则自动探测（先找当前解释器同目录，再找 PATH）
    executable: str = ""
    executable_env: str = "CSPM_FLET_EXECUTABLE"
    #: 打包很慢（首次构建要下载 Flutter 依赖），超时给足余量
    build_timeout: float = 3600.0
    clean_timeout: float = 300.0
    probe_timeout: float = 60.0


#: 「当前生效的打包参数」的取值入口。设置可以随时改，服务层因此不缓存参数包，
#: 而是每次问一次 —— 否则改完设置还得重启程序。
SettingsProvider = Callable[[], BuildSettings]


@dataclass(frozen=True, slots=True)
class LogSettings:
    """滚动日志参数。目录由 ``cs_pm.infra.locations`` 按运行环境给出。"""

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
    "ARCHIVE_STAMP_FORMAT",
    "ARCHIVE_SUFFIX_PREFIX",
    "BUILD_TARGETS",
    "CHANGE_PREVIEW_LIMIT",
    "HISTORY_DIR_NAME",
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
    "SettingsProvider",
    "env_flag",
]
