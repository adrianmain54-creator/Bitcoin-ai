import json
import sys
from pathlib import Path

import pytest

import bitcoin_ai.cli as cli


def args():
    return [
        "bitcoin-ai", "research-review",
        "--candidate-ledger", "candidate-trials.json",
        "--experiment-ledger", "holdout-history.json",
        "--plan-id", "plan-123",
        "--dataset-fingerprint", "a" * 64,
        "--test-start", "2026-01-01T00:00:00+00:00",
        "--test-end", "2026-02-01T00:00:00+00:00",
        "--code-revision", "abc123",
        "--proposal-candidate", "momentum:5",
        "--source-candidate", "sma:12",
    ]


def test_research_review_cli_passes_exact_plan_identity(monkeypatch, capsys):
    captured = {}

    def fake_evaluate(*paths, **kwargs):
        captured["paths"] = paths
        captured["kwargs"] = kwargs
        return {
            "status": "eligible_for_human_review",
            "provenance": {"observations": 240},
            "comparisons": {
                "source": {
                    "paired_edge_lower_5pct_pct_points": 0.2,
                    "bootstrap_positive_share_pct": 99.0,
                },
                "cash": {
                    "paired_edge_lower_5pct_pct_points": 0.3,
                    "bootstrap_positive_share_pct": 99.5,
                },
            },
        }

    monkeypatch.setattr(cli, "evaluate_completed_experiment", fake_evaluate)
    monkeypatch.setattr(sys, "argv", args())
    cli.main()
    output = capsys.readouterr().out
    assert "human review only" in output
    assert captured["paths"] == (Path("candidate-trials.json"), Path("holdout-history.json"))
    assert captured["kwargs"]["trial_ids"] == {
        "proposal": "plan-123:proposal",
        "source": "plan-123:source",
        "cash": "plan-123:cash",
    }
    assert captured["kwargs"]["expected_candidate_names"] == {
        "proposal": "momentum:5", "source": "sma:12", "cash": "cash:2",
    }


def test_research_review_cli_supports_machine_readable_output(monkeypatch, capsys):
    report = {"status": "rejected_or_insufficient", "gates": {"safe": False}}
    monkeypatch.setattr(cli, "evaluate_completed_experiment", lambda *a, **k: report)
    monkeypatch.setattr(sys, "argv", args() + ["--json"])
    cli.main()
    assert json.loads(capsys.readouterr().out) == report


def test_research_review_cli_fails_closed_on_evidence_error(monkeypatch):
    def reject(*args, **kwargs):
        raise cli.FreshEvidenceError("overlapping holdout")

    monkeypatch.setattr(cli, "evaluate_completed_experiment", reject)
    monkeypatch.setattr(sys, "argv", args())
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
