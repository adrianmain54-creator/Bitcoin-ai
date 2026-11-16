"""Localhost-only read-only web dashboard for the paper trader."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from typing import Callable

from .market_data import BinanceCandleClient
from .performance import build_performance_report
from .state_store import PaperStateStore
from .strategy import generate_signal

WEB_ROOT = Path(__file__).resolve().parents[2] / "web"


def build_dashboard_status(*, state_path: str, initial_cash: float = 10_000.0,
                           interval: str = "1m", client=None) -> dict:
    account, risk = PaperStateStore(state_path).load()
    feed = client or BinanceCandleClient()
    closes, observed_at = feed.completed_closes(interval=interval, limit=100)
    report = build_performance_report(
        account, price=closes[-1], starting_cash=initial_cash
    )
    signal = generate_signal(closes, max_allocation=account.max_allocation)
    return {
        **report,
        "observed_at": observed_at.isoformat(),
        "signal": {
            "action": signal.action,
            "target_allocation": signal.target_allocation,
            "reason": signal.reason,
            "fast_sma": signal.fast_sma,
            "slow_sma": signal.slow_sma,
        },
        "risk": {
            "halted": risk.halted,
            "utc_day": risk.utc_day,
            "day_start_equity": risk.day_start_equity,
            "peak_equity": risk.peak_equity,
            "last_trade_at": risk.last_trade_at.isoformat() if risk.last_trade_at else None,
        },
        "recent_trades": account.trades[-20:][::-1],
        "execution_mode": "PAPER ONLY — dashboard is read-only",
    }


def make_handler(*, state_path: str, initial_cash: float, interval: str,
                 status_provider: Callable = build_dashboard_status):
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/api/status":
                try:
                    payload = status_provider(
                        state_path=state_path, initial_cash=initial_cash,
                        interval=interval,
                    )
                    self._send(200, "application/json; charset=utf-8",
                               json.dumps(payload, allow_nan=False).encode("utf-8"))
                except Exception as exc:
                    self._send(503, "application/json; charset=utf-8",
                               json.dumps({"error": str(exc)}).encode("utf-8"))
                return
            if self.path in ("/", "/index.html"):
                page = WEB_ROOT / "index.html"
                try:
                    self._send(200, "text/html; charset=utf-8", page.read_bytes())
                except OSError:
                    self._send(404, "text/plain; charset=utf-8", b"Dashboard files not found")
                return
            self._send(404, "text/plain; charset=utf-8", b"Not found")

        def do_POST(self):
            self._send(405, "text/plain; charset=utf-8", b"Read-only dashboard")

        def _send(self, status, content_type, body):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args):
            return

    return DashboardHandler


def serve_dashboard(*, state_path: str, initial_cash: float = 10_000.0,
                    interval: str = "1m", host: str = "127.0.0.1",
                    port: int = 8765) -> None:
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("test dashboard must bind to localhost only")
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    server = ThreadingHTTPServer(
        (host, port),
        make_handler(state_path=state_path, initial_cash=initial_cash, interval=interval),
    )
    print(f"Bitcoin AI test dashboard: http://{host}:{port} (read-only, paper trading only)")
    try:
        server.serve_forever()
    finally:
        server.server_close()
