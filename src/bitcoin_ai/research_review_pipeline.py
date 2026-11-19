"""Build a deterministic, read-only comparison + HTML review bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .research_comparison import ComparisonError, compare_completed_research
from .research_review import ReviewArtifactError, render_review_html


class ReviewPipelineError(ValueError):
    """Raised when a complete review bundle cannot be safely produced."""


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ReviewPipelineError(f"artifact is not canonical JSON: {exc}") from exc


def _read_json(path: str | Path) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewPipelineError(f"cannot read JSON input {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReviewPipelineError(f"JSON input must contain an object: {path}")
    return value


def build_review_bundle(controlled_result: dict, evidence_result: dict, *, min_observations: int = 180) -> tuple[dict, str, dict]:
    """Validate supplied completed artifacts and return comparison, HTML, and manifest.

    This post-run stage does not fetch data, rerun evaluation, or mutate ledgers.
    """
    try:
        comparison = compare_completed_research(
            controlled_result, evidence_result, min_observations=min_observations
        )
        page = render_review_html(comparison)
    except (ComparisonError, ReviewArtifactError) as exc:
        raise ReviewPipelineError(str(exc)) from exc
    comparison_bytes = json.dumps(comparison, indent=2, sort_keys=True, allow_nan=False).encode("utf-8") + b"\n"
    html_bytes = page.encode("utf-8")
    receipt = controlled_result["reproducibility_receipt"]
    manifest_core = {
        "schema_version": 1,
        "bundle_type": "read_only_research_review",
        "execution_authority": "none",
        "comparison_id": comparison["comparison_id"],
        "plan_id": comparison["plan_id"],
        "receipt_id": comparison["receipt_id"],
        "comparison_sha256": hashlib.sha256(comparison_bytes).hexdigest(),
        "html_sha256": hashlib.sha256(html_bytes).hexdigest(),
        "research_report_sha256": receipt["research_report_sha256"],
    }
    manifest = {**manifest_core, "manifest_id": hashlib.sha256(_canonical_bytes(manifest_core)).hexdigest()}
    return comparison, page, manifest


def _stage(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False)
    staged = Path(handle.name)
    try:
        with handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        staged.unlink(missing_ok=True)
        raise
    return staged


def write_review_bundle(controlled_path: str | Path, evidence_path: str | Path, *,
                        comparison_output: str | Path, html_output: str | Path,
                        manifest_output: str | Path, min_observations: int = 180) -> dict:
    destinations = [Path(comparison_output), Path(html_output), Path(manifest_output)]
    if len({p.resolve() for p in destinations}) != 3:
        raise ReviewPipelineError("comparison, HTML, and manifest outputs must be distinct paths")
    if Path(controlled_path).resolve() in {p.resolve() for p in destinations} or Path(evidence_path).resolve() in {p.resolve() for p in destinations}:
        raise ReviewPipelineError("output paths must not overwrite input artifacts")
    controlled, evidence = _read_json(controlled_path), _read_json(evidence_path)
    comparison, page, manifest = build_review_bundle(controlled, evidence, min_observations=min_observations)
    payloads = [
        json.dumps(comparison, indent=2, sort_keys=True, allow_nan=False).encode("utf-8") + b"\n",
        page.encode("utf-8"),
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False).encode("utf-8") + b"\n",
    ]
    staged: list[Path] = []
    try:
        staged = [_stage(path, data) for path, data in zip(destinations, payloads)]
        # Publish the manifest last: its presence marks a fully published bundle.
        for temporary, destination in zip(staged[:2], destinations[:2]):
            os.replace(temporary, destination)
        os.replace(staged[2], destinations[2])
    except OSError as exc:
        raise ReviewPipelineError(f"could not publish review bundle: {exc}") from exc
    finally:
        for temporary in staged:
            temporary.unlink(missing_ok=True)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a read-only comparison, HTML review, and integrity manifest.")
    parser.add_argument("--controlled", required=True, help="Completed controlled-result JSON")
    parser.add_argument("--evidence", required=True, help="Read-only fresh-evidence JSON")
    parser.add_argument("--comparison-output", required=True)
    parser.add_argument("--html-output", required=True)
    parser.add_argument("--manifest-output", required=True)
    parser.add_argument("--min-observations", type=int, default=180)
    args = parser.parse_args()
    try:
        manifest = write_review_bundle(
            args.controlled, args.evidence,
            comparison_output=args.comparison_output,
            html_output=args.html_output,
            manifest_output=args.manifest_output,
            min_observations=args.min_observations,
        )
    except (ReviewPipelineError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps({"status": "bundle_written", "manifest_id": manifest["manifest_id"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
