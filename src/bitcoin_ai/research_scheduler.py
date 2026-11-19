"""Deterministic, append-only scheduler for research-only experiments.

The scheduler reacts to validated market-context reports and untested proposal
hypotheses. It queues work only; it never fetches data, runs experiments,
registers trials, promotes strategies, or places orders. Single-writer storage.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile


GENESIS_HASH = "0" * 64


class ResearchSchedulerError(ValueError):
    """Invalid market context, proposal, or scheduler queue."""


def _canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _event_digest(event: dict) -> str:
    return hashlib.sha256(_canonical(event)).hexdigest()


def _timestamp(value: str) -> datetime:
    if not isinstance(value, str):
        raise ResearchSchedulerError("observed_at must be a timezone-aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ResearchSchedulerError("observed_at is not a valid ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ResearchSchedulerError("observed_at must be timezone-aware and include an offset")
    return parsed


def _read_queue(path: Path) -> dict:
    if not path.exists():
        return {"schema_version": 1, "events": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchSchedulerError(f"cannot read scheduler queue: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1 or not isinstance(payload.get("events"), list):
        raise ResearchSchedulerError("scheduler queue has an invalid schema")
    previous = GENESIS_HASH
    seen = set()
    for item in payload["events"]:
        if not isinstance(item, dict) or set(item) != {"event", "previous_hash", "event_hash"}:
            raise ResearchSchedulerError("scheduler queue event envelope is malformed")
        event = item["event"]
        if not isinstance(event, dict) or item["previous_hash"] != previous:
            raise ResearchSchedulerError("scheduler queue hash chain is broken")
        digest = _event_digest(event)
        if item["event_hash"] != digest:
            raise ResearchSchedulerError("scheduler queue event hash is invalid")
        task_id = event.get("task_id")
        if not isinstance(task_id, str) or not task_id or task_id in seen:
            raise ResearchSchedulerError("scheduler queue contains a duplicate or invalid task ID")
        if event.get("event_type") != "task_queued":
            raise ResearchSchedulerError("scheduler queue contains an unsupported event")
        seen.add(task_id)
        previous = digest
    return payload


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def scan_and_queue_research(
    queue_path: str | Path,
    *,
    observed_at: str,
    market_context: dict,
    proposal_report: dict,
    source_candidate: str,
) -> dict:
    """Queue idempotent candidate/regime research tasks from validated reports.

    Market context must be the output of market_regime_intelligence and must
    have clean multi-source and anomaly checks. Proposal report must be an
    untested strategy-improvement hypothesis report.
    """
    timestamp = _timestamp(observed_at)
    if not isinstance(source_candidate, str) or not source_candidate.strip():
        raise ResearchSchedulerError("source_candidate is required")
    try:
        source_family, source_lookback_text = source_candidate.rsplit(":", 1)
        source_lookback = int(source_lookback_text)
    except (ValueError, TypeError) as exc:
        raise ResearchSchedulerError("source_candidate must use family:lookback format") from exc
    if not source_family.strip() or source_lookback < 1:
        raise ResearchSchedulerError("source_candidate must use family:positive-lookback format")
    source_definition = {"family": source_family, "lookback": source_lookback}
    if not isinstance(market_context, dict):
        raise ResearchSchedulerError("market_context must be a mapping")
    if market_context.get("status") != "classified" or market_context.get("posture") != "research_only":
        return {
            "status": "abstained",
            "reason": "market context is not cleanly classified for research",
            "queued": [],
            "queue_mutated": False,
        }
    regime = market_context.get("regime")
    sources = market_context.get("exchange_sources")
    aligned = market_context.get("aligned_candles")
    if not isinstance(regime, str) or not regime.strip():
        raise ResearchSchedulerError("market context regime is missing")
    if (not isinstance(sources, list)
            or any(not isinstance(source, str) or not source for source in sources)):
        raise ResearchSchedulerError("exchange_sources must be a list of non-empty source names")
    if len(set(sources)) < 3:
        return {
            "status": "abstained",
            "reason": "fewer than three unique verified exchange sources",
            "queued": [],
            "queue_mutated": False,
        }
    if isinstance(aligned, bool) or not isinstance(aligned, int) or aligned < 20:
        raise ResearchSchedulerError("scheduler requires at least 20 aligned market candles")
    alert_count = market_context.get("anomaly_alert_count")
    if (isinstance(alert_count, bool) or alert_count != 0
            or market_context.get("risk_flags") != []):
        return {
            "status": "abstained",
            "reason": "market anomaly or risk flags require review",
            "queued": [],
            "queue_mutated": False,
        }
    if not isinstance(proposal_report, dict) or proposal_report.get("status") != "hypotheses_only":
        raise ResearchSchedulerError("proposal_report must contain untested hypotheses only")
    proposals = proposal_report.get("proposals")
    if not isinstance(proposals, list):
        raise ResearchSchedulerError("proposal_report proposals must be a list")

    path = Path(queue_path)
    queue = _read_queue(path)
    known = {item["event"]["task_id"] for item in queue["events"]}
    added = []
    skipped_comparator_count = 0
    for proposal in proposals:
        if not isinstance(proposal, dict) or not isinstance(proposal.get("candidate"), dict):
            raise ResearchSchedulerError("each proposal must contain a candidate definition")
        candidate = proposal["candidate"]
        family, lookback = candidate.get("family"), candidate.get("lookback")
        if not isinstance(family, str) or not family.strip():
            raise ResearchSchedulerError("candidate family is invalid")
        if isinstance(lookback, bool) or not isinstance(lookback, int) or lookback < 1:
            raise ResearchSchedulerError("candidate lookback must be a positive integer")
        hypothesis = proposal.get("hypothesis")
        trigger = proposal.get("trigger")
        if not isinstance(hypothesis, str) or not hypothesis.strip() or not isinstance(trigger, str) or not trigger.strip():
            raise ResearchSchedulerError("proposal hypothesis and trigger are required")
        definition = {"family": family, "lookback": lookback}
        # The unchanged source and cash baseline are already mandatory
        # comparators in every experiment; queueing either as the proposal
        # would create duplicate strategy roles rather than a useful trial.
        if definition == source_definition or definition == {"family": "cash", "lookback": 2}:
            skipped_comparator_count += 1
            continue
        identity = {
            "observed_at": timestamp.isoformat(),
            "source_candidate": source_candidate,
            "market_regime": regime,
            "candidate": definition,
            "trigger": trigger,
        }
        task_id = hashlib.sha256(_canonical(identity)).hexdigest()
        if task_id in known:
            continue
        event = {
            "event_type": "task_queued",
            "task_id": task_id,
            **identity,
            "hypothesis": hypothesis,
            "status": "queued",
            "requirements": [
                "Register a new immutable candidate trial before evaluation.",
                "Use a genuinely unused dataset fingerprint and holdout interval.",
                "Compare proposal, unchanged source, and cash on identical out-of-sample observations.",
                "Require uncertainty, doubled-cost, regime, and failure-analysis checks.",
                "Underpowered or incomplete evidence remains ineligible.",
            ],
            "execution_authority": "none",
        }
        previous = queue["events"][-1]["event_hash"] if queue["events"] else GENESIS_HASH
        digest = _event_digest(event)
        queue["events"].append({
            "event": event,
            "previous_hash": previous,
            "event_hash": digest,
        })
        known.add(task_id)
        added.append(event)

    if added:
        _atomic_write(path, queue)
    return {
        "status": "queued" if added else "no_new_tasks",
        "queued": added,
        "queued_count": len(added),
        "skipped_comparator_count": skipped_comparator_count,
        "queue_size": len(queue["events"]),
        "queue_mutated": bool(added),
        "storage": "append_only_hash_chained_single_writer",
        "limitations": [
            "The scheduler consumes supplied reports; it does not fetch market data or run experiments.",
            "A queued task is not a preregistered trial and does not reserve a holdout interval.",
            "Hash chaining detects later edits but does not prevent concurrent writers or prove external timestamp accuracy.",
            "No paper or live trading authority is granted.",
        ],
    }


def load_research_queue(queue_path: str | Path) -> dict:
    """Return a validated read-only view of queued research tasks."""
    queue = _read_queue(Path(queue_path))
    return {
        "status": "valid" if queue["events"] else "empty",
        "task_count": len(queue["events"]),
        "tasks": [item["event"] for item in queue["events"]],
        "integrity": "valid_hash_chain",
    }
