import hashlib
import json

import pytest

from bitcoin_ai import research_review_pipeline as pipeline
from test_research_comparison import fixtures


def _write(path, value):
    path.write_text(json.dumps(value, allow_nan=False), encoding="utf-8")


def test_pipeline_writes_comparison_html_and_manifest(tmp_path):
    controlled, evidence = fixtures()
    controlled_path, evidence_path = tmp_path / "controlled.json", tmp_path / "evidence.json"
    comparison_path, html_path, manifest_path = (tmp_path / "comparison.json", tmp_path / "review.html", tmp_path / "manifest.json")
    _write(controlled_path, controlled)
    _write(evidence_path, evidence)

    manifest = pipeline.write_review_bundle(
        controlled_path, evidence_path,
        comparison_output=comparison_path, html_output=html_path, manifest_output=manifest_path,
    )

    comparison_bytes, html_bytes = comparison_path.read_bytes(), html_path.read_bytes()
    assert json.loads(comparison_bytes)["execution_authority"] == "none"
    assert b"Research review" in html_bytes
    assert manifest["comparison_sha256"] == hashlib.sha256(comparison_bytes).hexdigest()
    assert manifest["html_sha256"] == hashlib.sha256(html_bytes).hexdigest()
    assert json.loads(manifest_path.read_text())["manifest_id"] == manifest["manifest_id"]


def test_pipeline_rejects_mismatched_evidence_before_outputs(tmp_path):
    controlled, evidence = fixtures()
    evidence["provenance"]["dataset_fingerprint"] = "c" * 64
    controlled_path, evidence_path = tmp_path / "controlled.json", tmp_path / "evidence.json"
    _write(controlled_path, controlled)
    _write(evidence_path, evidence)
    outputs = [tmp_path / "comparison.json", tmp_path / "review.html", tmp_path / "manifest.json"]

    with pytest.raises(pipeline.ReviewPipelineError, match="dataset_fingerprint"):
        pipeline.write_review_bundle(
            controlled_path, evidence_path,
            comparison_output=outputs[0], html_output=outputs[1], manifest_output=outputs[2],
        )
    assert not any(path.exists() for path in outputs)


def test_pipeline_rejects_output_path_aliasing_input(tmp_path):
    controlled, evidence = fixtures()
    controlled_path, evidence_path = tmp_path / "controlled.json", tmp_path / "evidence.json"
    _write(controlled_path, controlled)
    _write(evidence_path, evidence)
    with pytest.raises(pipeline.ReviewPipelineError, match="overwrite input"):
        pipeline.write_review_bundle(
            controlled_path, evidence_path,
            comparison_output=controlled_path, html_output=tmp_path / "review.html",
            manifest_output=tmp_path / "manifest.json",
        )


def test_pipeline_manifest_is_published_last_on_failure(tmp_path, monkeypatch):
    controlled, evidence = fixtures()
    controlled_path, evidence_path = tmp_path / "controlled.json", tmp_path / "evidence.json"
    _write(controlled_path, controlled)
    _write(evidence_path, evidence)
    real_replace = pipeline.os.replace
    calls = 0

    def fail_manifest(source, destination):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("simulated manifest publish failure")
        return real_replace(source, destination)

    monkeypatch.setattr(pipeline.os, "replace", fail_manifest)
    manifest_path = tmp_path / "manifest.json"
    with pytest.raises(pipeline.ReviewPipelineError, match="publish"):
        pipeline.write_review_bundle(
            controlled_path, evidence_path,
            comparison_output=tmp_path / "comparison.json",
            html_output=tmp_path / "review.html", manifest_output=manifest_path,
        )
    assert not manifest_path.exists()
    assert not list(tmp_path.glob("*.tmp"))
    assert not list(tmp_path.glob(".*.tmp"))
