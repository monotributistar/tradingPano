from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from tracker.trade_logger import TradeLogger
from api.db.engine import SessionLocal
from api.db.models import Trade


class DBTradeLogger(TradeLogger):
    def __init__(self, source: str = "paper", backtest_job_id: Optional[int] = None,
                 path: Optional[str] = None):
        if path is None:
            path = str(Path(__file__).parent.parent.parent / "data" / "trades.json")
        super().__init__(path=path)
        self.source = source
        self.backtest_job_id = backtest_job_id

    def log(self, trade: dict):
        super().log(trade)
        self._write_to_db(trade)

    def _write_to_db(self, trade: dict):
        ts = trade.get("timestamp")
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                ts = None

        db = SessionLocal()
        try:
            row = Trade(
                source=self.source,
                backtest_job_id=self.backtest_job_id,
                type=trade.get("type", ""),
                pair=trade.get("pair", ""),
                strategy=trade.get("strategy"),
                price=float(trade.get("price", 0)),
                qty=float(trade.get("qty", 0)),
                fee=float(trade.get("fee", 0)),
                pnl=trade.get("pnl"),
                pnl_pct=trade.get("pnl_pct"),
                reason=trade.get("reason"),
                duration_bars=trade.get("duration_bars"),
                avg_cost=trade.get("avg_cost"),
                timestamp=ts,
            )
            db.add(row)
            db.commit()
        except Exception as exc:
            db.rollback()
            import logging
            logging.getLogger(__name__).warning(f"DB write failed: {exc}")
        finally:
            db.close()
