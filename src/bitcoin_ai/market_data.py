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
        "1m": 1, "3m": 3, "5m": 5, "15m": 15,
        "30m": 30, "1h": 60, "4h": 240, "1d": 1440,
    }
    KRAKEN_INTERVAL_MINUTES = {
        "1m": 1, "5m": 5, "15m": 15, "30m": 30,
        "1h": 60, "4h": 240, "1d": 1440,
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
        duration_ms = self.INTERVAL_MINUTES[interval] * 60_000
        if any(completed[i][1] - completed[i - 1][1] != duration_ms
               for i in range(1, len(completed))):
            raise MarketDataError("Binance candles contain a missing interval")
        return ([x[0] for x in completed],
                datetime.fromtimestamp(completed[-1][1] / 1000, timezone.utc))

    def _kraken(self, interval: str, limit: int, current: datetime):
        if interval not in self.KRAKEN_INTERVAL_MINUTES:
            raise MarketDataError(f"Kraken does not support {interval}; refusing to substitute a different candle interval")
        minutes = self.KRAKEN_INTERVAL_MINUTES[interval]
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
        if any(completed[i][1] - completed[i - 1][1] != duration
               for i in range(1, len(completed))):
            raise MarketDataError("Kraken candles contain a missing interval")
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

        max_age = 2 * self.INTERVAL_MINUTES[interval] * 60
        try:
            closes, latest = self._binance(interval, limit, current)
            if (current - latest).total_seconds() > max_age:
                raise MarketDataError("Binance latest completed candle is stale")
            return closes, latest
        except (MarketDataError, URLError, TimeoutError, OSError, ValueError, TypeError, KeyError) as binance_error:
            try:
                closes, latest = self._kraken(interval, limit, current)
                if (current - latest).total_seconds() > max_age:
                    raise MarketDataError("Kraken latest completed candle is stale")
                return closes, latest
            except (MarketDataError, URLError, TimeoutError, OSError, ValueError, TypeError, KeyError) as kraken_error:
                raise MarketDataError(
                    f"BTC market data unavailable from Binance and Kraken "
                    f"(Binance: {binance_error}; Kraken: {kraken_error})"
                ) from kraken_error

    def cross_checked_completed_closes(
        self, *, interval: str = "5m", limit: int = 100,
        now: datetime | None = None, max_price_deviation: float = 0.01,
    ) -> tuple[list[float], datetime]:
        """Return Binance closes only when a fresh, aligned Kraken feed agrees.

        Unlike completed_closes(), this method requires both exchanges. It fails
        closed if either source is unavailable, candle timestamps do not align,
        or the latest close prices differ beyond max_price_deviation.
        """
        if interval not in self.INTERVAL_MINUTES:
            raise ValueError("unsupported candle interval")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 2 <= limit <= 1000:
            raise ValueError("limit must be an integer from 2 to 1000")
        if (isinstance(max_price_deviation, bool)
                or not isinstance(max_price_deviation, (int, float))
                or not math.isfinite(max_price_deviation)
                or not 0 < max_price_deviation < 1):
            raise ValueError("max_price_deviation must be a finite fraction between 0 and 1")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("now must be timezone-aware")

        max_age = 2 * self.INTERVAL_MINUTES[interval] * 60
        try:
            binance_closes, binance_latest = self._binance(interval, limit, current)
        except (MarketDataError, URLError, TimeoutError, OSError, ValueError, TypeError, KeyError) as exc:
            raise MarketDataError(f"Cross-check requires Binance data: {exc}") from exc
        try:
            kraken_closes, kraken_latest = self._kraken(interval, limit, current)
        except (MarketDataError, URLError, TimeoutError, OSError, ValueError, TypeError, KeyError) as exc:
            raise MarketDataError(f"Cross-check requires Kraken data: {exc}") from exc

        if (current - binance_latest).total_seconds() > max_age:
            raise MarketDataError("Binance latest completed candle is stale")
        if (current - kraken_latest).total_seconds() > max_age:
            raise MarketDataError("Kraken latest completed candle is stale")
        if abs((binance_latest - kraken_latest).total_seconds()) > 2:
            raise MarketDataError("Binance and Kraken latest candle timestamps do not align")

        binance_price, kraken_price = binance_closes[-1], kraken_closes[-1]
        midpoint = (binance_price + kraken_price) / 2
        deviation = abs(binance_price - kraken_price) / midpoint
        if deviation > max_price_deviation:
            raise MarketDataError(
                f"Binance/Kraken price divergence {deviation:.4%} exceeds "
                f"the allowed {max_price_deviation:.4%}"
            )
        return binance_closes, binance_latest
