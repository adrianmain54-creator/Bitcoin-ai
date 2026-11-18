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
    base_ms = int(NOW.timestamp() * 1000) - 600_000
    rows = [candle(base_ms, 100, base_ms + 299_999),
            candle(base_ms + 300_000, 101, base_ms + 599_999),
            candle(base_ms + 600_000, 102, base_ms + 899_999)]
    client = BinanceCandleClient(opener=lambda *a, **k: Response(rows))
    closes, observed = client.completed_closes(now=NOW)
    assert closes == [100.0, 101.0]
    assert observed == datetime.fromtimestamp((base_ms + 599_999) / 1000, timezone.utc)


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


def test_three_minute_fallback_never_substitutes_five_minute_candles():
    calls = 0
    def opener(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise HTTPError(args[0].full_url, 451, "Unavailable", {}, None)
        return Response({"error": [], "result": {"XXBTZUSDT": [], "last": 1}})
    client = BinanceCandleClient(opener=opener)
    with pytest.raises(MarketDataError, match="does not support 3m"):
        client.completed_closes(interval="3m", now=NOW)
    assert calls == 1


def test_missing_candle_interval_is_rejected():
    base_ms = int(NOW.timestamp() * 1000) - 900_000
    rows = [
        candle(base_ms, 100, base_ms + 299_999),
        candle(base_ms + 600_000, 102, base_ms + 899_999),
    ]
    client = BinanceCandleClient(opener=lambda *a, **k: Response(rows))
    with pytest.raises(MarketDataError, match="missing interval"):
        client.completed_closes(now=NOW)


def test_stale_latest_candle_is_rejected():
    base_ms = int(NOW.timestamp() * 1000) - 3_600_000
    rows = [
        candle(base_ms, 100, base_ms + 299_999),
        candle(base_ms + 300_000, 101, base_ms + 599_999),
    ]
    client = BinanceCandleClient(opener=lambda *a, **k: Response(rows))
    with pytest.raises(MarketDataError, match="stale"):
        client.completed_closes(now=NOW)


def cross_check_payloads(binance_latest=100, kraken_latest=100):
    base_ms = int(NOW.timestamp() * 1000) - 600_000
    binance_rows = [
        candle(base_ms, 99, base_ms + 299_999),
        candle(base_ms + 300_000, binance_latest, base_ms + 599_999),
    ]
    base_ts = int(NOW.timestamp()) - 600
    kraken_rows = [
        [base_ts, "1", "1", "1", "99", "1", "1", 1],
        [base_ts + 300, "1", "1", "1", str(kraken_latest), "1", "1", 1],
    ]
    return binance_rows, {"error": [], "result": {"XXBTZUSDT": kraken_rows, "last": 1}}


def test_cross_check_accepts_aligned_exchange_prices():
    binance_rows, kraken_payload = cross_check_payloads(100, 100.4)
    payloads = iter([binance_rows, kraken_payload])
    client = BinanceCandleClient(opener=lambda *a, **k: Response(next(payloads)))
    closes, observed = client.cross_checked_completed_closes(now=NOW, min_overlap=2)
    assert closes == [99.0, 100.0]
    assert observed == datetime.fromtimestamp(((int(NOW.timestamp()) * 1000) - 1) / 1000, timezone.utc)


def test_cross_check_rejects_divergent_exchange_prices():
    binance_rows, kraken_payload = cross_check_payloads(100, 103)
    payloads = iter([binance_rows, kraken_payload])
    client = BinanceCandleClient(opener=lambda *a, **k: Response(next(payloads)))
    with pytest.raises(MarketDataError, match="history contains 1 divergent"):
        client.cross_checked_completed_closes(now=NOW, min_overlap=2)


def test_cross_check_fails_closed_if_one_exchange_is_unavailable():
    binance_rows, _ = cross_check_payloads()
    calls = 0
    def opener(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return Response(binance_rows)
        raise HTTPError(args[0].full_url, 451, "Unavailable", {}, None)
    client = BinanceCandleClient(opener=opener)
    with pytest.raises(MarketDataError, match="requires Kraken"):
        client.cross_checked_completed_closes(now=NOW)


def test_cross_check_rejects_historical_divergence_even_when_latest_prices_match():
    base_ms = int(NOW.timestamp() * 1000) - 1_500_000
    base_ts = int(NOW.timestamp()) - 1_500
    binance_rows = [
        candle(base_ms + i * 300_000, price, base_ms + i * 300_000 + 299_999)
        for i, price in enumerate([100, 101, 102, 103, 104])
    ]
    kraken_rows = [
        [base_ts + i * 300, "1", "1", "1", str(price), "1", "1", 1]
        for i, price in enumerate([100, 110, 102, 103, 104])
    ]
    payloads = iter([
        binance_rows,
        {"error": [], "result": {"XXBTZUSDT": kraken_rows, "last": 1}},
    ])
    client = BinanceCandleClient(opener=lambda *a, **k: Response(next(payloads)))
    with pytest.raises(MarketDataError, match="history contains 1 divergent"):
        client.cross_checked_candle_history(now=NOW, min_overlap=5)


def test_cross_check_reports_full_history_consistency():
    base_ms = int(NOW.timestamp() * 1000) - 1_500_000
    base_ts = int(NOW.timestamp()) - 1_500
    prices = [100, 101, 102, 103, 104]
    binance_rows = [
        candle(base_ms + i * 300_000, price, base_ms + i * 300_000 + 299_999)
        for i, price in enumerate(prices)
    ]
    kraken_rows = [
        [base_ts + i * 300, "1", "1", "1", str(price * 1.001), "1", "1", 1]
        for i, price in enumerate(prices)
    ]
    payloads = iter([
        binance_rows,
        {"error": [], "result": {"XXBTZUSDT": kraken_rows, "last": 1}},
    ])
    client = BinanceCandleClient(opener=lambda *a, **k: Response(next(payloads)))
    report = client.cross_checked_candle_history(
        now=NOW, min_overlap=5, max_price_deviation=0.002,
    )
    assert report["audit"]["status"] == "cross_checked"
    assert report["audit"]["aligned_candles"] == 5
    assert report["audit"]["divergent_candles"] == 0
    assert len(report["closes"]) == 5


def test_cross_check_rejects_insufficient_overlapping_history():
    binance_rows, kraken_payload = cross_check_payloads()
    payloads = iter([binance_rows, kraken_payload])
    client = BinanceCandleClient(opener=lambda *a, **k: Response(next(payloads)))
    with pytest.raises(MarketDataError, match="Insufficient cross-source history"):
        client.cross_checked_candle_history(now=NOW, min_overlap=3)



def test_three_source_check_accepts_aligned_binance_kraken_coinbase_history():
    base = int(NOW.timestamp()) - 25 * 300
    prices = [100.0 + i * 0.1 for i in range(25)]
    binance_rows = [
        candle((base + i * 300) * 1000, price, (base + (i + 1) * 300) * 1000 - 1)
        for i, price in enumerate(prices)
    ]
    kraken_rows = [
        [base + i * 300, "1", "1", "1", str(price), "1", "1", 1]
        for i, price in enumerate(prices)
    ]
    coinbase_rows = [
        [base + i * 300, "1", "1", "1", str(price * 1.001), "1"]
        for i, price in enumerate(prices)
    ][::-1]
    def opener(request, **kwargs):
        url = request.full_url
        if "api.binance.com" in url:
            return Response(binance_rows)
        if "api.kraken.com" in url:
            return Response({"error": [], "result": {"XXBTZUSDT": kraken_rows, "last": 1}})
        return Response(coinbase_rows)
    client = BinanceCandleClient(opener=opener)
    report = client.cross_checked_three_source_candle_history(
        interval="5m", now=NOW, min_overlap=20, max_price_deviation=0.01,
    )
    assert report["audit"]["status"] == "three_source_cross_checked"
    assert report["audit"]["sources"] == ["binance", "kraken", "coinbase"]
    assert report["audit"]["aligned_candles"] == 25


def test_three_source_check_rejects_coinbase_history_divergence():
    base = int(NOW.timestamp()) - 25 * 300
    prices = [100.0 + i * 0.1 for i in range(25)]
    binance_rows = [
        candle((base + i * 300) * 1000, price, (base + (i + 1) * 300) * 1000 - 1)
        for i, price in enumerate(prices)
    ]
    kraken_rows = [
        [base + i * 300, "1", "1", "1", str(price), "1", "1", 1]
        for i, price in enumerate(prices)
    ]
    coinbase_prices = prices.copy()
    coinbase_prices[8] *= 1.05
    coinbase_rows = [
        [base + i * 300, "1", "1", "1", str(price), "1"]
        for i, price in enumerate(coinbase_prices)
    ][::-1]
    def opener(request, **kwargs):
        url = request.full_url
        if "api.binance.com" in url:
            return Response(binance_rows)
        if "api.kraken.com" in url:
            return Response({"error": [], "result": {"XXBTZUSDT": kraken_rows, "last": 1}})
        return Response(coinbase_rows)
    client = BinanceCandleClient(opener=opener)
    with pytest.raises(MarketDataError, match="Three-source candle history divergence"):
        client.cross_checked_three_source_candle_history(
            interval="5m", now=NOW, min_overlap=20, max_price_deviation=0.01,
        )
