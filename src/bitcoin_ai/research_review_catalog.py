"""Build and verify a deterministic catalog of saved research-review bundles."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from .research_review_bundle_audit import ReviewBundleAuditError, verify_review_bundle


class ReviewCatalogError(ValueError):
    """Raised when bundle inputs or a portable catalog are invalid."""


def _hash(value: Any) -> str:
    try:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ReviewCatalogError(f"catalog data is not canonical JSON: {exc}") from exc
    return hashlib.sha256(payload).hexdigest()


def verify_review_catalog(catalog: dict) -> dict:
    """Validate catalog schema, unique sorted IDs, entry hash chain, and root digest."""
    required = {"schema_version", "catalog_type", "execution_authority", "entries", "catalog_id"}
    if not isinstance(catalog, dict) or set(catalog) != required:
        raise ReviewCatalogError("catalog fields are incomplete or unexpected")
    if catalog["schema_version"] != 1 or catalog["catalog_type"] != "read_only_research_review_index":
        raise ReviewCatalogError("unsupported catalog type or version")
    if catalog["execution_authority"] != "none" or not isinstance(catalog["entries"], list):
        raise ReviewCatalogError("catalog authority or entries are invalid")
    previous = "0" * 64
    seen: set[str] = set()
    ids: list[str] = []
    for index, entry in enumerate(catalog["entries"]):
        fields = {
            "manifest_id", "comparison_id", "plan_id", "receipt_id",
            "comparison_sha256", "html_sha256", "previous_entry_hash", "entry_hash",
        }
        if not isinstance(entry, dict) or set(entry) != fields:
            raise ReviewCatalogError(f"catalog entry {index} has incomplete or unexpected fields")
        manifest_id = entry["manifest_id"]
        if not isinstance(manifest_id, str) or len(manifest_id) != 64:
            raise ReviewCatalogError(f"catalog entry {index} has an invalid manifest ID")
        if manifest_id in seen:
            raise ReviewCatalogError("duplicate manifest IDs are not allowed")
        seen.add(manifest_id)
        ids.append(manifest_id)
        if entry["previous_entry_hash"] != previous:
            raise ReviewCatalogError(f"catalog entry {index} breaks the hash chain")
        core = {key: value for key, value in entry.items() if key != "entry_hash"}
        expected = _hash(core)
        if entry["entry_hash"] != expected:
            raise ReviewCatalogError(f"catalog entry {index} fingerprint does not match")
        previous = expected
    if ids != sorted(ids):
        raise ReviewCatalogError("catalog entries must be sorted by manifest ID")
    core = {key: value for key, value in catalog.items() if key != "catalog_id"}
    if catalog["catalog_id"] != _hash(core):
        raise ReviewCatalogError("catalog fingerprint does not match")
    return {
        "status": "verified",
        "catalog_id": catalog["catalog_id"],
        "bundle_count": len(catalog["entries"]),
        "execution_authority": "none",
        "read_only": True,
    }


def build_review_catalog(bundle_paths: Iterable[tuple[str | Path, str | Path, str | Path]]) -> dict:
    """Verify each supplied bundle and return a deterministic, export-only index.

    The source bundles are never written, moved, or deleted.
    """
    verified: list[dict] = []
    seen: set[str] = set()
    for comparison, page, manifest in bundle_paths:
        try:
            result = verify_review_bundle(comparison, page, manifest)
        except (ReviewBundleAuditError, OSError) as exc:
            raise ReviewCatalogError(f"bundle verification failed: {exc}") from exc
        if result["manifest_id"] in seen:
            raise ReviewCatalogError("duplicate manifest IDs are not allowed")
        seen.add(result["manifest_id"])
        verified.append(result)

    verified.sort(key=lambda item: item["manifest_id"])
    entries: list[dict] = []
    previous = "0" * 64
    for item in verified:
        core = {
            "manifest_id": item["manifest_id"],
            "comparison_id": item["comparison_id"],
            "plan_id": item["plan_id"],
            "receipt_id": item["receipt_id"],
            "comparison_sha256": item["comparison_sha256"],
            "html_sha256": item["html_sha256"],
            "previous_entry_hash": previous,
        }
        entry_hash = _hash(core)
        entries.append({**core, "entry_hash": entry_hash})
        previous = entry_hash
    catalog_core = {
        "schema_version": 1,
        "catalog_type": "read_only_research_review_index",
        "execution_authority": "none",
        "entries": entries,
    }
    return {**catalog_core, "catalog_id": _hash(catalog_core)}


def write_review_catalog(bundle_paths: Iterable[tuple[str | Path, str | Path, str | Path]],
                         output_path: str | Path) -> dict:
    bundles = tuple(tuple(bundle) for bundle in bundle_paths)
    catalog = build_review_catalog(bundles)
    verify_review_catalog(catalog)
    destination = Path(output_path)
    source_paths = {Path(path).resolve() for bundle in bundles for path in bundle}
    if destination.resolve() in source_paths:
        raise ReviewCatalogError("catalog output must not overwrite a source bundle")
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(catalog, indent=2, sort_keys=True, allow_nan=False) + "\n"
    destination.write_text(payload, encoding="utf-8")
    return verify_review_catalog(catalog)


def main() -> int:
    parser = argparse.ArgumentParser(description="Index verified research-review bundles without modifying them.")
    parser.add_argument(
        "--bundle", nargs=3, action="append", required=True,
        metavar=("COMPARISON", "HTML", "MANIFEST"),
        help="Bundle paths; repeat this option for each bundle",
    )
    parser.add_argument("--output", required=True, help="Portable catalog JSON output")
    args = parser.parse_args()
    try:
        result = write_review_catalog(args.bundle, args.output)
    except (ReviewCatalogError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
