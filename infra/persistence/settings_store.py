"""应用设置的持久化实现（:class:`~infra.ports.SettingsPort`）。

只是一张键值表：读回一个 ``dict[str, str]``，写入做 upsert。怎么解释这些值
（哪些键对应哪个参数、布尔怎么表示）属于 models 与 service，这里一概不管。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime

from sqlmodel import select

from infra.persistence.database import Database
from infra.persistence.entities import SettingEntity

logger = logging.getLogger(__name__)

__all__ = ["SqlSettingsRepository"]


class SqlSettingsRepository:
    """基于 SQLite 的键值型设置存储。"""

    def __init__(self, database: Database) -> None:
        self._db = database

    def load(self) -> dict[str, str]:
        with self._db.session() as session:
            rows = session.exec(select(SettingEntity)).all()
            return {row.key: row.value for row in rows}

    def save(self, values: Mapping[str, str]) -> None:
        """整批写入；已存在的键就地更新，没有的新增。"""
        if not values:
            return
        now = datetime.now()
        with self._db.session() as session:
            for key, value in values.items():
                entity = session.get(SettingEntity, key)
                if entity is None:
                    entity = SettingEntity(key=key, value=value, updated_at=now)
                else:
                    entity.value = value
                    entity.updated_at = now
                session.add(entity)

    def clear(self) -> None:
        """清空全部设置（「恢复默认」用）：删掉记录，读回时自然落到默认值。"""
        with self._db.session() as session:
            for row in session.exec(select(SettingEntity)).all():
                session.delete(row)
        logger.info("已清空保存的设置")
