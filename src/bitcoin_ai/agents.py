"""Small, deterministic advisory agents for the paper-trading coordinator.

These agents are deliberately not language-model trade executors. They produce
auditable votes from completed candle closes; the independent risk engine remains
the final authority over simulated execution.
"""
from __future__ import annotations

from dataclasses import dataclass

from .regime import classify_regime
from .strategy import TradingSignal, generate_signal


@dataclass(frozen=True)
class AgentCouncilReport:
    signal: TradingSignal
    regime: dict
    votes: dict
    decision: str
    confidence: float
    reasons: tuple[str, ...]


def run_agent_council(
    closes: list[float] | tuple[float, ...],
    *,
    max_allocation: float = 0.20,
    current_allocation: float = 0.0,
    fast_window: int = 12,
    slow_window: int = 48,
    momentum_window: int = 10,
    regime_lookback: int = 20,
) -> AgentCouncilReport:
    """Combine independent deterministic votes into a conservative target.

    Trend and momentum must agree to enter. High-volatility conditions halve
    the requested allocation; range conditions also halve it. Downtrends or
    disagreement abstain to cash. This is an experimental advisory layer.
    """
    if isinstance(momentum_window, bool) or not isinstance(momentum_window, int) or momentum_window < 2:
        raise ValueError("momentum_window must be an integer >= 2")
    if isinstance(regime_lookback, bool) or not isinstance(regime_lookback, int) or regime_lookback < 3:
        raise ValueError("regime_lookback must be an integer >= 3")
    if len(closes) < max(slow_window, momentum_window + 1, regime_lookback + 1):
        raise ValueError("insufficient completed closes for agent council")

    baseline = generate_signal(
        closes,
        fast_window=fast_window,
        slow_window=slow_window,
        max_allocation=max_allocation,
        current_allocation=current_allocation,
    )
    momentum_positive = float(closes[-1]) > float(closes[-1 - momentum_window])
    regime = classify_regime(closes, lookback=regime_lookback)

    votes = {
        "trend": "bullish" if baseline.target_allocation > 0 else "bearish",
        "momentum": "bullish" if momentum_positive else "bearish",
        "regime": regime["regime"],
        "skeptic": "clear",
    }
    reasons = [
        "Trend agent: " + baseline.reason,
        "Momentum agent: " + (
            "latest close is above its trailing comparison close."
            if momentum_positive else
            "latest close is not above its trailing comparison close."
        ),
        "Regime agent: " + regime["regime"] + " conditions.",
    ]

    agreement = votes["trend"] == votes["momentum"]
    if not agreement:
        votes["skeptic"] = "veto_disagreement"
        reasons.append("Skeptic agent veto: trend and momentum disagree; abstain.")
        target = 0.0
        decision = "abstain"
    elif votes["trend"] == "bearish" or regime["regime"] == "downtrend":
        target = 0.0
        decision = "cash"
    else:
        target = float(max_allocation)
        if regime["regime"] in {"range", "high_volatility"}:
            target *= 0.5
            votes["skeptic"] = "caution"
            reasons.append("Skeptic agent: reduce exposure in uncertain or volatile conditions.")
            decision = "cautious_long"
        else:
            decision = "long"
    confidence = 1.0 if agreement and regime["regime"] in {"uptrend", "downtrend"} else (0.65 if agreement else 0.0)
    signal = TradingSignal(
        action=("buy" if target > current_allocation + 1e-9 else
                "sell" if target < current_allocation - 1e-9 else "hold"),
        target_allocation=target,
        reason="Agent council " + decision + "; " + " ".join(reasons),
        fast_sma=baseline.fast_sma,
        slow_sma=baseline.slow_sma,
        close=baseline.close,
    )
    return AgentCouncilReport(
        signal=signal,
        regime=regime,
        votes=votes,
        decision=decision,
        confidence=confidence,
        reasons=tuple(reasons),
    )
