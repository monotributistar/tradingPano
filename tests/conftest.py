"""
tests/conftest.py — Shared pytest fixtures
==========================================

Sets up:
  - Environment variables required by the API (BOT_API_SECRET, no exchange keys)
  - An in-memory SQLite database so tests never touch the real data/trading.db
  - A FastAPI TestClient with the full application
  - Helper fixtures: api_headers (pre-populated X-API-Key)
"""

import os
import pytest

# ── Set env vars BEFORE importing any app code ─────────────────────────────────
TEST_API_SECRET = "test-secret-key-for-pytest-do-not-use-in-prod"
os.environ.setdefault("BOT_API_SECRET",     TEST_API_SECRET)
os.environ.setdefault("DATABASE_URL",       "sqlite:///:memory:")   # in-memory DB
os.environ.setdefault("EXCHANGE_API_KEY",   "")
os.environ.setdefault("EXCHANGE_API_SECRET","")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "")
os.environ.setdefault("TELEGRAM_CHAT_ID",   "")
os.environ.setdefault("LOG_LEVEL",          "WARNING")  # quiet during tests

# Ensure the project root is on PYTHONPATH so `import api.*` works
import sys
from pathlib import Path
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "crypto_bot") not in sys.path:
    sys.path.insert(0, str(ROOT / "crypto_bot"))


# ── Database override — in-memory SQLite ──────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def _override_db():
    """
    Replace the SQLAlchemy engine with an in-memory SQLite instance.
    This runs once for the whole test session.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from api.db import engine as db_engine
    from api.db.models import Base

    mem_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(mem_engine)
    TestSession = sessionmaker(bind=mem_engine)

    # Monkey-patch the module so all app code uses our in-memory engine
    db_engine.engine       = mem_engine
    db_engine.SessionLocal = TestSession

    yield mem_engine


# ── FastAPI TestClient ─────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def client():
    """
    Starlette TestClient wrapping the full FastAPI app.
    Session-scoped so the app starts up only once.
    """
    from fastapi.testclient import TestClient
    from api.main import create_app

    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture
def auth_headers():
    """X-API-Key header dict for authenticated requests."""
    return {"X-API-Key": TEST_API_SECRET}
