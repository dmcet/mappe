"""Alembic environment. Migrations run programmatically from db.run_migrations()."""

from alembic import context
from sqlmodel import SQLModel

import application_crew.db  # noqa: F401 - registers the tables on SQLModel.metadata

config = context.config
target_metadata = SQLModel.metadata


def run_migrations_online() -> None:
    connection = config.attributes["connection"]
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # SQLite can't ALTER most things; batch mode recreates tables
    )
    with context.begin_transaction():
        context.run_migrations()


run_migrations_online()
