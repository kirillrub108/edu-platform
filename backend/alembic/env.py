import asyncio
import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import settings
from app.database import Base
from app import models  # noqa: F401  (ensure all models are registered)

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# Only apply alembic.ini's [logger_*] sections when run from the alembic CLI
# (i.e. no logging handlers have been configured yet). When this env.py is
# invoked from `app.main:lifespan` via `command.upgrade`, the FastAPI process
# has already called `logging.basicConfig(level=INFO)` — calling
# `fileConfig()` here would either silence those loggers (the default
# `disable_existing_loggers=True` flips their `disabled` flag) or override
# the root level back to WARN per alembic.ini, both of which would hide
# tracebacks emitted by `app.main.log_and_catch`. Skipping fileConfig in
# that case keeps app logs working while standalone CLI runs still get
# alembic.ini's log config.
if config.config_file_name is not None and not logging.getLogger().handlers:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
