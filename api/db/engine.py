import logging
import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent.parent / "data"
DB_PATH = DATA_DIR / "trading.db"

# Allow DATABASE_URL env var to override the default SQLite path
_DB_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DB_PATH}")

engine = create_engine(
    _DB_URL,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """
    Initialise the database at API startup.

    - Production / Docker: runs ``alembic upgrade head`` so all pending
      migrations are applied automatically on every deployment.
    - Tests / in-memory SQLite: falls back to ``Base.metadata.create_all``
      because Alembic cannot manage in-memory databases (each connection
      sees a fresh empty DB).
    """
    from api.db import models  # noqa: F401 — register all ORM classes with Base

    db_url = str(engine.url)
    if ":memory:" in db_url:
        logger.debug("In-memory database detected — using create_all (bypassing Alembic)")
        Base.metadata.create_all(bind=engine)
    else:
        _run_alembic_upgrade()


def _run_alembic_upgrade() -> None:
    """
    Run ``alembic upgrade head`` as a subprocess.

    Running Alembic in a child process keeps the migration entirely isolated
    from the app's SQLAlchemy connection pool.  This avoids the SQLite
    write-lock deadlock that occurs when two engine connections to the same
    on-disk file compete for the exclusive lock needed to stamp
    ``alembic_version``.
    """
    import subprocess
    import sys

    ini_path = Path(__file__).parent.parent.parent / "alembic.ini"
    repo_root = str(ini_path.parent)

    try:
        logger.info("Running Alembic migrations…")
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", str(ini_path), "upgrade", "head"],
            capture_output=True,
            text=True,
            cwd=repo_root,
            env={**os.environ, "PYTHONPATH": repo_root},
            timeout=60,
        )
        if result.stdout:
            for line in result.stdout.splitlines():
                logger.info("[alembic] %s", line)
        if result.stderr:
            for line in result.stderr.splitlines():
                logger.debug("[alembic] %s", line)
        if result.returncode != 0:
            raise RuntimeError(
                f"alembic upgrade head exited {result.returncode}:\n{result.stderr}"
            )
        logger.info("Alembic migrations complete")

    except Exception as exc:
        logger.error("Alembic upgrade failed: %s", exc)
        raise
