"""应用设置的业务编排：读取、校验、保存，以及"当前生效的参数"。

三条职责，都带判断，所以放在 service 而不是 infra 或 view：

1. **合并**：``默认值（由运行环境/环境变量推导）`` 打底，数据库里存过的值覆盖上去。
   保存值优先 —— 用户在设置页按下的保存就是他真正的意图，环境变量只负责
   "还没保存过时用什么"；
2. **校验**：空路径、相对路径、不存在的模板目录、版本号格式……这些要拦在保存前，
   而不是等到打包时才发现（那时用户已经等了十分钟）；
3. **归一**：用户输入的 ``D:\\Softwares\\`` 与 ``D:\\Softwares`` 存成同一个值，
   所以保存前先过一遍解析再写库，界面回读到的也就是整理过的样子。

服务无状态：每次读取都直接问存储，因此设置页保存后，打包页下一次取参数
就已经是新的了，不需要重启程序。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from pathlib import Path

from cs_pm.infra.ports import SettingsPort
from cs_pm.models.build_options import apply_values, clean_values, values_of
from cs_pm.models.settings import BuildSettings

logger = logging.getLogger(__name__)

__all__ = ["SettingsError", "SettingsService"]

#: Python 版本写成 ``3.12`` 这种两段式
_PYTHON_VERSION = re.compile(r"^\d+\.\d+$")
_ABSOLUTE = re.compile(r"^(?:[a-zA-Z]:[\\/]|\\\\|/)")


class SettingsError(RuntimeError):
    """设置读写失败（数据库被占用、磁盘只读……）。"""


class SettingsService:
    """可配置参数的读写门面。"""

    def __init__(self, *, store: SettingsPort, defaults: BuildSettings) -> None:
        self._store = store
        self._defaults = defaults
        self._current = defaults

    # ------------------------------------------------------------------ 读取
    @property
    def current(self) -> BuildSettings:
        """当前生效的参数包（打包服务每次取都拿到这一份）。"""
        return self._current

    @property
    def defaults(self) -> BuildSettings:
        """默认值：由运行环境推导，未保存过任何设置时生效。"""
        return self._defaults

    def reload(self) -> BuildSettings:
        """从存储重新读一遍。程序启动时调用一次即可；读不出来就退回默认值。"""
        try:
            saved = self._store.load()
        except Exception:
            logger.exception("读取设置失败，改用默认值")
            self._current = self._defaults
            return self._current
        self._current = apply_values(self._defaults, saved)
        if saved:
            logger.info("设置已载入：%d 项", len(saved))
        return self._current

    def values(self) -> dict[str, str]:
        """当前生效值的文本形态（设置页草稿的起点）。"""
        return values_of(self._current)

    def default_values(self) -> dict[str, str]:
        """默认值的文本形态（「恢复默认」用）。"""
        return values_of(self._defaults)

    def settings_of(self, values: Mapping[str, str]) -> BuildSettings:
        """把一份草稿翻译成参数包。**不落库**，供设置页预览命令使用。"""
        return apply_values(self._defaults, values)

    # ------------------------------------------------------------------ 写入
    def save(self, values: Mapping[str, str]) -> BuildSettings:
        """校验并保存。归一后的值才落库，返回保存后生效的参数包。"""
        cleaned = clean_values(self._defaults, values)
        problems = self.problems(cleaned, check_exists=True)
        if problems:
            raise SettingsError(problems[0])
        try:
            self._store.save(cleaned)
        except Exception as exc:
            raise SettingsError(f"设置没能写入数据库：{exc}") from exc
        self._current = apply_values(self._defaults, cleaned)
        logger.info(
            "设置已保存：根目录 %s，模板 %s，目标 %s",
            self._current.output_root,
            self._current.template_dir or "（flet 默认）",
            self._current.target,
        )
        return self._current

    def reset(self) -> BuildSettings:
        """清空保存的设置，回到默认值。"""
        try:
            self._store.clear()
        except Exception as exc:
            raise SettingsError(f"恢复默认失败：{exc}") from exc
        self._current = self._defaults
        logger.info("已恢复默认设置")
        return self._current

    # ------------------------------------------------------------------ 校验
    def problems(self, values: Mapping[str, str], *, check_exists: bool = False) -> tuple[str, ...]:
        """把一份草稿校验成"能不能保存"。

        ``check_exists=False``（编辑途中）只做纯文本判断：敲到一半的路径不该
        立刻报"目录不存在"。真正落盘前（``check_exists=True``）才去看磁盘，
        避免把一个不存在的模板目录存下来 —— 那会让之后的每次打包都失败。
        """
        settings = apply_values(self._defaults, values)
        issues: list[str] = []

        root = settings.output_root.strip()
        if not root:
            issues.append("生成文件夹根目录不能为空：产物必须有地方落盘")
        elif not _ABSOLUTE.match(root):
            issues.append(f"生成文件夹根目录需要写绝对路径（例如 D:\\Softwares）：{root}")

        template = settings.template_dir.strip()
        if template:
            is_remote = "://" in template or template.startswith("git@")
            if not is_remote:
                if not _ABSOLUTE.match(template):
                    issues.append(f"模板所在文件夹需要写绝对路径：{template}")
                elif check_exists and not Path(template).is_dir():
                    issues.append(f"模板所在文件夹不存在：{template}")

        if settings.python_version and not _PYTHON_VERSION.match(settings.python_version):
            issues.append(f"Python 版本要写成「主.次」两段，例如 3.12：{settings.python_version}")

        if settings.build_number and not settings.build_number.isdigit():
            issues.append(f"构建号必须是整数：{settings.build_number}")

        if settings.verbose not in (0, 1, 2):
            issues.append(f"日志详细程度只能是 0 / 1 / 2：{settings.verbose}")

        if settings.executable and check_exists and not Path(settings.executable).is_file():
            issues.append(f"flet 可执行文件不存在：{settings.executable}")

        return tuple(issues)
