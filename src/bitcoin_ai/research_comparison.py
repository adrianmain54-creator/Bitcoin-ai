"""Integrity-checked, read-only comparison of completed Bitcoin research evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


class ComparisonError(ValueError):
    """Raised when research artifacts cannot be safely compared."""


def _canonical_hash(value: Any) -> str:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ComparisonError(f"artifact is not canonical JSON: {exc}") from exc
    return hashlib.sha256(raw).hexdigest()


def _compound(values: list[float]) -> float:
    equity = 1.0
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= -1:
            raise ComparisonError("return streams must contain finite numeric returns greater than -100%")
        equity *= 1.0 + value
    return (equity - 1.0) * 100.0


def _max_drawdown(values: list[float]) -> float:
    equity = peak = 1.0
    worst = 0.0
    for value in values:
        equity *= 1.0 + value
        peak = max(peak, equity)
        worst = min(worst, (equity / peak - 1.0) * 100.0)
    return worst


def _verify_receipt(result: dict) -> tuple[dict, dict]:
    if not isinstance(result, dict) or result.get("status") != "completed_research_only":
        raise ComparisonError("a completed research-only controlled result is required")
    if result.get("execution_authority") != "none":
        raise ComparisonError("controlled result has unexpected execution authority")
    plan, report, receipt = result.get("plan"), result.get("research_report"), result.get("reproducibility_receipt")
    if not all(isinstance(x, dict) for x in (plan, report, receipt)):
        raise ComparisonError("plan, research report, and reproducibility receipt are required")
    plan_id = _canonical_hash(plan)
    if result.get("plan_id") != plan_id or receipt.get("plan_id") != plan_id:
        raise ComparisonError("plan identity does not match its canonical fingerprint")
    if receipt.get("dataset_fingerprint") != plan.get("dataset_fingerprint"):
        raise ComparisonError("receipt dataset fingerprint differs from the plan")
    if receipt.get("code_revision") != plan.get("code_revision"):
        raise ComparisonError("receipt code revision differs from the plan")
    if receipt.get("test_window") != plan.get("test_window"):
        raise ComparisonError("receipt test window differs from the plan")
    if receipt.get("research_report_sha256") != _canonical_hash(report):
        raise ComparisonError("research report digest does not match the receipt")
    core = {k: v for k, v in receipt.items() if k not in {"receipt_id", "limitations"}}
    if receipt.get("receipt_id") != _canonical_hash(core):
        raise ComparisonError("reproducibility receipt digest is invalid")
    if receipt.get("experiment_id") != result.get("experiment_id"):
        raise ComparisonError("receipt experiment identity differs from the result")
    return plan, report


def compare_completed_research(controlled_result: dict, evidence_result: dict, *, min_observations: int = 180) -> dict:
    """Summarize validated proposal/source/cash streams and their existing evidence gates.

    This function does not re-evaluate a holdout, calculate new p-values, or alter ledgers.
    """
    plan, report = _verify_receipt(controlled_result)
    if isinstance(min_observations, bool) or not isinstance(min_observations, int) or min_observations < 1:
        raise ComparisonError("min_observations must be a positive integer")
    if not isinstance(evidence_result, dict) or evidence_result.get("evaluation_type") != "read_only_fresh_evidence":
        raise ComparisonError("a read-only fresh-evidence result is required")
    provenance = evidence_result.get("provenance")
    if not isinstance(provenance, dict):
        raise ComparisonError("fresh-evidence provenance is missing")
    window = plan.get("test_window", {})
    for key, expected in (("dataset_fingerprint", plan.get("dataset_fingerprint")),
                          ("code_revision", plan.get("code_revision")),
                          ("test_start", window.get("start")), ("test_end", window.get("end"))):
        if provenance.get(key) != expected:
            raise ComparisonError(f"fresh-evidence {key} differs from the controlled plan")
    fixed = report.get("fixed_candidate_oos_comparison", {}).get("candidates")
    candidates = plan.get("candidates")
    if not isinstance(fixed, dict) or not isinstance(candidates, dict):
        raise ComparisonError("fixed candidate comparison or candidate definitions are missing")
    roles = {"proposal": candidates.get("proposal"), "source": candidates.get("unchanged_source"), "cash": candidates.get("cash")}
    names = {}
    streams = {}
    stress = {}
    for role, definition in roles.items():
        if not isinstance(definition, dict) or set(definition) != {"family", "lookback"}:
            raise ComparisonError(f"{role} candidate definition is malformed")
        name = f"{definition['family']}:{definition['lookback']}"
        names[role] = name
        item = fixed.get(name)
        if not isinstance(item, dict):
            raise ComparisonError(f"research report is missing the {role} candidate")
        streams[role], stress[role] = item.get("returns"), item.get("doubled_cost_returns")
        if not isinstance(streams[role], list) or not isinstance(stress[role], list):
            raise ComparisonError(f"{role} return streams are missing")
    n = len(streams["proposal"])
    if n == 0 or any(len(streams[r]) != n or len(stress[r]) != n for r in roles):
        raise ComparisonError("candidate return streams are empty or not aligned")
    if provenance.get("observations") != n:
        raise ComparisonError("fresh-evidence observation count differs from the report streams")
    if evidence_result.get("comparisons") is None or evidence_result.get("gates") is None:
        raise ComparisonError("fresh-evidence comparisons and gates are required")
    if n < min_observations:
        status = "insufficient_evidence"
    elif _compound(streams["proposal"]) < _compound(streams["source"]) and _compound(streams["proposal"]) < _compound(streams["cash"]):
        status = "proposal_underperforms"
    elif evidence_result.get("status") == "eligible_for_human_review" and all(evidence_result["gates"].values()):
        status = "supports_further_human_review"
    else:
        status = "inconclusive"
    comparisons = {}
    for role in ("source", "cash"):
        comparisons[role] = {
            "proposal_net_return_pct": round(_compound(streams["proposal"]), 6),
            "comparator_net_return_pct": round(_compound(streams[role]), 6),
            "proposal_minus_comparator_pct_points": round(_compound(streams["proposal"]) - _compound(streams[role]), 6),
            "proposal_doubled_cost_return_pct": round(_compound(stress["proposal"]), 6),
            "comparator_doubled_cost_return_pct": round(_compound(stress[role]), 6),
            "proposal_max_drawdown_pct": round(_max_drawdown(streams["proposal"]), 6),
            "comparator_max_drawdown_pct": round(_max_drawdown(streams[role]), 6),
            "existing_fresh_evidence": evidence_result["comparisons"].get(role),
        }
    core = {
        "schema_version": 1, "status": status, "evaluation_type": "comparison_only",
        "research_only": True, "execution_authority": "none",
        "plan_id": controlled_result["plan_id"],
        "receipt_id": controlled_result["reproducibility_receipt"]["receipt_id"],
        "research_report_sha256": controlled_result["reproducibility_receipt"]["research_report_sha256"],
        "dataset_fingerprint": plan["dataset_fingerprint"],
        "test_window": window, "observations": n, "candidate_names": names,
        "comparisons": comparisons,
        "statistical_evidence": {
            "source": evidence_result["comparisons"].get("source"),
            "cash": evidence_result["comparisons"].get("cash"),
            "gates": evidence_result["gates"],
            "fresh_evidence_status": evidence_result.get("status"),
            "corrected_p_values": "not_available_in_supplied_evidence",
        },
        "limitations": [
            "This report summarizes existing evidence; it does not rerun or independently validate the holdout evaluator.",
            "No corrected p-values are supplied by the current paired fresh-evidence result; none are inferred.",
            "Bootstrap bounds depend on block-size and stationarity assumptions; results do not establish future profitability.",
            "A favorable status means further human review only, never a buy/sell instruction or execution authorization.",
        ],
    }
    core["comparison_id"] = _canonical_hash(core)
    return core


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a read-only comparison from completed research JSON artifacts.")
    parser.add_argument("--controlled", required=True, help="Completed controlled-result JSON")
    parser.add_argument("--evidence", required=True, help="Read-only fresh-evidence JSON")
    parser.add_argument("--output", required=True, help="Output comparison JSON")
    parser.add_argument("--min-observations", type=int, default=180)
    args = parser.parse_args()
    try:
        controlled = json.loads(Path(args.controlled).read_text(encoding="utf-8"))
        evidence = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
        result = compare_completed_research(controlled, evidence, min_observations=args.min_observations)
        Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    except (OSError, json.JSONDecodeError, ComparisonError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
