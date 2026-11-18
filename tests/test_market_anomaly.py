import pytest

from bitcoin_ai.market_anomaly import MarketAnomalyError, audit_ohlcv_anomalies


def candles(count=25):
    return [
        {"timestamp": i, "open": 100, "high": 101, "low": 99,
         "close": 100, "volume": 10}
        for i in range(count)
    ]


def test_ohlcv_audit_reports_clean_series_without_alerts():
    report = audit_ohlcv_anomalies(candles())
    assert report["status"] == "no_anomalies_detected"
    assert report["candles_scored"] == 5
    assert report["alerts"] == []


def test_ohlcv_audit_flags_volume_spike_using_prior_only_baseline():
    rows = candles()
    rows[-1]["volume"] = 1000
    report = audit_ohlcv_anomalies(rows)
    assert report["status"] == "alerts_found"
    assert "abnormal_volume" in report["alerts"][0]["reasons"]


def test_ohlcv_audit_flags_extreme_range_and_close_return():
    rows = candles()
    rows[-1].update({"high": 120, "low": 90, "close": 115})
    report = audit_ohlcv_anomalies(rows)
    assert "abnormal_candle_range" in report["alerts"][0]["reasons"]
    assert "extreme_close_return" in report["alerts"][0]["reasons"]


def test_ohlcv_audit_rejects_non_monotonic_timestamps():
    rows = candles()
    rows[-1]["timestamp"] = rows[-2]["timestamp"]
    with pytest.raises(MarketAnomalyError, match="strictly increasing"):
        audit_ohlcv_anomalies(rows)


def test_ohlcv_audit_rejects_invalid_ohlcv_relationships():
    rows = candles()
    rows[-1]["high"] = 98
    with pytest.raises(MarketAnomalyError, match="OHLCV"):
        audit_ohlcv_anomalies(rows)


def test_ohlcv_audit_requires_sufficient_history():
    with pytest.raises(MarketAnomalyError, match="at least"):
        audit_ohlcv_anomalies(candles(10))
