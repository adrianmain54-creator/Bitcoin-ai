"""Verify a saved research-review bundle without changing any files."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .research_review import ReviewArtifactError, render_review_html, verify_comparison_artifact


class ReviewBundleAuditError(ValueError):
    """Raised when a review bundle is incomplete, altered, or mismatched."""


def _canonical_hash(value: Any) -> str:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ReviewBundleAuditError(f"manifest is not canonical JSON: {exc}") from exc
    return hashlib.sha256(raw).hexdigest()


def _read_json(path: str | Path, label: str) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewBundleAuditError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReviewBundleAuditError(f"{label} must be a JSON object")
    return value


def verify_review_bundle(comparison_path: str | Path, html_path: str | Path,
                         manifest_path: str | Path) -> dict:
    """Verify manifest identity, artifact hashes, comparison provenance, and HTML content.

    Read-only: no files are created, rewritten, or deleted.
    """
    paths = [Path(comparison_path), Path(html_path), Path(manifest_path)]
    if len({path.resolve() for path in paths}) != 3:
        raise ReviewBundleAuditError("comparison, HTML, and manifest paths must be distinct")
    comparison = _read_json(paths[0], "comparison artifact")
    manifest = _read_json(paths[2], "bundle manifest")
    try:
        verify_comparison_artifact(comparison)
    except ReviewArtifactError as exc:
        raise ReviewBundleAuditError(f"comparison artifact is invalid: {exc}") from exc

    required = {
        "schema_version", "bundle_type", "execution_authority", "comparison_id",
        "plan_id", "receipt_id", "comparison_sha256", "html_sha256",
        "research_report_sha256", "manifest_id",
    }
    if set(manifest) != required:
        raise ReviewBundleAuditError("manifest fields are incomplete or unexpected")
    core = {key: value for key, value in manifest.items() if key != "manifest_id"}
    if manifest["manifest_id"] != _canonical_hash(core):
        raise ReviewBundleAuditError("manifest fingerprint does not match its contents")
    if manifest["schema_version"] != 1 or manifest["bundle_type"] != "read_only_research_review":
        raise ReviewBundleAuditError("unsupported bundle manifest type or version")
    if manifest["execution_authority"] != "none":
        raise ReviewBundleAuditError("bundle manifest grants unexpected execution authority")

    try:
        comparison_bytes = paths[0].read_bytes()
        html_bytes = paths[1].read_bytes()
    except OSError as exc:
        raise ReviewBundleAuditError(f"cannot read bundle output: {exc}") from exc
    if hashlib.sha256(comparison_bytes).hexdigest() != manifest["comparison_sha256"]:
        raise ReviewBundleAuditError("comparison output SHA-256 does not match manifest")
    if hashlib.sha256(html_bytes).hexdigest() != manifest["html_sha256"]:
        raise ReviewBundleAuditError("HTML output SHA-256 does not match manifest")
    if comparison["comparison_id"] != manifest["comparison_id"]:
        raise ReviewBundleAuditError("comparison ID differs from manifest")
    if comparison["plan_id"] != manifest["plan_id"]:
        raise ReviewBundleAuditError("plan ID differs from manifest")
    if comparison["receipt_id"] != manifest["receipt_id"]:
        raise ReviewBundleAuditError("receipt ID differs from manifest")
    if comparison["research_report_sha256"] != manifest["research_report_sha256"]:
        raise ReviewBundleAuditError("research report digest differs from manifest")
    try:
        expected_html = render_review_html(comparison).encode("utf-8")
    except ReviewArtifactError as exc:
        raise ReviewBundleAuditError(f"comparison cannot reproduce the review page: {exc}") from exc
    if html_bytes != expected_html:
        raise ReviewBundleAuditError("HTML content does not match the verified comparison artifact")

    return {
        "status": "verified",
        "manifest_id": manifest["manifest_id"],
        "comparison_id": comparison["comparison_id"],
        "plan_id": comparison["plan_id"],
        "receipt_id": comparison["receipt_id"],
        "comparison_sha256": manifest["comparison_sha256"],
        "html_sha256": manifest["html_sha256"],
        "execution_authority": "none",
        "read_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a saved read-only research review bundle.")
    parser.add_argument("--comparison", required=True, help="Comparison JSON output")
    parser.add_argument("--html", required=True, help="Static HTML review output")
    parser.add_argument("--manifest", required=True, help="Bundle manifest output")
    args = parser.parse_args()
    try:
        result = verify_review_bundle(args.comparison, args.html, args.manifest)
    except (ReviewBundleAuditError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
