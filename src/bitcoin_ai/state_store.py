"""Atomic JSON persistence for simulation account and risk state."""
from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
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
        try:
            # Reconstruct to revalidate fields that callers may have mutated since creation.
            if not isinstance(account, PaperAccount):
                raise ValueError("account must be a PaperAccount")
            PaperAccount(
                cash=account.cash, btc=account.btc, fee_bps=account.fee_bps,
                slippage_bps=account.slippage_bps,
                max_allocation=account.max_allocation, trades=account.trades,
            )
            json.dumps(account.trades, allow_nan=False)
            _validate_risk_state(risk)
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
        except StateStoreError:
            raise
        except (AttributeError, TypeError, ValueError, RiskError) as exc:
            raise StateStoreError(f"Could not save valid paper state: {exc}") from exc

    def load(self) -> tuple[PaperAccount, RiskState]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("version") != self.VERSION:
                raise StateStoreError("Unsupported or invalid paper state document")
            a = payload["account"]
            r = payload["risk"]
            if not isinstance(a, dict) or not isinstance(r, dict):
                raise ValueError("account and risk must be objects")
            trades = a["trades"]
            if not isinstance(trades, list) or any(not isinstance(t, dict) for t in trades):
                raise ValueError("trades must be a list of event objects")
            json.dumps(trades, allow_nan=False)
            account = PaperAccount(
                cash=a["cash"], btc=a["btc"], fee_bps=a["fee_bps"],
                slippage_bps=a["slippage_bps"], max_allocation=a["max_allocation"],
                trades=trades,
            )
            last_trade = datetime.fromisoformat(r["last_trade_at"]) if r["last_trade_at"] else None
            risk = RiskState(
                utc_day=r["utc_day"], day_start_equity=r["day_start_equity"],
                peak_equity=r["peak_equity"], last_trade_at=last_trade,
                halted=r["halted"],
            )
            _validate_risk_state(risk)
            return account, risk
        except StateStoreError:
            raise
        except (OSError, KeyError, TypeError, AttributeError, OverflowError,
                ValueError, json.JSONDecodeError, PaperTradingError, RiskError) as exc:
            raise StateStoreError(f"Could not load valid paper state: {exc}") from exc


def _validate_risk_state(risk: RiskState) -> None:
    if not isinstance(risk, RiskState):
        raise ValueError("risk must be a RiskState")
    if not isinstance(risk.utc_day, str):
        raise ValueError("invalid risk day")
    try:
        date.fromisoformat(risk.utc_day)
    except ValueError as exc:
        raise ValueError("invalid risk day") from exc
    for value in (risk.day_start_equity, risk.peak_equity):
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value <= 0):
            raise ValueError("invalid persisted risk equity")
    if not isinstance(risk.halted, bool):
        raise ValueError("invalid halted flag")
    if risk.last_trade_at is not None and (
        not isinstance(risk.last_trade_at, datetime)
        or risk.last_trade_at.tzinfo is None
        or risk.last_trade_at.utcoffset() is None
    ):
        raise ValueError("persisted trade timestamp must be timezone-aware")
