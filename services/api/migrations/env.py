"""Alembic environment. Migrations run as the owner role; the application role never owns tables."""
from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine

from chobra_api.config import settings
from chobra_api.models import Base

url = context.config.get_main_option("sqlalchemy.url") or settings.owner_database_url


def run_migrations_online() -> None:
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
