"""Read-only health checks for persisted simulation-only paper trading state."""
from __future__ import annotations

from datetime import datetime, timezone
import math

from .forward_validation import evaluate_forward_paper_evidence, verify_observation_chain
from .performance_anomaly import evaluate_performance_anomalies
from .drawdown_monitor import summarize_drawdown
from .state_store import PaperStateStore, StateStoreError


def build_paper_health_report(state_path, *, now=None, max_age_seconds=180.0):
    """Report paper-state integrity and freshness without changing or resuming it."""
    if (isinstance(max_age_seconds, bool)
            or not isinstance(max_age_seconds, (int, float))
            or not math.isfinite(max_age_seconds) or max_age_seconds <= 0):
        raise ValueError("max_age_seconds must be a finite positive number")
    now = now or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be a timezone-aware datetime")

    store = PaperStateStore(state_path)
    if not store.path.exists():
        return {
            "status": "not_started", "healthy": False, "alert": "paper_state_missing",
            "state_path": str(store.path), "observations": 0,
            "action": "Start the paper trader to create a persisted simulation account.",
        }
    try:
        account, risk = store.load()
        observations = account.paper_observations
        verify_observation_chain(observations)
        evidence = evaluate_forward_paper_evidence(observations)
    except (StateStoreError, ValueError, TypeError, KeyError) as exc:
        return {
            "status": "corrupt", "healthy": False, "alert": "paper_state_integrity_failure",
            "state_path": str(store.path), "error": str(exc),
            "action": "Stop paper execution and inspect the persisted state; do not reset it automatically.",
        }

    if not observations:
        return {
            "status": "no_observations", "healthy": False,
            "alert": "paper_observations_missing", "state_path": str(store.path),
            "observations": 0,
            "action": "Inspect the paper trader; no valid observation has been recorded yet.",
        }

    last_at = datetime.fromisoformat(observations[-1]["observed_at"])
    age = max(0.0, (now - last_at).total_seconds())
    common = {
        "state_path": str(store.path), "observations": len(observations),
        "last_observed_at": last_at.isoformat(), "last_observation_age_seconds": round(age, 3),
        "max_age_seconds": float(max_age_seconds),
        "forward_evidence_status": evidence["status"],
        "risk_halted": risk.halted,
        "performance_anomalies": evaluate_performance_anomalies(observations),
        "drawdown": summarize_drawdown(observations),
    }
    if risk.halted:
        return {
            **common, "status": "risk_halted", "healthy": False,
            "alert": "risk_halt_active",
            "action": "Keep the risk halt in place and require human review; monitoring never clears it.",
        }
    if age > max_age_seconds:
        return {
            **common, "status": "stale", "healthy": False,
            "alert": "paper_observations_stale",
            "action": "Check market-data connectivity and paper-service process. A newer valid observation clears this freshness alert; it does not override risk controls.",
        }
    if common["performance_anomalies"]["status"] == "anomaly_detected":
        return {
            **common, "status": "review_required", "healthy": False,
            "alert": "strategy_performance_degradation",
            "action": "Pause promotion decisions and review recent strategy performance, market regime, and execution assumptions. This monitor does not change positions or clear risk controls.",
        }
    if evidence["cadence_status"] == "gaps_detected":
        return {
            **common, "status": "review_required", "healthy": False,
            "alert": "paper_observation_cadence_gap",
            "action": "Review missing paper observations and the data/service timeline. Do not treat this evidence window as continuous or use it to promote a strategy.",
        }
    return {
        **common, "status": "healthy", "healthy": True, "alert": None,
        "action": "Paper state is valid and the latest observation is within the freshness limit.",
    }
