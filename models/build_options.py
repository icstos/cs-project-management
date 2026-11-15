"""可配置的打包参数清单 —— 「设置」页与持久化共用的唯一事实源。

为什么单列一份清单
------------------
``flet build`` 有几十个参数，界面上一行一个字段、库里一个键、命令行一个开关，
三处各写一遍必然很快对不上（改个标签忘改键、加个参数忘加持久化）。这里用一张
表描述"哪些参数可以改、叫什么、怎么编辑、存成什么"，其余地方一律照表办事：

* :mod:`view.settings` 按 ``kind`` 选控件、按 ``group`` 分组渲染，不认识具体字段；
* :mod:`service.settings_service` 按这张表把数据库里的文本还原成
  :class:`~models.settings.BuildSettings`；
* :mod:`infra.flet_cli` 只认参数包，不认这张表（命令行的拼装留在那一层）。

值的形态只有一种：**文本**。布尔存 ``"1"/"0"``，多行列表按行拆，平台这类
枚举存命令行里的原值。这样界面草稿、数据库、表单校验都不必各自处理类型。

本模块是纯计算：不读写文件、不访问数据库、不依赖界面。
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

from models.settings import BUILD_TARGETS, BuildSettings

__all__ = [
    "BUILD_OPTIONS",
    "TRUE_TEXTS",
    "BuildOption",
    "OptionKind",
    "apply_values",
    "clean_values",
    "groups_of",
    "values_of",
]

#: 视为"开"的文本。库里存的是 ``"1"/"0"``，但要能容忍手改过的库与历史值。
TRUE_TEXTS = frozenset({"1", "true", "yes", "on", "是", "开"})


class OptionKind(StrEnum):
    """一个字段怎么编辑、怎么存。"""

    TEXT = "text"
    PATH = "path"
    MULTILINE = "multiline"
    BOOL = "bool"
    CHOICE = "choice"


@dataclass(frozen=True, slots=True)
class BuildOption:
    """一个可配置参数。

    ``flag`` 是它在 ``flet build`` 命令行里的写法，直接展示给用户 —— 界面上
    改的是"模板所在文件夹"，用户同时知道对应 ``--template``，看命令预览时
    才接得上。
    """

    key: str
    label: str
    kind: OptionKind
    group: str
    flag: str = ""
    hint: str = ""
    placeholder: str = ""
    #: ``CHOICE`` 的候选：``(值, 显示文本)``，值就是命令行里的原值
    choices: tuple[tuple[str, str], ...] = ()


#: 全部可配置参数，顺序即界面上的顺序。
BUILD_OPTIONS: tuple[BuildOption, ...] = (
    # ------------------------------------------------------------------ 发布位置
    BuildOption(
        key="output_root",
        label="生成文件夹根目录",
        kind=OptionKind.PATH,
        group="发布位置",
        flag="--output",
        hint="每个项目的产物落在「根目录 / 项目文件夹名」下，例如 D:\\Softwares 下的 "
        "cs-project-management。根目录本身不需要预先存在。重新打包时，已有产物会先"
        "整体移入同级的「历史版本」文件夹（名字追加 -before-时间），不会被删除。",
        placeholder=r"D:\Softwares",
    ),
    BuildOption(
        key="template_dir",
        label="模板所在文件夹",
        kind=OptionKind.PATH,
        group="发布位置",
        flag="--template",
        hint="flet 的 Flutter 引导模板目录（也可以是模板仓库的 git 地址）。留空则用 "
        "flet 自带模板；本地模板能省掉每次构建的下载。",
        placeholder=r"D:\Softwares\dev\flet-build-template\build",
    ),
    BuildOption(
        key="target",
        label="目标平台",
        kind=OptionKind.CHOICE,
        group="发布位置",
        choices=BUILD_TARGETS,
        hint="放在命令行的位置参数上。打包机上还需要对应平台的工具链（Windows 目标只需 "
        "Flutter SDK，Android / iOS 另外要 SDK 与签名）。",
    ),
    BuildOption(
        key="python_version",
        label="Python 版本",
        kind=OptionKind.TEXT,
        group="发布位置",
        flag="--python-version",
        hint="打进产物里的 Python 版本，形如 3.12。",
        placeholder="3.12",
    ),
    # ------------------------------------------------------------------ 应用元信息
    BuildOption(
        key="company",
        label="公司名称",
        kind=OptionKind.TEXT,
        group="应用元信息",
        flag="--company",
        hint="显示在「关于」对话框里。",
        placeholder="cstos.com",
    ),
    BuildOption(
        key="copyright",
        label="版权信息",
        kind=OptionKind.TEXT,
        group="应用元信息",
        flag="--copyright",
        hint="显示在「关于」对话框里，通常写人名或公司名。",
        placeholder="ShawnChen",
    ),
    BuildOption(
        key="org",
        label="组织标识",
        kind=OptionKind.TEXT,
        group="应用元信息",
        flag="--org",
        hint="反向域名写法，与项目名拼成 bundle id，例如 com.cstos。移动端与 macOS 需要。",
        placeholder="com.cstos",
    ),
    BuildOption(
        key="description",
        label="应用描述",
        kind=OptionKind.TEXT,
        group="应用元信息",
        flag="--description",
        hint="一句话说明这个程序是做什么的。",
    ),
    BuildOption(
        key="build_version",
        label="版本号",
        kind=OptionKind.TEXT,
        group="应用元信息",
        flag="--build-version",
        hint="展示给用户的版本号，形如 1.0.0；留空则由 flet 按默认规则给出。",
        placeholder="1.0.0",
    ),
    BuildOption(
        key="build_number",
        label="构建号",
        kind=OptionKind.TEXT,
        group="应用元信息",
        flag="--build-number",
        hint="内部递增的整数，用于区分同版本号的多次构建。",
        placeholder="1",
    ),
    BuildOption(
        key="module_name",
        label="入口模块",
        kind=OptionKind.TEXT,
        group="应用元信息",
        flag="--module-name",
        hint="含应用入口的 Python 模块名。留空则按源目录里的 main.py 自动推断。",
        placeholder="main",
    ),
    # ------------------------------------------------------------------ 构建行为
    BuildOption(
        key="cleanup_app",
        label="精简应用文件",
        kind=OptionKind.BOOL,
        group="构建行为",
        flag="--cleanup-app",
        hint="打包时删掉应用目录里用不到的文件（含本机的 build 目录），产物更小。",
    ),
    BuildOption(
        key="cleanup_packages",
        label="精简依赖包文件",
        kind=OptionKind.BOOL,
        group="构建行为",
        flag="--cleanup-packages",
        hint="打包时删掉依赖包里用不到的文件（测试、示例、类型存根等）。",
    ),
    BuildOption(
        key="compile_app",
        label="预编译应用代码",
        kind=OptionKind.BOOL,
        group="构建行为",
        flag="--compile-app / --no-compile-app",
        hint="把应用自己的 .py 预编译成 .pyc，启动更快、源码不外露。关掉会传 --no-compile-app。",
    ),
    BuildOption(
        key="compile_packages",
        label="预编译依赖代码",
        kind=OptionKind.BOOL,
        group="构建行为",
        flag="--compile-packages / --no-compile-packages",
        hint="把 site-packages 里的 .py 也预编译。关掉会传 --no-compile-packages。",
    ),
    BuildOption(
        key="assume_yes",
        label="自动确认提问",
        kind=OptionKind.BOOL,
        group="构建行为",
        flag="--yes",
        hint="对 flet 的所有提问自动回答 yes（例如 Flutter SDK 版本校验的 Proceed?）。"
        "关掉后遇到这类提问会直接构建失败，需要先在命令行里处理一次。",
    ),
    BuildOption(
        key="skip_flutter_doctor",
        label="跳过环境检查",
        kind=OptionKind.BOOL,
        group="构建行为",
        flag="--skip-flutter-doctor",
        hint="构建失败时不再额外跑一遍 flutter doctor 收集环境报告，日志更短。",
    ),
    BuildOption(
        key="verbose",
        label="日志详细程度",
        kind=OptionKind.CHOICE,
        group="构建行为",
        flag="-v",
        choices=(("0", "标准"), ("1", "详细 (-v)"), ("2", "非常详细 (-vv)")),
        hint="控制台里能看到更多构建细节，排错时打开。",
    ),
    BuildOption(
        key="exclude_globs",
        label="排除文件",
        kind=OptionKind.MULTILINE,
        group="构建行为",
        flag="--exclude",
        hint="每行一条，相对源目录的路径或通配符，例如 tests、docs、*.md。",
        placeholder="tests\ndocs",
    ),
    BuildOption(
        key="include_globs",
        label="额外包含",
        kind=OptionKind.MULTILINE,
        group="构建行为",
        flag="--include",
        hint="每行一条。flet 默认会排除隐藏文件和 __pycache__，这里写上就会被一起打包，例如 .env。",
        placeholder=".env",
    ),
    # ------------------------------------------------------------------ 工具
    BuildOption(
        key="executable",
        label="flet 可执行文件",
        kind=OptionKind.PATH,
        group="工具",
        flag="flet build",
        hint="留空自动探测：先找当前解释器同目录下的 Scripts/flet.exe，再找 PATH。"
        "也可以用环境变量 CSPM_FLET_EXECUTABLE 指定。",
        placeholder="留空自动探测",
    ),
)


def groups_of(options: tuple[BuildOption, ...] = BUILD_OPTIONS) -> tuple[str, ...]:
    """按首次出现的顺序给出分组标题。"""
    seen: list[str] = []
    for option in options:
        if option.group not in seen:
            seen.append(option.group)
    return tuple(seen)


def options_of(
    group: str, options: tuple[BuildOption, ...] = BUILD_OPTIONS
) -> tuple[BuildOption, ...]:
    """某一分组下的字段。"""
    return tuple(option for option in options if option.group == group)


# --------------------------------------------------------------------------- 值
def values_of(settings: BuildSettings) -> dict[str, str]:
    """参数包 → 文本值表（界面草稿、数据库都用这个形态）。"""
    return {option.key: _text(option, getattr(settings, option.key)) for option in BUILD_OPTIONS}


def clean_values(base: BuildSettings, values: Mapping[str, str]) -> dict[str, str]:
    """把用户输入的文本过一遍解析再吐回来。

    「D:\\Softwares\\」与「D:\\Softwares」是同一个目录，但保存后界面里应该
    显示整理过的那个 —— 所以保存前先往返一次，而不是把原样文本塞进库。
    """
    return values_of(apply_values(base, values))


def apply_values(base: BuildSettings, values: Mapping[str, str]) -> BuildSettings:
    """以 ``base`` 为底，套用文本值表。

    缺失的键保持 ``base`` 里的值（老版本存下的库不会有新增字段）；解析失败
    的也回退到 ``base`` —— 校验由 :mod:`service.settings_service` 负责，
    这里只保证"怎么都得到一份能跑的参数"。
    """
    changes: dict[str, object] = {}
    for option in BUILD_OPTIONS:
        if option.key not in values:
            continue
        changes[option.key] = _parse(option, values[option.key], getattr(base, option.key))
    return replace(base, **changes)


# --------------------------------------------------------------------------- 内部
def _text(option: BuildOption, value: object) -> str:
    match option.kind:
        case OptionKind.BOOL:
            return "1" if value else "0"
        case OptionKind.MULTILINE:
            return "\n".join(str(item) for item in (value or ()))  # type: ignore[union-attr]
        case _:
            # ``0`` 是合法取值（verbose=0、build_number=0），不能用 ``value or ""``
            return "" if value is None else str(value)


def _parse(option: BuildOption, raw: str, fallback: object) -> object:
    text = (raw or "").strip()
    match option.kind:
        case OptionKind.BOOL:
            # 空串不是"关"：老库/手改的库缺这一格时保持默认，而不是静默关掉功能
            return (text.lower() in TRUE_TEXTS) if text else bool(fallback)
        case OptionKind.MULTILINE:
            return _lines(text)
        case OptionKind.CHOICE:
            allowed = {key for key, _ in option.choices}
            if text not in allowed:
                return fallback
            # 枚举的"值"可能是数字（verbose），按默认值的类型还原
            return int(text) if isinstance(fallback, int) else text
        case OptionKind.PATH:
            return _path(text, fallback)
        case _:
            return text


def _lines(text: str) -> tuple[str, ...]:
    """多行文本 → 去空行、去重、保序的元组。"""
    items: list[str] = []
    for line in text.splitlines():
        item = line.strip()
        if item and item not in items:
            items.append(item)
    return tuple(items)


def _path(text: str, fallback: object) -> str:
    """路径类字段：去尾部斜杠、把 ``/`` 归一成 ``\\``，但不检查是否存在。

    归一化只在"看起来像本机路径"时做；``https://…`` 这种模板地址原样保留，
    否则 ``--template`` 会被拼成一条不存在的本地路径。
    """
    if not text:
        return ""
    if "://" in text or text.startswith("git@"):
        return text
    try:
        return str(Path(text).expanduser())
    except (OSError, ValueError):  # 非法字符（``*`` / ``?``）就按用户写的存
        return os.path.normpath(text)
