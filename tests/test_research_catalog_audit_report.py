import json

import pytest

from bitcoin_ai import research_catalog_audit_report as report
from bitcoin_ai import research_review_catalog as catalog
from bitcoin_ai import research_review_pipeline as pipeline
from test_research_comparison import fixtures


def _bundle(tmp_path, name="one", observations=200):
    controlled, evidence = fixtures(n=observations)
    root = tmp_path / name
    root.mkdir()
    c, e = root / "controlled.json", root / "evidence.json"
    comparison, page, manifest = root / "comparison.json", root / "review.html", root / "manifest.json"
    c.write_text(json.dumps(controlled), encoding="utf-8")
    e.write_text(json.dumps(evidence), encoding="utf-8")
    pipeline.write_review_bundle(c, e, comparison_output=comparison, html_output=page, manifest_output=manifest)
    return comparison, page, manifest


def test_audit_report_is_deterministic_and_bound_to_catalog(tmp_path):
    first = _bundle(tmp_path, "first")
    second = _bundle(tmp_path, "second", 201)
    saved = catalog.build_review_catalog([first, second])
    a = report.build_catalog_audit_report(saved, [first, second])
    b = report.build_catalog_audit_report(saved, [second, first])
    assert a == b
    assert report.verify_catalog_audit_report(a, saved)["bundle_count"] == 2
    assert a["original_bundle_bytes_reverified"] is True


def test_audit_report_rejects_incomplete_or_extra_bundle_set(tmp_path):
    first = _bundle(tmp_path, "first")
    second = _bundle(tmp_path, "second", 201)
    saved = catalog.build_review_catalog([first])
    with pytest.raises(report.CatalogAuditReportError, match="exactly match"):
        report.build_catalog_audit_report(saved, [])
    with pytest.raises(report.CatalogAuditReportError, match="exactly match"):
        report.build_catalog_audit_report(saved, [first, second])


def test_audit_report_detects_tampering(tmp_path):
    bundle = _bundle(tmp_path)
    saved = catalog.build_review_catalog([bundle])
    value = report.build_catalog_audit_report(saved, [bundle])
    value["bundles"][0]["plan_id"] = "tampered"
    with pytest.raises(report.CatalogAuditReportError, match="does not match"):
        report.verify_catalog_audit_report(value, saved)


def test_audit_report_detects_digest_change(tmp_path):
    bundle = _bundle(tmp_path)
    saved = catalog.build_review_catalog([bundle])
    value = report.build_catalog_audit_report(saved, [bundle])
    value["status"] = "changed"
    with pytest.raises(report.CatalogAuditReportError, match="fingerprint"):
        report.verify_catalog_audit_report(value, saved)


def test_audit_report_rejects_output_aliasing_catalog_or_bundle(tmp_path):
    bundle = _bundle(tmp_path)
    saved = catalog.build_review_catalog([bundle])
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(saved), encoding="utf-8")
    with pytest.raises(report.CatalogAuditReportError, match="must not overwrite"):
        report.write_catalog_audit_report(catalog_path, [bundle], catalog_path)
    with pytest.raises(report.CatalogAuditReportError, match="must not overwrite"):
        report.write_catalog_audit_report(catalog_path, [bundle], bundle[0])


def test_audit_report_writer_is_deterministic_and_preserves_inputs(tmp_path):
    bundle = _bundle(tmp_path)
    saved = catalog.build_review_catalog([bundle])
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(saved), encoding="utf-8")
    before = [catalog_path.read_bytes(), *(path.read_bytes() for path in bundle)]
    one, two = tmp_path / "one-report.json", tmp_path / "two-report.json"
    a = report.write_catalog_audit_report(catalog_path, [bundle], one)
    b = report.write_catalog_audit_report(catalog_path, [bundle], two)
    assert a == b
    assert one.read_bytes() == two.read_bytes()
    assert [catalog_path.read_bytes(), *(path.read_bytes() for path in bundle)] == before
