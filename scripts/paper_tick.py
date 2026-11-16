"""One scheduled, restart-safe paper-trading tick for GitHub Actions."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from bitcoin_ai.paper_service import PaperService
from bitcoin_ai.state_store import PaperStateStore
from bitcoin_ai.performance import build_performance_report
from bitcoin_ai.market_data import MarketDataError

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "data" / "paper" / "state.json"
STATUS = ROOT / "docs" / "status.json"
INITIAL_CASH = 100.0


def main() -> int:
    previous = {}
    if STATUS.exists():
        try:
            previous = json.loads(STATUS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            previous = {}

    try:
        cycle = PaperService(
            state_path=str(STATE), interval="1m", poll_seconds=60,
            initial_cash=INITIAL_CASH,
        ).run_once()
        account, risk = PaperStateStore(STATE).load()
        report = build_performance_report(
            account, price=cycle["price"], starting_cash=INITIAL_CASH
        )
        payload = {
            "status": "running",
            "mode": "paper",
            "initial_cash": INITIAL_CASH,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "market": {"symbol": "BTCUSDT", "price": cycle["price"],
                       "observed_at": cycle["observed_at"], "interval": "1m"},
            "portfolio": report,
            "decision": {
                "signal": cycle["signal"],
                "requested_allocation": cycle["requested_allocation"],
                "risk_allowed": cycle["risk_allowed"],
                "risk_halted": cycle["risk_halted"],
                "risk_reason": cycle["risk_reason"],
                "execution": cycle["execution"],
            },
            "risk": {
                "halted": risk.halted,
                "utc_day": risk.utc_day,
                "day_start_equity": risk.day_start_equity,
                "peak_equity": risk.peak_equity,
                "last_trade_at": risk.last_trade_at.isoformat() if risk.last_trade_at else None,
                "limits": {"max_allocation_pct": 20, "daily_loss_halt_pct": 2,
                           "drawdown_halt_pct": 10, "cooldown_minutes": 15},
            },
            "recent_trades": account.trades[-30:][::-1],
            "message": "Scheduled paper-trading tick completed. Fake money only.",
        }
    except MarketDataError as exc:
        payload = {
            **previous,
            "status": "market_data_error",
            "mode": "paper",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "message": f"Market data unavailable; no trade or state change: {exc}",
        }
        print(payload["message"])

    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
