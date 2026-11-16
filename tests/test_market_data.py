import json
from datetime import datetime, timezone

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


def test_bad_candle_fails_closed():
    rows = [candle(0, 100, 299_999), candle(300_000, "nan", 599_999)]
    client = BinanceCandleClient(opener=lambda *a, **k: Response(rows))
    with pytest.raises(MarketDataError):
        client.completed_closes(now=NOW)
