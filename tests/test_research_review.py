import hashlib
import json

import pytest

from bitcoin_ai.research_review import ReviewArtifactError, render_review_html, verify_comparison_artifact


def artifact():
    data = {
        "schema_version": 1, "status": "inconclusive", "evaluation_type": "comparison_only",
        "research_only": True, "execution_authority": "none",
        "plan_id": "plan-123", "receipt_id": "receipt-123",
        "research_report_sha256": "a" * 64, "dataset_fingerprint": "b" * 64,
        "test_window": {"start": "2025-01-01T00:00:00Z", "end": "2025-02-01T00:00:00Z"},
        "observations": 200,
        "candidate_names": {"proposal": "ema:20", "source": "sma:50", "cash": "cash:1"},
        "comparisons": {
            role: {
                "proposal_net_return_pct": 3.0, "comparator_net_return_pct": 2.0,
                "proposal_minus_comparator_pct_points": 1.0,
                "proposal_doubled_cost_return_pct": 1.0,
                "comparator_doubled_cost_return_pct": 0.5,
                "proposal_max_drawdown_pct": -4.0, "comparator_max_drawdown_pct": -3.0,
            } for role in ("source", "cash")
        },
        "statistical_evidence": {"gates": {"paired": False}, "corrected_p_values": "not_available"},
        "limitations": ["No profitability guarantee.", "Human review only."],
    }
    data["comparison_id"] = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return data


def test_valid_artifact_renders_static_review_page():
    page = render_review_html(artifact())
    assert "Research review" in page
    assert "No profitability guarantee." in page
    assert "execution authority" in page.lower() or "Execution authority" in page
    assert "ema:20" in page
    assert "<script" not in page.lower()


def test_modified_artifact_is_rejected():
    data = artifact()
    data["observations"] = 999
    with pytest.raises(ReviewArtifactError, match="fingerprint"):
        verify_comparison_artifact(data)


def test_execution_authority_must_be_none():
    data = artifact()
    data["execution_authority"] = "paper"
    core = {key: value for key, value in data.items() if key != "comparison_id"}
    data["comparison_id"] = hashlib.sha256(json.dumps(core, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    with pytest.raises(ReviewArtifactError, match="research-only"):
        render_review_html(data)


def test_missing_comparison_metrics_fail_closed():
    data = artifact()
    del data["comparisons"]["source"]["proposal_max_drawdown_pct"]
    core = {key: value for key, value in data.items() if key != "comparison_id"}
    data["comparison_id"] = hashlib.sha256(json.dumps(core, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    with pytest.raises(ReviewArtifactError, match="metrics are incomplete"):
        render_review_html(data)


def test_nonfinite_metric_is_rejected():
    data = artifact()
    data["comparisons"]["cash"]["proposal_net_return_pct"] = float("nan")
    with pytest.raises(ReviewArtifactError, match="canonical JSON"):
        render_review_html(data)


def test_html_escapes_untrusted_candidate_names():
    data = artifact()
    data["candidate_names"]["proposal"] = "<script>alert(1)</script>"
    core = {key: value for key, value in data.items() if key != "comparison_id"}
    data["comparison_id"] = hashlib.sha256(json.dumps(core, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    page = render_review_html(data)
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page
