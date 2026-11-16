import json
from datetime import datetime, timezone
from urllib.error import HTTPError

import pytest

from bitcoin_ai.market_data import BinanceCandleClient, MarketDataError


NOW = datetime(2026, 1, 1, 0, 10, tzinfo=timezone.utc)


class Response:
    status = 200
    def __init__(self, payload):
        self.payload = payload
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return json.dumps(self.payload).encode()


def candle(open_ms, close, close_ms):
    return [open_ms, "0", "0", "0", str(close), "0", close_ms]


def test_only_completed_candles_are_returned():
    rows = [candle(0, 100, 299_999), candle(300_000, 101, 599_999),
            candle(600_000, 102, 899_999)]
    client = BinanceCandleClient(opener=lambda *a, **k: Response(rows))
    closes, observed = client.completed_closes(now=NOW)
    assert closes == [100.0, 101.0]
    assert observed == datetime.fromtimestamp(599_999 / 1000, timezone.utc)


def test_kraken_fallback_is_used_when_binance_is_blocked():
    kraken_rows = [
        [int(datetime(2026, 1, 1, 0, 7, tzinfo=timezone.utc).timestamp()), "1", "1", "1", "99", "1", "1", 1],
        [int(datetime(2026, 1, 1, 0, 8, tzinfo=timezone.utc).timestamp()), "1", "1", "1", "100", "1", "1", 1],
        [int(datetime(2026, 1, 1, 0, 9, tzinfo=timezone.utc).timestamp()), "1", "1", "1", "101", "1", "1", 1],
        [int(datetime(2026, 1, 1, 0, 10, tzinfo=timezone.utc).timestamp()), "1", "1", "1", "102", "1", "1", 1],
    ]
    calls = 0
    def opener(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise HTTPError(args[0].full_url, 451, "Unavailable", {}, None)
        return Response({"error": [], "result": {"XXBTZUSDT": kraken_rows, "last": 1}})
    client = BinanceCandleClient(opener=opener)
    closes, observed = client.completed_closes(interval="1m", now=NOW)
    assert closes == [99.0, 100.0, 101.0]
    assert observed == datetime(2026, 1, 1, 0, 10, tzinfo=timezone.utc)
    assert calls == 2


def test_bad_candle_fails_closed_when_both_sources_return_bad_data():
    rows = [candle(0, 100, 299_999), candle(300_000, "nan", 599_999)]
    client = BinanceCandleClient(opener=lambda *a, **k: Response(rows))
    with pytest.raises(MarketDataError):
        client.completed_closes(now=NOW)
