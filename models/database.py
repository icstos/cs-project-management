"""数据库引擎、会话与向前兼容迁移。

设计要点：

* 开启 WAL 与 busy_timeout，配合线程池访问时不会互相阻塞；
* ``session_scope`` 统一负责提交 / 回滚 / 关闭，业务代码不写 try/except 样板；
* ``_add_missing_columns`` 依据实体定义自动补列，新增字段不需要手写迁移脚本。
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import Column, event, inspect, text
from sqlmodel import Session, SQLModel, create_engine

from core.config import DATA_DIR, DB_PATH
from models import entities  # noqa: F401  导入以注册表元数据

logger = logging.getLogger(__name__)

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    echo=False,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _configure_sqlite(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """事务边界：正常退出提交，异常回滚，最后一定关闭。"""
    session = Session(engine, expire_on_commit=False)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """建库建表并补齐历史库缺失的列。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine)
    _add_missing_columns()
    logger.info("数据库就绪：%s", DB_PATH)


def _add_missing_columns() -> None:
    inspector = inspect(engine)
    for table in SQLModel.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        existing = {column["name"] for column in inspector.get_columns(table.name)}
        missing = [column for column in table.columns if column.name not in existing]
        if not missing:
            continue
        logger.info("数据库迁移：%s 补列 %s", table.name, "、".join(c.name for c in missing))
        with engine.begin() as connection:
            for column in missing:
                connection.execute(
                    text(f'ALTER TABLE "{table.name}" ADD COLUMN {_column_ddl(column)}')
                )


def _column_ddl(column: Column) -> str:
    """按实体定义拼出 ALTER TABLE 所需的列声明。"""
    ddl = f'"{column.name}" {column.type.compile(engine.dialect)}'
    default = column.default.arg if column.default is not None else None
    if default is None or callable(default):
        # 无法确定常量默认值时只能允许为空，避免迁移失败
        return ddl
    literal = _sql_literal(default)
    return ddl if column.nullable else f"{ddl} NOT NULL DEFAULT {literal}"


def _sql_literal(value: object) -> str:
    match value:
        case bool():
            return "1" if value else "0"
        case int() | float():
            return str(value)
        case datetime():
            return f"'{value.isoformat(sep=' ')}'"
        case _:
            return "'" + str(value).replace("'", "''") + "'"
