"""
Alembic Environment Configuration for PyVolley

This module configures Alembic to work with PyVolley's database models
and configuration. It supports both online (direct database connection)
and offline (SQL script generation) migration modes.
"""

from logging.config import fileConfig
import sys
from pathlib import Path

from sqlalchemy import engine_from_config, pool
from alembic import context

# Add project root to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import PyVolley configuration and models
from src.pyvolley.core.config import get_settings
from src.pyvolley.database.models import Base

# Alembic Config object
config = context.config

# Set up logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for autogeneration
target_metadata = Base.metadata

# Get PyVolley settings
pyvolley_settings = get_settings()


def get_url() -> str:
    """Get database URL from PyVolley configuration."""
    return pyvolley_settings.database_url


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.
    
    This configures the context with just a URL and not an Engine,
    though an Engine is acceptable here as well. By skipping the Engine
    creation we don't even need a DBAPI to be available.
    
    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Compare types for better autogenerate accuracy
        compare_type=True,
        # Compare server defaults
        compare_server_default=True,
        # Include schema in autogenerate
        include_schemas=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode.
    
    In this scenario we need to create an Engine and associate a
    connection with the context.
    """
    # Get engine configuration
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_url()
    
    # Determine pool class based on database type
    if pyvolley_settings.is_postgres:
        poolclass = None  # Use default pool for PostgreSQL
    else:
        poolclass = pool.NullPool  # SQLite doesn't need pooling
    
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=poolclass,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Compare types for better autogenerate accuracy
            compare_type=True,
            # Compare server defaults
            compare_server_default=True,
            # Include schema in autogenerate
            include_schemas=True,
            # Render item names as strings (better for debugging)
            render_as_batch=pyvolley_settings.is_sqlite,  # Use batch for SQLite
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
