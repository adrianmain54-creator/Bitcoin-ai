import json

import pytest

from bitcoin_ai import research_review_bundle_audit as audit
from bitcoin_ai import research_review_catalog as catalog
from bitcoin_ai import research_review_pipeline as pipeline
from test_research_comparison import fixtures


def _make_bundle(tmp_path, name="one", observations=200):
    controlled, evidence = fixtures(n=observations)
    root = tmp_path / name
    root.mkdir()
    controlled_path, evidence_path = root / "controlled.json", root / "evidence.json"
    comparison, page, manifest = root / "comparison.json", root / "review.html", root / "manifest.json"
    controlled_path.write_text(json.dumps(controlled), encoding="utf-8")
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    pipeline.write_review_bundle(
        controlled_path, evidence_path,
        comparison_output=comparison, html_output=page, manifest_output=manifest,
    )
    return comparison, page, manifest


def test_catalog_is_deterministic_and_verifiable(tmp_path):
    first = _make_bundle(tmp_path, "first")
    second = _make_bundle(tmp_path, "second", observations=201)
    before = [[path.read_bytes() for path in bundle] for bundle in (first, second)]
    left = catalog.build_review_catalog([first, second])
    right = catalog.build_review_catalog([second, first])
    assert left == right
    assert catalog.verify_review_catalog(left)["bundle_count"] == 2
    assert [[path.read_bytes() for path in bundle] for bundle in (first, second)] == before


def test_catalog_rejects_duplicate_manifest_ids(tmp_path):
    bundle = _make_bundle(tmp_path)
    with pytest.raises(catalog.ReviewCatalogError, match="duplicate manifest"):
        catalog.build_review_catalog([bundle, bundle])


def test_catalog_rejects_tampered_bundle_before_indexing(tmp_path):
    bundle = _make_bundle(tmp_path)
    bundle[1].write_text(bundle[1].read_text(encoding="utf-8") + "tampered", encoding="utf-8")
    with pytest.raises(catalog.ReviewCatalogError, match="bundle verification failed"):
        catalog.build_review_catalog([bundle])


def test_catalog_rejects_broken_hash_chain(tmp_path):
    bundle = _make_bundle(tmp_path)
    value = catalog.build_review_catalog([bundle])
    value["entries"][0]["previous_entry_hash"] = "f" * 64
    value["catalog_id"] = catalog._hash({key: item for key, item in value.items() if key != "catalog_id"})
    with pytest.raises(catalog.ReviewCatalogError, match="breaks the hash chain"):
        catalog.verify_review_catalog(value)


def test_catalog_rejects_recomputed_entry_with_bad_root_fingerprint(tmp_path):
    bundle = _make_bundle(tmp_path)
    value = catalog.build_review_catalog([bundle])
    value["catalog_id"] = "0" * 64
    with pytest.raises(catalog.ReviewCatalogError, match="catalog fingerprint"):
        catalog.verify_review_catalog(value)


def test_catalog_output_cannot_overwrite_bundle(tmp_path):
    bundle = _make_bundle(tmp_path)
    with pytest.raises(catalog.ReviewCatalogError, match="must not overwrite"):
        catalog.write_review_catalog([bundle], bundle[2])


def test_catalog_write_emits_verifiable_export(tmp_path):
    bundle = _make_bundle(tmp_path)
    output = tmp_path / "catalog.json"
    result = catalog.write_review_catalog([bundle], output)
    assert json.loads(output.read_text(encoding="utf-8"))["catalog_id"] == result["catalog_id"]
    assert audit.verify_review_bundle(*bundle)["status"] == "verified"
