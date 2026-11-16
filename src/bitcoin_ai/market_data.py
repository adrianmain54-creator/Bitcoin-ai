"""Public BTC/USDT completed-candle feed using Binance's unauthenticated REST API."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from urllib.error import URLError
from urllib.request import Request, urlopen


class MarketDataError(RuntimeError):
    """Market data could not be fetched or validated."""


class BinanceCandleClient:
    BASE_URL = "https://api.binance.com/api/v3/klines"

    def __init__(self, *, timeout_seconds: float = 8.0, opener=urlopen):
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds
        self._opener = opener

    def completed_closes(self, *, interval: str = "5m", limit: int = 100,
                         now: datetime | None = None) -> tuple[list[float], datetime]:
        """Return validated closes and latest completed candle close timestamp."""
        if interval not in {"1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"}:
            raise ValueError("unsupported candle interval")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 2 <= limit <= 1000:
            raise ValueError("limit must be an integer from 2 to 1000")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("now must be timezone-aware")

        url = f"{self.BASE_URL}?symbol=BTCUSDT&interval={interval}&limit={limit}"
        request = Request(url, headers={"User-Agent": "bitcoin-ai-paper-trader/0.1"})
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                if getattr(response, "status", 200) != 200:
                    raise MarketDataError("Binance candle endpoint returned a non-200 status")
                rows = json.loads(response.read().decode("utf-8"))
        except MarketDataError:
            raise
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise MarketDataError(f"Could not retrieve BTC candles: {exc}") from exc

        if not isinstance(rows, list):
            raise MarketDataError("Unexpected candle response")
        now_ms = int(current.timestamp() * 1000)
        completed = []
        previous_open = None
        for row in rows:
            try:
                if not isinstance(row, list) or len(row) < 7:
                    raise ValueError("short candle row")
                open_ms = int(row[0])
                close = float(row[4])
                close_ms = int(row[6])
                if open_ms <= (previous_open if previous_open is not None else -1):
                    raise ValueError("candle timestamps are not strictly increasing")
                if not math.isfinite(close) or close <= 0 or close_ms <= open_ms:
                    raise ValueError("invalid candle values")
                previous_open = open_ms
                if close_ms < now_ms:
                    completed.append((close, close_ms))
            except (TypeError, ValueError, OverflowError) as exc:
                raise MarketDataError(f"Invalid candle payload: {exc}") from exc

        if len(completed) < 2:
            raise MarketDataError("Not enough completed candles in market response")
        closes = [item[0] for item in completed]
        observed_at = datetime.fromtimestamp(completed[-1][1] / 1000, timezone.utc)
        return closes, observed_at
