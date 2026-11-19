import json

import pytest

from bitcoin_ai import research_review_bundle_audit as audit
from bitcoin_ai import research_review_pipeline as pipeline
from test_research_comparison import fixtures


def _make_bundle(tmp_path):
    controlled, evidence = fixtures()
    controlled_path, evidence_path = tmp_path / "controlled.json", tmp_path / "evidence.json"
    comparison_path, html_path, manifest_path = (
        tmp_path / "comparison.json", tmp_path / "review.html", tmp_path / "manifest.json"
    )
    controlled_path.write_text(json.dumps(controlled), encoding="utf-8")
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    pipeline.write_review_bundle(
        controlled_path, evidence_path,
        comparison_output=comparison_path, html_output=html_path, manifest_output=manifest_path,
    )
    return comparison_path, html_path, manifest_path


def test_verifier_accepts_intact_bundle_and_reports_provenance(tmp_path):
    paths = _make_bundle(tmp_path)
    result = audit.verify_review_bundle(*paths)
    assert result["status"] == "verified"
    assert result["execution_authority"] == "none"
    assert result["read_only"] is True


def test_verifier_rejects_changed_html(tmp_path):
    comparison, page, manifest = _make_bundle(tmp_path)
    page.write_text(page.read_text(encoding="utf-8") + "<!-- changed -->", encoding="utf-8")
    with pytest.raises(audit.ReviewBundleAuditError, match="HTML output SHA-256"):
        audit.verify_review_bundle(comparison, page, manifest)


def test_verifier_rejects_tampered_manifest(tmp_path):
    comparison, page, manifest = _make_bundle(tmp_path)
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["plan_id"] = "0" * 64
    manifest.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(audit.ReviewBundleAuditError, match="manifest fingerprint"):
        audit.verify_review_bundle(comparison, page, manifest)


def test_verifier_rejects_comparison_html_mismatch_even_if_hashes_recomputed(tmp_path):
    comparison, page, manifest = _make_bundle(tmp_path)
    page.write_text("<html>different page</html>", encoding="utf-8")
    value = json.loads(manifest.read_text(encoding="utf-8"))
    import hashlib
    value["html_sha256"] = hashlib.sha256(page.read_bytes()).hexdigest()
    core = {key: item for key, item in value.items() if key != "manifest_id"}
    value["manifest_id"] = audit._canonical_hash(core)
    manifest.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(audit.ReviewBundleAuditError, match="HTML content does not match"):
        audit.verify_review_bundle(comparison, page, manifest)


def test_verifier_does_not_modify_bundle_files(tmp_path):
    paths = _make_bundle(tmp_path)
    before = [path.read_bytes() for path in paths]
    audit.verify_review_bundle(*paths)
    assert [path.read_bytes() for path in paths] == before


def test_verifier_rejects_path_aliasing(tmp_path):
    paths = _make_bundle(tmp_path)
    with pytest.raises(audit.ReviewBundleAuditError, match="must be distinct"):
        audit.verify_review_bundle(paths[0], paths[1], paths[0])
