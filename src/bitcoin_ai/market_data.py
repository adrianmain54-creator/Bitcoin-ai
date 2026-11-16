"""Public BTC/USDT completed-candle feed with Binance and Kraken fallback."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from urllib.error import URLError
from urllib.request import Request, urlopen


class MarketDataError(RuntimeError):
    """Market data could not be fetched or validated."""


class BinanceCandleClient:
    """Fetch completed BTC/USDT candles; fall back to Kraken public OHLC."""

    BASE_URL = "https://api.binance.com/api/v3/klines"
    KRAKEN_URL = "https://api.kraken.com/0/public/OHLC"
    INTERVAL_MINUTES = {
        "1m": 1, "3m": 5, "5m": 5, "15m": 15,
        "30m": 30, "1h": 60, "4h": 240, "1d": 1440,
    }

    def __init__(self, *, timeout_seconds: float = 8.0, opener=urlopen):
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds
        self._opener = opener

    def _get_json(self, url: str):
        request = Request(url, headers={"User-Agent": "bitcoin-ai-paper-trader/0.1"})
        with self._opener(request, timeout=self.timeout_seconds) as response:
            if getattr(response, "status", 200) != 200:
                raise MarketDataError("market-data endpoint returned a non-200 status")
            return json.loads(response.read().decode("utf-8"))

    def _binance(self, interval: str, limit: int, current: datetime):
        url = f"{self.BASE_URL}?symbol=BTCUSDT&interval={interval}&limit={limit}"
        rows = self._get_json(url)
        if not isinstance(rows, list):
            raise MarketDataError("Unexpected Binance candle response")
        now_ms = int(current.timestamp() * 1000)
        completed = []
        previous_open = None
        for row in rows:
            if not isinstance(row, list) or len(row) < 7:
                raise MarketDataError("Invalid Binance candle row")
            open_ms, close_ms = int(row[0]), int(row[6])
            close = float(row[4])
            if open_ms <= (previous_open if previous_open is not None else -1):
                raise MarketDataError("Binance candle timestamps are not increasing")
            if not math.isfinite(close) or close <= 0 or close_ms <= open_ms:
                raise MarketDataError("Invalid Binance candle values")
            previous_open = open_ms
            if close_ms < now_ms:
                completed.append((close, close_ms))
        if len(completed) < 2:
            raise MarketDataError("Not enough completed Binance candles")
        return ([x[0] for x in completed],
                datetime.fromtimestamp(completed[-1][1] / 1000, timezone.utc))

    def _kraken(self, interval: str, limit: int, current: datetime):
        minutes = self.INTERVAL_MINUTES[interval]
        url = f"{self.KRAKEN_URL}?pair=XBTUSDT&interval={minutes}"
        payload = self._get_json(url)
        if not isinstance(payload, dict) or payload.get("error"):
            raise MarketDataError("Kraken public OHLC returned an API error")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise MarketDataError("Unexpected Kraken OHLC response")
        rows = next((v for k, v in result.items() if k != "last"), None)
        if not isinstance(rows, list):
            raise MarketDataError("Kraken BTC/USDT pair was not returned")
        now_ts = current.timestamp()
        duration = minutes * 60
        completed = []
        previous_open = None
        for row in rows:
            if not isinstance(row, list) or len(row) < 5:
                raise MarketDataError("Invalid Kraken candle row")
            open_ts = int(row[0])
            close = float(row[4])
            if open_ts <= (previous_open if previous_open is not None else -1):
                raise MarketDataError("Kraken candle timestamps are not increasing")
            if not math.isfinite(close) or close <= 0:
                raise MarketDataError("Invalid Kraken candle values")
            previous_open = open_ts
            if open_ts + duration <= now_ts:
                completed.append((close, open_ts + duration))
        if len(completed) < 2:
            raise MarketDataError("Not enough completed Kraken candles")
        completed = completed[-limit:]
        return ([x[0] for x in completed],
                datetime.fromtimestamp(completed[-1][1], timezone.utc))

    def completed_closes(self, *, interval: str = "5m", limit: int = 100,
                         now: datetime | None = None) -> tuple[list[float], datetime]:
        """Return validated closes and latest completed candle close timestamp."""
        if interval not in self.INTERVAL_MINUTES:
            raise ValueError("unsupported candle interval")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 2 <= limit <= 1000:
            raise ValueError("limit must be an integer from 2 to 1000")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("now must be timezone-aware")

        try:
            return self._binance(interval, limit, current)
        except (MarketDataError, URLError, TimeoutError, OSError, ValueError, TypeError, KeyError) as binance_error:
            try:
                return self._kraken(interval, limit, current)
            except (MarketDataError, URLError, TimeoutError, OSError, ValueError, TypeError, KeyError) as kraken_error:
                raise MarketDataError(
                    f"BTC market data unavailable from Binance and Kraken "
                    f"(Binance: {binance_error}; Kraken: {kraken_error})"
                ) from kraken_error
