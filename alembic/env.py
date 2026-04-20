"""
alembic/env.py — Alembic migration environment
================================================

Wires Alembic to the app's SQLAlchemy models and database URL so that
`alembic upgrade head` (CLI) and the programmatic upgrade in `init_db()`
both use the same schema target.

Path resolution
---------------
This file lives at <repo_root>/alembic/env.py.  When `prepend_sys_path = .`
is set in alembic.ini (the default) the repo root is on sys.path, so
`import api.*` resolves correctly without any extra manipulation.

We also import `api.path_setup` to ensure `crypto_bot/` is on sys.path,
which is required by some model-level imports.

Database URL precedence
-----------------------
1. DATABASE_URL environment variable (used by tests and Docker)
2. The ``sqlalchemy.url`` value set programmatically via
   ``cfg.set_main_option("sqlalchemy.url", ...)`` by ``_run_alembic_upgrade()``
3. The ``sqlalchemy.url`` from alembic.ini (fallback for CLI use)
"""

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# ── Path setup — must happen before any api.* import ─────────────────────────

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Trigger crypto_bot/ path insertion (used by strategy imports inside models)
try:
    import api.path_setup  # noqa: F401
except Exception:
    pass

# ── Import models so they register with Base.metadata ─────────────────────────

from api.db.engine import Base       # noqa: E402
from api.db import models            # noqa: F401, E402  — registers all ORM classes

# ── Alembic Config object ──────────────────────────────────────────────────────

config = context.config

# Allow DATABASE_URL env var to override alembic.ini — useful in Docker / CI
_env_url = os.environ.get("DATABASE_URL")
if _env_url:
    config.set_main_option("sqlalchemy.url", _env_url)

# Interpret the config file for Python logging (skip if called programmatically)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata for autogenerate support
target_metadata = Base.metadata


# ── Offline mode (generates SQL without a live connection) ────────────────────

def run_migrations_offline() -> None:
    """
    Run migrations without a live DB connection.
    Writes the SQL to stdout / a file.  Useful for review before applying.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # SQLite needs batch mode for ALTER TABLE operations
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online mode (runs migrations against a live connection) ───────────────────

def run_migrations_online() -> None:
    """
    Run migrations against a live database connection.

    When called programmatically from ``_run_alembic_upgrade()`` in
    ``api/db/engine.py``, the caller injects its existing connection via
    ``config.attributes["connection"]``.  Reusing that connection avoids the
    SQLite write-lock deadlock that occurs when a second engine tries to open
    a concurrent connection to the same on-disk file.

    When invoked from the Alembic CLI (``alembic upgrade head``), no injected
    connection is present, so we fall back to ``engine_from_config`` with
    NullPool as usual.
    """
    injected = config.attributes.get("connection")

    if injected is not None:
        # ── Programmatic path: reuse the app engine's connection ──────────────
        context.configure(
            connection=injected,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    else:
        # ── CLI path: create a fresh connection via NullPool ──────────────────
        connectable = engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                # SQLite needs batch mode to support column-level ALTER TABLE
                render_as_batch=True,
            )
            with context.begin_transaction():
                context.run_migrations()


# ── Entry point ────────────────────────────────────────────────────────────────

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
