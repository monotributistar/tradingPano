"""
Must be imported first in api/main.py.
Adds crypto_bot/ to sys.path so bare imports (from strategies.x, etc.) resolve.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
BOT_DIR = REPO_ROOT / "crypto_bot"
DATA_DIR = REPO_ROOT / "data"

sys.path.insert(0, str(BOT_DIR))

# Ensure data directories exist
(DATA_DIR / "cache").mkdir(parents=True, exist_ok=True)
(DATA_DIR / "backtest_results").mkdir(parents=True, exist_ok=True)
