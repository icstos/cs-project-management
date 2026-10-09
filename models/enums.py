"""领域枚举：项目可见性、工作区变更类型、语义色调。

本模块只承载"领域词汇"及其固定的中文表述，不含任何流程逻辑，因此
所有层都可以放心引用；``Tone`` 描述的是**表达意图**（成功 / 警告 / 危险…）
而不是具体颜色，色值由视图层的设计令牌负责翻译，视图模型因此可以把
``Tone`` 放进状态而不必接触 flet 的颜色常量。
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["ChangeKind", "Permission", "Tone"]


class Permission(StrEnum):
    """项目可见性。"""

    PUBLIC = "public"
    PRIVATE = "private"

    @property
    def label(self) -> str:
        match self:
            case Permission.PUBLIC:
                return "公开"
            case _:
                return "私有"

    @property
    def icon(self) -> str:
        match self:
            case Permission.PUBLIC:
                return "public"
            case _:
                return "lock"

    @classmethod
    def parse(cls, value: str | None) -> Permission:
        """宽松解析：脏数据一律回退为私有。"""
        try:
            return cls(value) if value else cls.PRIVATE
        except ValueError:
            return cls.PRIVATE


class ChangeKind(StrEnum):
    """工作区变更类型。"""

    MODIFIED = "modified"
    ADDED = "added"
    DELETED = "deleted"
    RENAMED = "renamed"
    UNTRACKED = "untracked"
    CONFLICT = "conflict"
    TYPE_CHANGED = "type_changed"

    @property
    def label(self) -> str:
        match self:
            case ChangeKind.ADDED:
                return "新增"
            case ChangeKind.DELETED:
                return "删除"
            case ChangeKind.RENAMED:
                return "重命名"
            case ChangeKind.UNTRACKED:
                return "未跟踪"
            case ChangeKind.CONFLICT:
                return "冲突"
            case ChangeKind.TYPE_CHANGED:
                return "类型变更"
            case _:
                return "已修改"

    @property
    def badge(self) -> str:
        """单字符标记，对齐 git porcelain 的写法。"""
        match self:
            case ChangeKind.ADDED:
                return "A"
            case ChangeKind.DELETED:
                return "D"
            case ChangeKind.RENAMED:
                return "R"
            case ChangeKind.UNTRACKED:
                return "?"
            case ChangeKind.CONFLICT:
                return "U"
            case ChangeKind.TYPE_CHANGED:
                return "T"
            case _:
                return "M"


class Tone(StrEnum):
    """语义色角色。界面只描述意图，具体颜色由视图层决定。"""

    PRIMARY = "primary"
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    DANGER = "danger"
    NEUTRAL = "neutral"
