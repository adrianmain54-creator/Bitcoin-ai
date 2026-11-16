"""Read-only public Bitcoin data adapter with bounded caching and provenance."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Callable
from urllib.error import URLError
from urllib.request import Request, urlopen


class DataSourceError(RuntimeError):
    """Raised when a public data source cannot provide valid data."""


class MempoolSpaceClient:
    """Small dependency-free client for public mempool.space REST endpoints.

    The client never submits transactions or requests wallet/address data.
    Responses are cached in memory for a short TTL to avoid needless requests.
    """

    BASE_URL = "https://mempool.space/api"
    PROVIDER = "mempool.space"

    def __init__(
        self,
        cache_ttl_seconds: int = 30,
        timeout_seconds: float = 5.0,
        opener: Callable = urlopen,
        clock: Callable[[], float] = time.time,
    ):
        if cache_ttl_seconds < 0:
            raise ValueError("cache_ttl_seconds cannot be negative")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.cache_ttl_seconds = cache_ttl_seconds
        self.timeout_seconds = timeout_seconds
        self._opener = opener
        self._clock = clock
        self._cache: dict[str, tuple[float, object]] = {}

    def _get_json(self, path: str) -> tuple[object, float, bool]:
        url = f"{self.BASE_URL}/{path.lstrip('/')}"
        now = self._clock()
        cached = self._cache.get(url)
        if cached and now - cached[0] <= self.cache_ttl_seconds:
            return cached[1], cached[0], True

        request = Request(
            url,
            headers={"User-Agent": "bitcoin-ai/0.1 (+https://github.com/adrianmain54-creator/Bitcoin-ai)"},
        )
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                status = getattr(response, "status", 200)
                if status != 200:
                    raise DataSourceError(f"{self.PROVIDER} returned HTTP {status}")
                payload = json.loads(response.read().decode("utf-8"))
        except DataSourceError:
            raise
        except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
            raise DataSourceError(f"Could not retrieve valid data from {self.PROVIDER}: {exc}") from exc

        fetched_at = self._clock()
        self._cache[url] = (fetched_at, payload)
        return payload, fetched_at, False

    def _record(self, path: str, value_name: str, validator: Callable) -> dict:
        payload, fetched_at, cached = self._get_json(path)
        try:
            value = validator(payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise DataSourceError(f"Unexpected response format from {self.PROVIDER} ({path})") from exc
        age = max(0, self._clock() - fetched_at)
        return {
            "value": value,
            "unit": value_name,
            "provider": self.PROVIDER,
            "source_url": f"{self.BASE_URL}/{path}",
            "observed_at": datetime.fromtimestamp(fetched_at, timezone.utc).isoformat(),
            "age_seconds": round(age, 3),
            "cache_hit": cached,
            "freshness": "cached" if cached else "fresh",
        }

    def snapshot(self, currency: str = "USD") -> dict:
        """Return a timestamped read-only snapshot; never silently substitutes stale data."""
        code = currency.upper()
        if len(code) != 3 or not code.isalpha():
            raise ValueError("currency must be a three-letter ISO-style code")

        price_path = "v1/prices"
        prices, price_time, price_cached = self._get_json(price_path)
        try:
            price = prices[code]
            if isinstance(price, bool) or not isinstance(price, (int, float)) or price <= 0:
                raise ValueError("invalid price")
        except (KeyError, TypeError, ValueError) as exc:
            raise DataSourceError(f"No valid {code} price in {self.PROVIDER} response") from exc

        price_age = max(0, self._clock() - price_time)
        result = {
            "provider": self.PROVIDER,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "currency": code,
            "price": {
                "value": price,
                "unit": code,
                "provider": self.PROVIDER,
                "source_url": f"{self.BASE_URL}/{price_path}",
                "observed_at": datetime.fromtimestamp(price_time, timezone.utc).isoformat(),
                "age_seconds": round(price_age, 3),
                "cache_hit": price_cached,
                "freshness": "cached" if price_cached else "fresh",
            },
            "block_height": self._record(
                "blocks/tip/height", "blocks", lambda value: int(value)
            ),
            "mempool": self._record(
                "mempool", "mempool statistics", lambda value: {
                    "count": int(value["count"]),
                    "vsize": int(value["vsize"]),
                    "total_fee": int(value["total_fee"]),
                }
            ),
            "recommended_fees": self._record(
                "v1/fees/recommended", "sat/vB", lambda value: {
                    key: float(value[key])
                    for key in ("fastestFee", "halfHourFee", "hourFee", "economyFee", "minimumFee")
                }
            ),
            "disclaimer": "Network and market observations are descriptive, not price forecasts or trading signals.",
        }
        return result
