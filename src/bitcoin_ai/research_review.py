"""Render a verified comparison artifact as a portable, static HTML review page."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
from pathlib import Path
from typing import Any


class ReviewArtifactError(ValueError):
    """Raised when a comparison artifact is incomplete or has been altered."""


def _canonical_hash(value: Any) -> str:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ReviewArtifactError(f"comparison is not canonical JSON: {exc}") from exc
    return hashlib.sha256(encoded).hexdigest()


def verify_comparison_artifact(artifact: dict) -> dict:
    if not isinstance(artifact, dict) or artifact.get("evaluation_type") != "comparison_only":
        raise ReviewArtifactError("comparison-only artifact required")
    if artifact.get("research_only") is not True or artifact.get("execution_authority") != "none":
        raise ReviewArtifactError("artifact is not explicitly research-only")
    if artifact.get("status") not in {
        "insufficient_evidence", "proposal_underperforms", "inconclusive",
        "supports_further_human_review",
    }:
        raise ReviewArtifactError("unknown or missing review status")
    required = ("comparison_id", "plan_id", "receipt_id", "research_report_sha256",
                "dataset_fingerprint", "test_window", "observations", "candidate_names",
                "comparisons", "statistical_evidence", "limitations")
    if any(key not in artifact for key in required):
        raise ReviewArtifactError("comparison artifact is missing required fields")
    if isinstance(artifact["observations"], bool) or not isinstance(artifact["observations"], int) or artifact["observations"] < 0:
        raise ReviewArtifactError("observation count must be a non-negative integer")
    if not isinstance(artifact["test_window"], dict) or not {"start", "end"} <= artifact["test_window"].keys():
        raise ReviewArtifactError("test window is incomplete")
    if not isinstance(artifact["candidate_names"], dict) or not {"proposal", "source", "cash"} <= artifact["candidate_names"].keys():
        raise ReviewArtifactError("candidate role names are incomplete")
    comparisons = artifact["comparisons"]
    if not isinstance(comparisons, dict) or not {"source", "cash"} <= comparisons.keys():
        raise ReviewArtifactError("source and cash comparisons are required")
    metric_keys = ("proposal_net_return_pct", "comparator_net_return_pct",
                   "proposal_minus_comparator_pct_points", "proposal_doubled_cost_return_pct",
                   "comparator_doubled_cost_return_pct", "proposal_max_drawdown_pct",
                   "comparator_max_drawdown_pct")
    for role in ("source", "cash"):
        item = comparisons[role]
        if not isinstance(item, dict) or any(key not in item for key in metric_keys):
            raise ReviewArtifactError(f"{role} comparison metrics are incomplete")
        for key in metric_keys:
            value = item[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ReviewArtifactError(f"{role}.{key} must be finite numeric data")
    if not isinstance(artifact["statistical_evidence"], dict) or not isinstance(artifact["limitations"], list):
        raise ReviewArtifactError("statistical evidence or limitations are malformed")
    core = {key: value for key, value in artifact.items() if key != "comparison_id"}
    if artifact["comparison_id"] != _canonical_hash(core):
        raise ReviewArtifactError("comparison fingerprint does not match artifact contents")
    return artifact


def _fmt(value: float) -> str:
    return f"{value:+.4f}%"


def render_review_html(artifact: dict) -> str:
    data = verify_comparison_artifact(artifact)
    esc = lambda value: html.escape(str(value), quote=True)
    status_labels = {
        "insufficient_evidence": "Insufficient evidence",
        "proposal_underperforms": "Proposal underperforms",
        "inconclusive": "Inconclusive",
        "supports_further_human_review": "Supports further human review",
    }
    rows = []
    for role, label in (("source", "Unchanged source"), ("cash", "Cash baseline")):
        item = data["comparisons"][role]
        rows.append(
            "<tr><th scope=\"row\">" + label + "</th>"
            + "".join("<td>" + _fmt(item[key]) + "</td>" for key in (
                "proposal_net_return_pct", "comparator_net_return_pct",
                "proposal_minus_comparator_pct_points", "proposal_doubled_cost_return_pct",
                "proposal_max_drawdown_pct", "comparator_max_drawdown_pct"))
            + "</tr>"
        )
    limits = "".join("<li>" + esc(item) + "</li>" for item in data["limitations"])
    stats = esc(json.dumps(data["statistical_evidence"], indent=2, sort_keys=True))
    candidates = "".join(
        "<li><strong>" + esc(role.title()) + ":</strong> " + esc(data["candidate_names"][role]) + "</li>"
        for role in ("proposal", "source", "cash")
    )
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Bitcoin AI · Research review</title>
<style>
:root{color-scheme:dark;font-family:Inter,ui-sans-serif,system-ui,-apple-system,sans-serif;background:#07111f;color:#e8f1ff}
*{box-sizing:border-box}body{margin:0;padding:clamp(18px,4vw,48px);max-width:1100px;margin-inline:auto}
header{border-bottom:1px solid #1b3553;padding-bottom:24px}.eyebrow{color:#75baff;letter-spacing:.14em;text-transform:uppercase;font-size:12px;font-weight:700}
h1{font-size:clamp(28px,5vw,44px);margin:10px 0}.muted{color:#9cb2ca}.panel{background:#0c1b2d;border:1px solid #1d3856;border-radius:16px;padding:20px;margin:18px 0}
.status{font-size:20px;font-weight:750}.notice{border-left:3px solid #55aaff;padding:12px 16px;background:#0c1b2d;margin:20px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}.metric{background:#10243a;padding:14px;border-radius:12px;overflow-wrap:anywhere}.metric small{display:block;color:#9cb2ca;margin-bottom:6px}
table{width:100%;border-collapse:collapse;display:block;overflow-x:auto;white-space:nowrap}th,td{text-align:right;padding:12px;border-bottom:1px solid #1d3856}th:first-child,td:first-child{text-align:left}
code{overflow-wrap:anywhere;color:#a8d5ff}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#07111f;padding:14px;border-radius:10px;color:#c7d8eb}
li{margin:8px 0}.foot{font-size:13px;color:#9cb2ca;margin-top:28px}
</style></head><body>
<header><div class="eyebrow">Bitcoin AI / Evidence desk</div><h1>Research review</h1>
<p class="muted">Static, read-only summary of a completed research comparison.</p></header>
<div class="notice"><div class="eyebrow">Review status</div><div class="status">""" + esc(status_labels[data["status"]]) + """</div>
<p>This is research evidence only. It is not a trading signal, a profitability promise, or permission to execute orders.</p></div>
<section class="panel"><h2>Experiment snapshot</h2><div class="grid">
<div class="metric"><small>Observations</small><strong>""" + str(data["observations"]) + """</strong></div>
<div class="metric"><small>Test window</small><strong>""" + esc(data["test_window"]["start"]) + """ → """ + esc(data["test_window"]["end"]) + """</strong></div>
<div class="metric"><small>Dataset fingerprint</small><code>""" + esc(data["dataset_fingerprint"]) + """</code></div>
<div class="metric"><small>Comparison ID</small><code>""" + esc(data["comparison_id"]) + """</code></div>
</div></section>
<section class="panel"><h2>Candidate definitions</h2><ul>""" + candidates + """</ul></section>
<section class="panel"><h2>After-cost comparison</h2><p class="muted">Returns and drawdowns are percentages. Difference is proposal minus comparator in percentage points. Doubled-cost figure is the proposal stress result.</p>
<table><thead><tr><th>Baseline</th><th>Proposal net</th><th>Baseline net</th><th>Difference</th><th>Proposal 2× cost</th><th>Proposal max DD</th><th>Baseline max DD</th></tr></thead><tbody>""" + "".join(rows) + """</tbody></table></section>
<section class="panel"><h2>Existing statistical evidence</h2><pre>""" + stats + """</pre></section>
<section class="panel"><h2>Limitations &amp; cautions</h2><ul>""" + limits + """</ul></section>
<section class="panel"><h2>Provenance</h2><p>Plan: <code>""" + esc(data["plan_id"]) + """</code></p>
<p>Reproducibility receipt: <code>""" + esc(data["receipt_id"]) + """</code></p>
<p>Research report SHA-256: <code>""" + esc(data["research_report_sha256"]) + """</code></p>
<p>Execution authority: <strong>none</strong></p></section>
<p class="foot">Generated locally from a hash-verified comparison artifact. A matching hash detects accidental changes relative to a retained digest; it is not a digital signature or trusted timestamp.</p>
</body></html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a verified research comparison as static HTML.")
    parser.add_argument("--input", required=True, help="Research comparison JSON")
    parser.add_argument("--output", required=True, help="HTML output path")
    args = parser.parse_args()
    try:
        artifact = json.loads(Path(args.input).read_text(encoding="utf-8"))
        page = render_review_html(artifact)
        Path(args.output).write_text(page, encoding="utf-8")
    except (OSError, json.JSONDecodeError, ReviewArtifactError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
