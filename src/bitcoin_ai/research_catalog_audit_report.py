"""Create and verify deterministic audit reports for saved research catalogs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Iterable

from .research_review_catalog import (
    ReviewCatalogError,
    verify_review_catalog,
    verify_review_catalog_bundles,
)


class CatalogAuditReportError(ValueError):
    """Raised when a catalog audit report is invalid or cannot be produced."""


def _digest(value: object) -> str:
    try:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CatalogAuditReportError(f"report data is not canonical JSON: {exc}") from exc
    return hashlib.sha256(payload).hexdigest()


def build_catalog_audit_report(catalog: dict, bundle_paths: Iterable[tuple[str | Path, str | Path, str | Path]]) -> dict:
    """Reverify every original bundle and return a deterministic, read-only audit report."""
    bundles = tuple(tuple(paths) for paths in bundle_paths)
    try:
        verification = verify_review_catalog_bundles(catalog, bundles)
        structural = verify_review_catalog(catalog)
    except ReviewCatalogError as exc:
        raise CatalogAuditReportError(str(exc)) from exc

    entries = [
        {
            "manifest_id": item["manifest_id"],
            "comparison_id": item["comparison_id"],
            "plan_id": item["plan_id"],
            "receipt_id": item["receipt_id"],
            "comparison_sha256": item["comparison_sha256"],
            "html_sha256": item["html_sha256"],
            "status": "verified",
        }
        for item in catalog["entries"]
    ]
    core = {
        "schema_version": 1,
        "report_type": "read_only_research_catalog_audit",
        "status": "verified",
        "catalog_id": structural["catalog_id"],
        "bundle_count": structural["bundle_count"],
        "bundles": entries,
        "original_bundle_bytes_reverified": verification["bundle_bytes_reverified"],
        "execution_authority": "none",
        "read_only": True,
    }
    return {**core, "report_id": _digest(core)}


def verify_catalog_audit_report(report: dict, catalog: dict) -> dict:
    """Verify report schema, catalog binding, entries, and canonical report digest."""
    try:
        structural = verify_review_catalog(catalog)
    except ReviewCatalogError as exc:
        raise CatalogAuditReportError(f"catalog is invalid: {exc}") from exc
    required = {
        "schema_version", "report_type", "status", "catalog_id", "bundle_count",
        "bundles", "original_bundle_bytes_reverified", "execution_authority",
        "read_only", "report_id",
    }
    if not isinstance(report, dict) or set(report) != required:
        raise CatalogAuditReportError("audit report fields are incomplete or unexpected")
    if report["schema_version"] != 1 or report["report_type"] != "read_only_research_catalog_audit":
        raise CatalogAuditReportError("unsupported audit report type or version")
    if report["status"] != "verified" or report["execution_authority"] != "none" or report["read_only"] is not True:
        raise CatalogAuditReportError("audit report status or authority is invalid")
    if report["original_bundle_bytes_reverified"] is not True:
        raise CatalogAuditReportError("report does not attest to original bundle byte reverification")
    expected_bundles = [
        {key: entry[key] for key in (
            "manifest_id", "comparison_id", "plan_id", "receipt_id",
            "comparison_sha256", "html_sha256",
        )} | {"status": "verified"}
        for entry in catalog["entries"]
    ]
    if (
        report["catalog_id"] != structural["catalog_id"]
        or report["bundle_count"] != structural["bundle_count"]
        or report["bundles"] != expected_bundles
    ):
        raise CatalogAuditReportError("audit report does not match the supplied catalog")
    core = {key: value for key, value in report.items() if key != "report_id"}
    if report["report_id"] != _digest(core):
        raise CatalogAuditReportError("audit report fingerprint does not match")
    return {
        "status": "verified",
        "report_id": report["report_id"],
        "catalog_id": report["catalog_id"],
        "bundle_count": report["bundle_count"],
        "execution_authority": "none",
        "read_only": True,
    }


def write_catalog_audit_report(catalog_path: str | Path,
                               bundle_paths: Iterable[tuple[str | Path, str | Path, str | Path]],
                               output_path: str | Path) -> dict:
    """Write a canonical report without overwriting the catalog or any source bundle."""
    catalog_file = Path(catalog_path)
    catalog = json.loads(catalog_file.read_text(encoding="utf-8"))
    bundles = tuple(tuple(paths) for paths in bundle_paths)
    destination = Path(output_path)
    inputs = {catalog_file.resolve(), *(Path(path).resolve() for bundle in bundles for path in bundle)}
    if destination.resolve() in inputs:
        raise CatalogAuditReportError("report output must not overwrite the catalog or a source bundle")
    report = build_catalog_audit_report(catalog, bundles)
    verify_catalog_audit_report(report, catalog)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    temporary = destination.with_name(destination.name + ".tmp")
    try:
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return verify_catalog_audit_report(report, catalog)


def main() -> int:
    parser = argparse.ArgumentParser(description="Reverify a saved research catalog and write a deterministic audit report.")
    parser.add_argument("--catalog", required=True, help="Saved catalog JSON")
    parser.add_argument("--bundle", nargs=3, action="append", required=True,
                        metavar=("COMPARISON", "HTML", "MANIFEST"))
    parser.add_argument("--output", required=True, help="Audit report JSON output")
    args = parser.parse_args()
    try:
        result = write_catalog_audit_report(args.catalog, args.bundle, args.output)
    except (CatalogAuditReportError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
