"""Fetch real completed BTC-USDT OHLCV history from three public venues.

Read-only public endpoints only. No credentials, account access, or order APIs.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from urllib.error import URLError
from urllib.request import Request, urlopen

from .research_ingestion import ResearchIngestionError, prepare_research_dataset


class ResearchMarketFetchError(RuntimeError):
    """A public historical market-data source failed or returned invalid data."""


class PublicResearchMarketIngestor:
    """Fetch and cross-check normalized OHLCV history from three public venues."""

    BINANCE_URL = "https://api.binance.com/api/v3/klines"
    KRAKEN_URL = "https://api.kraken.com/0/public/OHLC"
    COINBASE_URL = "https://api.exchange.coinbase.com/products/BTC-USDT/candles"
    BINANCE_INTERVALS = {"1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"}
    KRAKEN_INTERVALS = {"1m": 1, "5m": 5, "15m": 15, "30m": 30,
                        "1h": 60, "4h": 240, "1d": 1440}
    COINBASE_INTERVALS = {"1m": 60, "5m": 300, "15m": 900,
                          "1h": 3600, "1d": 86400}

    def __init__(self, *, timeout_seconds: float = 8.0, opener=urlopen):
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = float(timeout_seconds)
        self._opener = opener

    def _get_json(self, url: str):
        request = Request(url, headers={"User-Agent": "bitcoin-ai-research/0.1"})
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                if getattr(response, "status", 200) != 200:
                    raise ResearchMarketFetchError("market-data endpoint returned a non-200 status")
                return json.loads(response.read().decode("utf-8"))
        except ResearchMarketFetchError:
            raise
        except (URLError, TimeoutError, OSError, ValueError, TypeError) as exc:
            raise ResearchMarketFetchError(f"public market-data request failed: {exc}") from exc

    @staticmethod
    def _bar(timestamp, open_, high, low, close, volume):
        try:
            values = [float(value) for value in (open_, high, low, close, volume)]
            stamp = datetime.fromtimestamp(float(timestamp), timezone.utc)
        except (TypeError, ValueError, OverflowError, OSError) as exc:
            raise ResearchMarketFetchError("source returned malformed OHLCV values") from exc
        if not all(math.isfinite(value) for value in values):
            raise ResearchMarketFetchError("source returned non-finite OHLCV values")
        return {
            "timestamp": stamp.isoformat(),
            "open": values[0], "high": values[1], "low": values[2],
            "close": values[3], "volume": values[4],
        }

    @staticmethod
    def _interval_seconds(interval: str) -> int:
        units = {"m": 60, "h": 3600, "d": 86400}
        try:
            amount, unit = int(interval[:-1]), interval[-1]
        except (ValueError, TypeError, IndexError) as exc:
            raise ValueError("unsupported interval") from exc
        if amount < 1 or unit not in units:
            raise ValueError("unsupported interval")
        return amount * units[unit]

    def _binance(self, interval: str, limit: int, now: datetime):
        if interval not in self.BINANCE_INTERVALS:
            raise ResearchMarketFetchError(f"Binance does not support {interval}")
        url = f"{self.BINANCE_URL}?symbol=BTCUSDT&interval={interval}&limit={limit}"
        rows = self._get_json(url)
        if not isinstance(rows, list):
            raise ResearchMarketFetchError("unexpected Binance response")
        duration = self._interval_seconds(interval)
        bars = []
        for row in rows:
            if not isinstance(row, list) or len(row) < 7:
                raise ResearchMarketFetchError("malformed Binance candle")
            try:
                start = int(row[0]) / 1000
                end = (int(row[0]) + duration * 1000) / 1000
            except (TypeError, ValueError, OverflowError) as exc:
                raise ResearchMarketFetchError("malformed Binance candle timestamp") from exc
            if end <= now.timestamp():
                bars.append(self._bar(start, row[1], row[2], row[3], row[4], row[5]))
        return bars

    def _kraken(self, interval: str, limit: int, now: datetime):
        if interval not in self.KRAKEN_INTERVALS:
            raise ResearchMarketFetchError(f"Kraken does not support {interval}")
        url = f"{self.KRAKEN_URL}?pair=XBTUSDT&interval={self.KRAKEN_INTERVALS[interval]}"
        payload = self._get_json(url)
        if not isinstance(payload, dict) or payload.get("error"):
            raise ResearchMarketFetchError("Kraken returned an API error")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise ResearchMarketFetchError("unexpected Kraken response")
        rows = next((value for key, value in result.items() if key != "last"), None)
        if not isinstance(rows, list):
            raise ResearchMarketFetchError("Kraken BTC-USDT candles missing")
        duration = self._interval_seconds(interval)
        bars = []
        for row in rows:
            if not isinstance(row, list) or len(row) < 8:
                raise ResearchMarketFetchError("malformed Kraken candle")
            try:
                start = float(row[0])
            except (TypeError, ValueError, OverflowError) as exc:
                raise ResearchMarketFetchError("malformed Kraken candle timestamp") from exc
            if start + duration <= now.timestamp():
                bars.append(self._bar(start, row[1], row[2], row[3], row[4], row[6]))
        return bars[-limit:]

    def _coinbase(self, interval: str, limit: int, now: datetime):
        if interval not in self.COINBASE_INTERVALS:
            raise ResearchMarketFetchError(f"Coinbase does not support {interval}")
        granularity = self.COINBASE_INTERVALS[interval]
        end = now.astimezone(timezone.utc)
        start = end.timestamp() - (limit + 2) * granularity
        start_text = datetime.fromtimestamp(start, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        end_text = end.strftime("%Y-%m-%dT%H:%M:%SZ")
        url = f"{self.COINBASE_URL}?granularity={granularity}&start={start_text}&end={end_text}"
        rows = self._get_json(url)
        if not isinstance(rows, list):
            raise ResearchMarketFetchError("unexpected Coinbase response")
        bars = []
        for row in rows:
            if not isinstance(row, list) or len(row) < 6:
                raise ResearchMarketFetchError("malformed Coinbase candle")
            try:
                stamp = float(row[0])
            except (TypeError, ValueError, OverflowError) as exc:
                raise ResearchMarketFetchError("malformed Coinbase candle timestamp") from exc
            if stamp + granularity <= now.timestamp():
                # Coinbase order: time, low, high, open, close, volume.
                bars.append(self._bar(stamp, row[3], row[2], row[1], row[4], row[5]))
        # Coinbase documents newest-first candle ordering. Verify that contract
        # before reversing; do not sort arbitrary malformed source data.
        stamps = [bar["timestamp"] for bar in bars]
        if any(stamps[index] <= stamps[index + 1] for index in range(len(stamps) - 1)):
            raise ResearchMarketFetchError("Coinbase candles are not in documented newest-first order")
        return list(reversed(bars))[-limit:]

    def fetch_and_prepare(
        self, *, interval: str = "5m", limit: int = 100,
        now: datetime | None = None, max_age_seconds: int = 900,
        max_price_deviation: float = 0.01, min_sources: int = 3,
    ) -> dict:
        """Fetch three venues, then pass untouched OHLCV to strict ingestion."""
        supported_by_all = self.BINANCE_INTERVALS & set(self.KRAKEN_INTERVALS) & set(self.COINBASE_INTERVALS)
        if interval not in supported_by_all:
            raise ValueError("interval is not supported by all three research data providers")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 20 <= limit <= 300:
            raise ValueError("limit must be an integer from 20 to 300")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        retrieved_at = current.astimezone(timezone.utc).isoformat()
        candle_seconds = self._interval_seconds(interval)
        fetchers = (
            ("binance", self._binance),
            ("kraken", self._kraken),
            ("coinbase", self._coinbase),
        )
        payloads = []
        for source, fetcher in fetchers:
            bars = fetcher(interval, limit, current)
            if len(bars) < 20:
                raise ResearchMarketFetchError(
                    f"{source} returned only {len(bars)} completed candles; at least 20 required"
                )
            latest_open = datetime.fromisoformat(bars[-1]["timestamp"].replace("Z", "+00:00"))
            latest_close = latest_open.timestamp() + candle_seconds
            if latest_close > current.timestamp():
                raise ResearchMarketFetchError(f"{source} returned an incomplete future candle")
            if current.timestamp() - latest_close > 2 * candle_seconds:
                raise ResearchMarketFetchError(f"{source} latest completed candle is stale")
            payloads.append({
                "source": source, "symbol": "BTC-USDT", "interval": interval,
                "retrieved_at": retrieved_at, "bars": bars,
            })
        try:
            report = prepare_research_dataset(
                payloads, symbol="BTC-USDT", interval=interval,
                ingested_at=retrieved_at, max_age_seconds=max_age_seconds,
                min_sources=min_sources, max_price_deviation=max_price_deviation,
            )
        except ResearchIngestionError as exc:
            raise ResearchMarketFetchError(f"historical dataset rejected: {exc}") from exc
        report["provider"] = "public-exchange-apis"
        report["limitations"].append(
            "Live provider responses are subject to venue outages, rate limits, and upstream data errors."
        )
        return report
