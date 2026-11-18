"""Restart-safe continuous paper trader. Simulation only; no exchange execution."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import time
from typing import Callable

from .autopilot import run_paper_cycle
from .market_data import BinanceCandleClient, MarketDataError
from .paper_trading import PaperAccount
from .risk import RiskLimits, new_risk_state
from .state_store import PaperStateStore, StateStoreError
from .forward_validation import evaluate_forward_paper_evidence


class PaperService:
    def __init__(self, *, state_path: str, interval: str = "1m",
                 poll_seconds: float = 60.0, initial_cash: float = 10_000.0,
                 client: BinanceCandleClient | None = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 limits: RiskLimits = RiskLimits()):
        if isinstance(poll_seconds, bool) or not isinstance(poll_seconds, (int, float)) or not math.isfinite(poll_seconds) or poll_seconds < 10:
            raise ValueError("poll_seconds must be a finite number of at least 10 seconds")
        if isinstance(initial_cash, bool) or not isinstance(initial_cash, (int, float)) or not math.isfinite(initial_cash) or initial_cash <= 0:
            raise ValueError("initial_cash must be a finite positive number")
        self.store = PaperStateStore(state_path)
        self.interval = interval
        self.poll_seconds = poll_seconds
        self.initial_cash = initial_cash
        self.client = client or BinanceCandleClient()
        self.clock = clock
        self.limits = limits

    def run_once(self) -> dict:
        now = self.clock()
        # A paper cycle requires two independent exchanges to agree. If either
        # feed is unavailable or timestamps/prices disagree, fail closed: no
        # simulated trade and no account-state mutation.
        closes, observed_at = self.client.cross_checked_completed_closes(
            interval=self.interval, limit=100, now=now
        )
        try:
            account, risk = self.store.load()
        except StateStoreError as exc:
            if self.store.path.exists():
                # Never reset a corrupt account or halted risk state automatically.
                raise
            account = PaperAccount(
                cash=self.initial_cash,
                max_allocation=self.limits.max_allocation,
            )
            risk = new_risk_state(account.equity(closes[-1]), now)

        # The same completed candle may be returned by multiple polls.
        # Never let duplicate observations create repeated decisions or inflate
        # forward-evidence sample counts.
        if account.paper_observations:
            last_seen = datetime.fromisoformat(account.paper_observations[-1]["observed_at"])
            if observed_at <= last_seen:
                return {
                    "mode": "paper",
                    "status": "duplicate_or_stale_observation",
                    "observed_at": observed_at.isoformat(),
                    "state_path": str(self.store.path),
                }

        baseline_equity = account.equity(closes[-1])
        result = run_paper_cycle(
            closes=closes, account=account, risk_state=risk,
            observed_at=observed_at, now=now, limits=self.limits,
        )
        observation = {
            "observed_at": observed_at.isoformat(),
            "price": closes[-1],
            "equity": result.equity,
            "baseline_equity": baseline_equity,
            "signal": result.signal.action,
            "risk_allowed": result.risk.allowed,
            "risk_halted": result.risk.halted,
            "trade_count": len(account.trades),
        }
        account.paper_observations.append(observation)
        self.store.save(account, risk)
        return {
            "mode": "paper",
            "observed_at": observed_at.isoformat(),
            "price": closes[-1],
            "signal": result.signal.action,
            "requested_allocation": result.signal.target_allocation,
            "risk_allowed": result.risk.allowed,
            "risk_halted": result.risk.halted,
            "risk_reason": result.risk.reason,
            "execution": result.execution,
            "equity": result.equity,
            "forward_evidence": evaluate_forward_paper_evidence(account.paper_observations),
            "state_path": str(self.store.path),
        }

    def run_forever(self, *, emit: Callable[[str], None] = print,
                    sleep: Callable[[float], None] = time.sleep) -> None:
        emit("Bitcoin AI paper trader started. Simulation only; Ctrl+C to stop.")
        while True:
            try:
                report = self.run_once()
                emit(json.dumps(report, sort_keys=True))
            except MarketDataError as exc:
                # No trade and no state mutation when the feed is unavailable.
                emit(json.dumps({"mode": "paper", "status": "no_trade",
                                 "reason": str(exc)}, sort_keys=True))
            sleep(self.poll_seconds)
