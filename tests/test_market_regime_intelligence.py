import pytest

from bitcoin_ai.market_regime_intelligence import (
    MarketRegimeIntelligenceError,
    classify_market_conditions,
)


def clean_inputs():
    return (
        [100.0 + i * 0.2 for i in range(25)],
        {"status": "no_anomalies_detected", "alerts": []},
        {
            "status": "three_source_cross_checked",
            "sources": ["binance", "kraken", "coinbase"],
            "aligned_candles": 25,
            "divergent_candles": {"binance_kraken": 0, "binance_coinbase": 0, "kraken_coinbase": 0},
        },
    )


def test_classifies_clean_uptrend_as_research_only():
    closes, anomalies, exchange = clean_inputs()
    report = classify_market_conditions(
        closes, anomaly_report=anomalies, exchange_audit=exchange
    )
    assert report["status"] == "classified"
    assert report["regime"] == "uptrend_low_volatility"
    assert report["posture"] == "research_only"
    assert report["causal"] is True


def test_anomaly_alert_forces_abstain():
    closes, anomalies, exchange = clean_inputs()
    anomalies = {"status": "alerts_found", "alerts": [{"reasons": ["abnormal_volume"]}]}
    report = classify_market_conditions(
        closes, anomaly_report=anomalies, exchange_audit=exchange
    )
    assert report["status"] == "review_required"
    assert report["posture"] == "abstain"
    assert "ohlcv_anomalies_detected" in report["risk_flags"]


def test_divergent_exchange_audit_is_rejected():
    closes, anomalies, exchange = clean_inputs()
    exchange["divergent_candles"]["binance_kraken"] = 1
    with pytest.raises(MarketRegimeIntelligenceError, match="divergent"):
        classify_market_conditions(
            closes, anomaly_report=anomalies, exchange_audit=exchange
        )


def test_unverified_exchange_audit_is_rejected():
    closes, anomalies, exchange = clean_inputs()
    exchange["status"] = "failed"
    with pytest.raises(MarketRegimeIntelligenceError, match="successful cross-check"):
        classify_market_conditions(
            closes, anomaly_report=anomalies, exchange_audit=exchange
        )


def test_insufficient_exchange_history_is_rejected():
    closes, anomalies, exchange = clean_inputs()
    exchange["aligned_candles"] = 5
    with pytest.raises(MarketRegimeIntelligenceError, match="insufficient"):
        classify_market_conditions(
            closes, anomaly_report=anomalies, exchange_audit=exchange
        )


def test_conflicting_anomaly_report_is_rejected():
    closes, anomalies, exchange = clean_inputs()
    anomalies["alerts"] = [{"reasons": ["abnormal_volume"]}]
    with pytest.raises(MarketRegimeIntelligenceError, match="conflicts"):
        classify_market_conditions(
            closes, anomaly_report=anomalies, exchange_audit=exchange
        )


def test_insufficient_price_history_is_rejected():
    closes, anomalies, exchange = clean_inputs()
    with pytest.raises(MarketRegimeIntelligenceError):
        classify_market_conditions(
            closes[:5], anomaly_report=anomalies, exchange_audit=exchange
        )
