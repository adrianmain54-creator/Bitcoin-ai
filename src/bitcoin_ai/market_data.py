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

    def cross_checked_candle_history(
        self, *, interval: str = "5m", limit: int = 100,
        now: datetime | None = None, max_price_deviation: float = 0.01,
        min_overlap: int = 20,
    ) -> dict:
        """Return Binance history only when the aligned Kraken history agrees.

        Both feeds must be fresh, contiguous, and aligned at the latest candle.
        Since each source validates fixed cadence, their tails can then be
        aligned by timestamp. Every overlapping close is compared; a matching
        final price cannot hide a divergent earlier candle.
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
        if isinstance(min_overlap, bool) or not isinstance(min_overlap, int) or min_overlap < 2:
            raise ValueError("min_overlap must be an integer >= 2")
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

        overlap = min(len(binance_closes), len(kraken_closes))
        if overlap < min_overlap:
            raise MarketDataError(
                f"Insufficient cross-source history: {overlap} aligned candles; "
                f"at least {min_overlap} required"
            )
        left = binance_closes[-overlap:]
        right = kraken_closes[-overlap:]
        deviations = [
            abs(a - b) / ((a + b) / 2.0)
            for a, b in zip(left, right)
        ]
        max_deviation = max(deviations)
        mean_deviation = sum(deviations) / len(deviations)
        divergent_count = sum(value > max_price_deviation for value in deviations)
        if divergent_count:
            raise MarketDataError(
                f"Binance/Kraken history contains {divergent_count} divergent "
                f"candles; maximum deviation {max_deviation:.4%} exceeds "
                f"the allowed {max_price_deviation:.4%}"
            )

        return {
            "closes": binance_closes,
            "latest": binance_latest,
            "source_closes": {
                "binance": binance_closes,
                "kraken": kraken_closes,
            },
            "audit": {
                "status": "cross_checked",
                "sources": ["binance", "kraken"],
                "interval": interval,
                "aligned_candles": overlap,
                "max_price_deviation": max_deviation,
                "mean_price_deviation": mean_deviation,
                "max_allowed_deviation": max_price_deviation,
                "divergent_candles": 0,
                "interpretation": (
                    "All overlapping close prices agreed within the configured "
                    "tolerance. This is a consistency check, not proof that either "
                    "exchange or the shared market is manipulation-free."
                ),
            },
        }


    COINBASE_URL = "https://api.exchange.coinbase.com/products/BTC-USDT/candles"
    COINBASE_GRANULARITY = {
        "1m": 60, "5m": 300, "15m": 900,
        "1h": 3600, "1d": 86400,
    }

    def _coinbase(self, interval: str, limit: int, current: datetime):
        """Fetch and validate Coinbase BTC-USDT candles as a third venue."""
        if interval not in self.COINBASE_GRANULARITY:
            raise MarketDataError(
                f"Coinbase does not support {interval}; refusing interval substitution"
            )
        granularity = self.COINBASE_GRANULARITY[interval]
        url = f"{self.COINBASE_URL}?granularity={granularity}"
        rows = self._get_json(url)
        if not isinstance(rows, list):
            raise MarketDataError("Unexpected Coinbase candle response")
        parsed = []
        for row in rows:
            if not isinstance(row, list) or len(row) < 6:
                raise MarketDataError("Invalid Coinbase candle row")
            try:
                open_ts = int(row[0])
                close = float(row[4])
            except (TypeError, ValueError, OverflowError) as exc:
                raise MarketDataError("Invalid Coinbase candle values") from exc
            if not math.isfinite(close) or close <= 0:
                raise MarketDataError("Invalid Coinbase candle close")
            parsed.append((open_ts, close))
        parsed.sort(key=lambda item: item[0])
        if len(parsed) != len({item[0] for item in parsed}):
            raise MarketDataError("Coinbase candle timestamps contain duplicates")
        duration = granularity
        completed = [
            (close, open_ts + duration)
            for open_ts, close in parsed
            if open_ts + duration <= current.timestamp()
        ][-limit:]
        if len(completed) < 2:
            raise MarketDataError("Not enough completed Coinbase candles")
        if any(completed[i][1] - completed[i - 1][1] != duration
               for i in range(1, len(completed))):
            raise MarketDataError("Coinbase candles contain a missing interval")
        return ([item[0] for item in completed],
                datetime.fromtimestamp(completed[-1][1], timezone.utc))

    def cross_checked_three_source_candle_history(
        self, *, interval: str = "5m", limit: int = 100,
        now: datetime | None = None, max_price_deviation: float = 0.01,
        min_overlap: int = 20,
    ) -> dict:
        """Require aligned Binance, Kraken, and Coinbase candle histories.

        All three venues must be fresh and contiguous. Every overlapping close
        is compared pairwise; an unavailable or divergent third source fails
        closed instead of silently downgrading to two-source validation.
        """
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        pair = self.cross_checked_candle_history(
            interval=interval, limit=limit, now=current,
            max_price_deviation=max_price_deviation, min_overlap=min_overlap,
        )
        try:
            third_closes, third_latest = self._coinbase(interval, limit, current)
        except (MarketDataError, URLError, TimeoutError, OSError, ValueError, TypeError, KeyError) as exc:
            raise MarketDataError(f"Three-source check requires Coinbase data: {exc}") from exc
        max_age = 2 * self.INTERVAL_MINUTES[interval] * 60
        if (current - third_latest).total_seconds() > max_age:
            raise MarketDataError("Coinbase latest completed candle is stale")
        if abs((pair["latest"] - third_latest).total_seconds()) > 2:
            raise MarketDataError("Coinbase latest candle timestamp does not align with Binance/Kraken")
        overlap = min(len(pair["closes"]), len(third_closes))
        if overlap < min_overlap:
            raise MarketDataError(
                f"Insufficient three-source history: {overlap} aligned candles; "
                f"at least {min_overlap} required"
            )
        binance = pair["closes"][-overlap:]
        kraken = pair["source_closes"]["kraken"][-overlap:]
        coinbase = third_closes[-overlap:]
        deviations = {
            "binance_kraken": [
                abs(a - b) / ((a + b) / 2.0) for a, b in zip(binance, kraken)
            ],
            "binance_coinbase": [
                abs(a - c) / ((a + c) / 2.0) for a, c in zip(binance, coinbase)
            ],
            "kraken_coinbase": [
                abs(b - c) / ((b + c) / 2.0) for b, c in zip(kraken, coinbase)
            ],
        }
        maxima = {name: max(values) for name, values in deviations.items()}
        means = {name: sum(values) / len(values) for name, values in deviations.items()}
        divergent = {
            name: sum(value > max_price_deviation for value in values)
            for name, values in deviations.items()
        }
        if any(divergent.values()):
            raise MarketDataError(
                "Three-source candle history divergence exceeds tolerance: "
                + ", ".join(f"{name}={count}" for name, count in divergent.items())
            )
        return {
            "closes": pair["closes"],
            "latest": pair["latest"],
            "audit": {
                "status": "three_source_cross_checked",
                "sources": ["binance", "kraken", "coinbase"],
                "product": "BTC-USDT",
                "interval": interval,
                "aligned_candles": overlap,
                "max_price_deviation": maxima,
                "mean_price_deviation": means,
                "max_allowed_deviation": max_price_deviation,
                "divergent_candles": divergent,
                "interpretation": (
                    "All three venue histories agreed within the configured tolerance. "
                    "This reduces dependence on any one venue but cannot rule out "
                    "shared upstream errors, coordinated manipulation, or market-wide distortion."
                ),
            },
        }

    def cross_checked_completed_closes(
        self, *, interval: str = "5m", limit: int = 100,
        now: datetime | None = None, max_price_deviation: float = 0.01,
        min_overlap: int = 20,
    ) -> tuple[list[float], datetime]:
        """Backward-compatible tuple API backed by full-history comparison."""
        result = self.cross_checked_candle_history(
            interval=interval, limit=limit, now=now,
            max_price_deviation=max_price_deviation,
            min_overlap=min_overlap,
        )
        return result["closes"], result["latest"]
