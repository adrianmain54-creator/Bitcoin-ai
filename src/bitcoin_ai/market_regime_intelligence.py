"""Conservative market context combining causal regimes and integrity audits.

This module classifies observed conditions; it does not forecast prices or
produce trade instructions. Any integrity alert causes an abstain posture.
"""
from __future__ import annotations

from .backtesting import BacktestError
from .regime import classify_regime


class MarketRegimeIntelligenceError(ValueError):
    """Market context inputs are malformed or insufficient."""


def classify_market_conditions(
    closes,
    *,
    anomaly_report: dict,
    exchange_audit: dict,
    lookback: int = 20,
    high_volatility_threshold: float = 0.04,
    minimum_aligned_candles: int = 20,
) -> dict:
    """Combine trailing price regime with OHLCV and cross-venue audit results.

    `anomaly_report` is the output of audit_ohlcv_anomalies. `exchange_audit`
    is the audit mapping returned by the market-data cross-check. Only a clean
    two- or three-source audit is accepted. All inputs describe completed bars.
    """
    if isinstance(minimum_aligned_candles, bool) or not isinstance(minimum_aligned_candles, int) or minimum_aligned_candles < 2:
        raise MarketRegimeIntelligenceError("minimum_aligned_candles must be an integer >= 2")
    if not isinstance(anomaly_report, dict):
        raise MarketRegimeIntelligenceError("anomaly_report must be a mapping")
    if not isinstance(exchange_audit, dict):
        raise MarketRegimeIntelligenceError("exchange_audit must be a mapping")

    try:
        price = classify_regime(
            closes, lookback=lookback,
            high_volatility_threshold=high_volatility_threshold,
        )
    except (BacktestError, TypeError, ValueError) as exc:
        raise MarketRegimeIntelligenceError(str(exc)) from exc

    status = exchange_audit.get("status")
    sources = exchange_audit.get("sources")
    aligned = exchange_audit.get("aligned_candles")
    divergent = exchange_audit.get("divergent_candles")
    if status not in {"cross_checked", "three_source_cross_checked"}:
        raise MarketRegimeIntelligenceError("exchange audit is not a recognized successful cross-check")
    if not isinstance(sources, list) or len(sources) < 2 or len(set(sources)) != len(sources):
        raise MarketRegimeIntelligenceError("exchange audit must identify at least two unique sources")
    if (isinstance(aligned, bool) or not isinstance(aligned, int)
            or aligned < minimum_aligned_candles):
        raise MarketRegimeIntelligenceError("exchange audit has insufficient aligned candles")
    if status == "three_source_cross_checked" and len(sources) < 3:
        raise MarketRegimeIntelligenceError("three-source audit must identify three sources")
    if divergent not in (0, None) and not (
        isinstance(divergent, dict) and all(value == 0 for value in divergent.values())
    ):
        raise MarketRegimeIntelligenceError("exchange audit reports divergent candles")

    anomaly_status = anomaly_report.get("status")
    alerts = anomaly_report.get("alerts")
    if anomaly_status not in {"alerts_found", "no_anomalies_detected"} or not isinstance(alerts, list):
        raise MarketRegimeIntelligenceError("anomaly report is missing a valid status or alerts list")
    if anomaly_status == "no_anomalies_detected" and alerts:
        raise MarketRegimeIntelligenceError("anomaly report status conflicts with its alerts")
    if anomaly_status == "alerts_found" and not alerts:
        raise MarketRegimeIntelligenceError("anomaly report status conflicts with its alerts")

    high_volatility = price["regime"] == "high_volatility"
    if price["regime"] == "high_volatility":
        trend = "uptrend" if price["momentum_pct"] >= price["trend_threshold_pct"] else (
            "downtrend" if price["momentum_pct"] <= -price["trend_threshold_pct"] else "range"
        )
    else:
        trend = price["regime"]
    regime = f"{trend}_{'high' if high_volatility else 'low'}_volatility"
    risk_flags = []
    if alerts:
        risk_flags.append("ohlcv_anomalies_detected")
    if not alerts and anomaly_status != "no_anomalies_detected":
        risk_flags.append("ohlcv_anomaly_audit_uncertain")

    abstain = bool(risk_flags)
    return {
        "status": "review_required" if abstain else "classified",
        "regime": regime,
        "trend": trend,
        "volatility": "high" if high_volatility else "low",
        "momentum_pct": price["momentum_pct"],
        "realized_volatility_pct_per_bar": price["realized_volatility_pct_per_bar"],
        "lookback": lookback,
        "exchange_sources": list(sources),
        "aligned_candles": aligned,
        "anomaly_alert_count": len(alerts),
        "risk_flags": risk_flags,
        "posture": "abstain" if abstain else "research_only",
        "causal": True,
        "limitations": [
            "Regime labels describe trailing observations; they are not forecasts.",
            "Thresholds are heuristics and require out-of-sample calibration.",
            "A clean exchange cross-check does not prove market-wide data integrity.",
            "Anomaly alerts are not proof of manipulation or spoofing.",
            "This report is not a trade signal and never authorizes live orders.",
        ],
    }
