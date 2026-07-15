import asyncio
import json
import os
from logging.config import fileConfig
import re

from alembic import context
import sqlalchemy as sa
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.database import normalize_database_url
from app.models.base import Base
from app.models.review import ReviewRecord, UserSettings  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.question import Question  # noqa: F401
from app.models.analysis import Analysis  # noqa: F401
from app.models.upload import UploadedAsset  # noqa: F401
from app.models.ocr_task import OCRTask  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = os.environ.get("DATABASE_URL", config.get_main_option("sqlalchemy.url"))
config.set_main_option(
    "sqlalchemy.url", normalize_database_url(database_url).replace("%", "%%")
)
target_metadata = Base.metadata


def _json_default_value(rendered: str) -> object:
    """Parse a PostgreSQL/SQLAlchemy JSON literal for semantic comparison."""

    value = rendered.strip()
    value = re.sub(r"::jsonb?\s*$", "", value, flags=re.IGNORECASE).strip()
    while value.startswith("(") and value.endswith(")"):
        value = value[1:-1].strip()
    if len(value) >= 2 and value[0] == value[-1] == "'":
        value = value[1:-1].replace("''", "'")
    return json.loads(value)


def _compare_server_default(
    migration_context,
    inspected_column,
    metadata_column,
    inspected_default,
    metadata_default,
    rendered_metadata_default,
):
    """Avoid PostgreSQL's unsupported ``json = json`` default comparison."""

    del migration_context, inspected_column, metadata_default
    if not isinstance(metadata_column.type, sa.JSON):
        return None
    if inspected_default is None or rendered_metadata_default is None:
        return inspected_default != rendered_metadata_default
    try:
        return _json_default_value(inspected_default) != _json_default_value(
            rendered_metadata_default
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_server_default=_compare_server_default,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_server_default=_compare_server_default,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
