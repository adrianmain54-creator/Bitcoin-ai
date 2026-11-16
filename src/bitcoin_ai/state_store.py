"""Atomic JSON persistence for simulation account and risk state."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import json
import math
import os
from pathlib import Path
import tempfile

from .paper_trading import PaperAccount, PaperTradingError
from .risk import RiskState, RiskError


class StateStoreError(RuntimeError):
    """Persistent paper-trading state is missing, corrupt, or incompatible."""


class PaperStateStore:
    VERSION = 1

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def save(self, account: PaperAccount, risk: RiskState) -> None:
        payload = {
            "version": self.VERSION,
            "account": {
                "cash": account.cash, "btc": account.btc,
                "fee_bps": account.fee_bps, "slippage_bps": account.slippage_bps,
                "max_allocation": account.max_allocation, "trades": account.trades,
            },
            "risk": {
                **asdict(risk),
                "last_trade_at": risk.last_trade_at.isoformat() if risk.last_trade_at else None,
            },
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent,
                                             prefix=f".{self.path.name}.", delete=False) as handle:
                temp_name = handle.name
                json.dump(payload, handle, allow_nan=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
        except (OSError, TypeError, ValueError) as exc:
            if temp_name:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass
            raise StateStoreError(f"Could not atomically save paper state: {exc}") from exc

    def load(self) -> tuple[PaperAccount, RiskState]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("version") != self.VERSION:
                raise StateStoreError("Unsupported paper state version")
            a = payload["account"]
            r = payload["risk"]
            account = PaperAccount(
                cash=a["cash"], btc=a["btc"], fee_bps=a["fee_bps"],
                slippage_bps=a["slippage_bps"], max_allocation=a["max_allocation"],
                trades=a["trades"],
            )
            last_trade = datetime.fromisoformat(r["last_trade_at"]) if r["last_trade_at"] else None
            risk = RiskState(
                utc_day=r["utc_day"], day_start_equity=r["day_start_equity"],
                peak_equity=r["peak_equity"], last_trade_at=last_trade,
                halted=r["halted"],
            )
            if not isinstance(risk.utc_day, str) or not risk.utc_day:
                raise ValueError("invalid risk day")
            for value in (risk.day_start_equity, risk.peak_equity):
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                    raise ValueError("invalid persisted risk equity")
            if last_trade and (last_trade.tzinfo is None or last_trade.utcoffset() is None):
                raise ValueError("persisted trade timestamp must be timezone-aware")
            if not isinstance(risk.halted, bool):
                raise ValueError("invalid halted flag")
            return account, risk
        except StateStoreError:
            raise
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError, PaperTradingError, RiskError) as exc:
            raise StateStoreError(f"Could not load valid paper state: {exc}") from exc
