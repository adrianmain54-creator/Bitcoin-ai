from bitcoin_ai import research_cycle


def test_research_cycle_runs_prepare_experiment_and_review_in_order(monkeypatch, tmp_path):
    calls = []
    prepared = {"plan_id": "plan-abc", "status": "plan_prepared"}
    experiment = {"status": "completed_research_only", "execution_authority": "none"}
    review = {"status": "rejected_or_insufficient", "gates": {"sample": False}}

    def prepare(task, dataset, **kwargs):
        calls.append(("prepare", task, dataset, kwargs))
        return prepared

    def run(plan, **kwargs):
        calls.append(("run", plan, kwargs))
        return experiment

    def evaluate(result, **kwargs):
        calls.append(("evaluate", result, kwargs))
        return review

    monkeypatch.setattr(research_cycle, "prepare_scheduled_experiment", prepare)
    monkeypatch.setattr(research_cycle, "run_preregistered_experiment", run)
    monkeypatch.setattr(research_cycle, "evaluate_controlled_experiment", evaluate)

    task, dataset = {"task_id": "t"}, {"dataset_fingerprint": "f"}
    result = research_cycle.run_scheduled_research_cycle(
        task, dataset, train_bars=100, test_bars=20, code_revision="rev",
        source_strategy_definition={"family": "sma", "lookback": 12},
        candidate_registry_path=tmp_path / "registry.json",
        holdout_ledger_path=tmp_path / "holdouts.json",
        registered_at="2026-11-19T00:00:00+00:00",
    )

    assert [item[0] for item in calls] == ["prepare", "run", "evaluate"]
    assert calls[1][1] is prepared
    assert calls[2][1] is experiment
    assert result["status"] == "rejected_or_insufficient"
    assert result["execution_authority"] == "none"
    assert result["evidence_review"] is review


def test_rejected_holdout_stops_before_evidence_review(monkeypatch, tmp_path):
    calls = []
    prepared = {"plan_id": "plan-rejected"}
    rejected = {"status": "rejected_holdout_reuse", "execution_authority": "none"}

    monkeypatch.setattr(
        research_cycle, "prepare_scheduled_experiment",
        lambda *args, **kwargs: prepared,
    )

    def run(*args, **kwargs):
        calls.append("run")
        return rejected

    def evaluate(*args, **kwargs):
        calls.append("evaluate")
        raise AssertionError("evidence review must not run for a rejected holdout")

    monkeypatch.setattr(research_cycle, "run_preregistered_experiment", run)
    monkeypatch.setattr(research_cycle, "evaluate_controlled_experiment", evaluate)

    result = research_cycle.run_scheduled_research_cycle(
        {}, {}, train_bars=100, test_bars=20, code_revision="rev",
        source_strategy_definition={"family": "sma", "lookback": 12},
        candidate_registry_path=tmp_path / "registry.json",
        holdout_ledger_path=tmp_path / "holdouts.json",
        registered_at="2026-11-19T00:00:00+00:00",
    )

    assert calls == ["run"]
    assert result["status"] == "rejected_holdout_reuse"
    assert result["evidence_review"] is None
    assert result["execution_authority"] == "none"
