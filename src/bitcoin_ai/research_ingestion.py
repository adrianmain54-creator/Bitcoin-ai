"""Fail-closed, provenance-preserving historical OHLCV ingestion for research.

Inputs are normalized completed-candle payloads supplied by an explicit caller.
This module performs no network access and never sorts, fills, resamples, or repairs.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import re


class ResearchIngestionError(ValueError):
    """Historical research data failed schema, quality, or provenance checks."""


_INTERVAL = re.compile(r"^(\d+)(m|h|d)$")


def _timestamp(value, field: str) -> datetime:
    if not isinstance(value, str):
        raise ResearchIngestionError(f"{field} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ResearchIngestionError(f"{field} is not a valid ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ResearchIngestionError(f"{field} must include a timezone offset")
    return parsed.astimezone(timezone.utc)


def _interval_seconds(value: str) -> int:
    if not isinstance(value, str):
        raise ResearchIngestionError("interval must be a supported duration")
    match = _INTERVAL.fullmatch(value)
    if not match:
        raise ResearchIngestionError("interval must use a positive m, h, or d duration")
    amount = int(match.group(1))
    if amount < 1:
        raise ResearchIngestionError("interval duration must be positive")
    return amount * {"m": 60, "h": 3600, "d": 86400}[match.group(2)]


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def compute_research_dataset_fingerprint(dataset: dict) -> str:
    """Recompute the canonical prepared-dataset digest from its actual content."""
    if not isinstance(dataset, dict):
        raise ResearchIngestionError("dataset must be a mapping")
    cross_source = dataset.get("cross_source")
    if not isinstance(cross_source, dict):
        raise ResearchIngestionError("dataset cross-source metadata is missing")
    sources = cross_source.get("sources")
    bars = dataset.get("canonical_bars")
    if not isinstance(sources, list) or not isinstance(bars, list):
        raise ResearchIngestionError("dataset source names or canonical bars are missing")
    material = {
        "schema_version": dataset.get("schema_version"),
        "symbol": dataset.get("symbol"),
        "interval": dataset.get("interval"),
        "start": dataset.get("start"),
        "end": dataset.get("end"),
        "row_count": dataset.get("row_count"),
        "sources": sources,
        "canonical_bars": bars,
    }
    try:
        return hashlib.sha256(_canonical(material)).hexdigest()
    except (TypeError, ValueError) as exc:
        raise ResearchIngestionError("dataset content cannot be fingerprinted safely") from exc


def _number(value, field: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ResearchIngestionError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0) or (not positive and result < 0):
        raise ResearchIngestionError(f"{field} must be finite and {'positive' if positive else 'non-negative'}")
    return result


def _normalize_source(payload: dict, *, symbol: str, interval: str,
                      interval_seconds: int, ingested_at: datetime,
                      max_age_seconds: int) -> dict:
    if not isinstance(payload, dict):
        raise ResearchIngestionError("each source payload must be a mapping")
    source = payload.get("source")
    if not isinstance(source, str) or not source.strip():
        raise ResearchIngestionError("source name is required")
    if payload.get("symbol") != symbol or payload.get("interval") != interval:
        raise ResearchIngestionError(f"{source}: symbol or interval provenance mismatch")
    retrieved = _timestamp(payload.get("retrieved_at"), f"{source}.retrieved_at")
    age = (ingested_at - retrieved).total_seconds()
    if age < 0:
        raise ResearchIngestionError(f"{source}: retrieval timestamp is in the future")
    if age > max_age_seconds:
        raise ResearchIngestionError(f"{source}: source payload is stale")
    rows = payload.get("bars")
    if not isinstance(rows, list) or len(rows) < 3:
        raise ResearchIngestionError(f"{source}: at least 3 completed candles are required")

    normalized = []
    previous = None
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ResearchIngestionError(f"{source}: candle {index} must be a mapping")
        stamp = _timestamp(row.get("timestamp"), f"{source}.bars[{index}].timestamp")
        if stamp > ingested_at:
            raise ResearchIngestionError(f"{source}: candle timestamp is in the future")
        if previous is not None:
            delta = (stamp - previous).total_seconds()
            if delta <= 0:
                raise ResearchIngestionError(f"{source}: duplicate or out-of-order candle timestamp")
            if delta != interval_seconds:
                raise ResearchIngestionError(f"{source}: missing or irregular candle interval")
        previous = stamp
        op = _number(row.get("open"), f"{source}.open", positive=True)
        high = _number(row.get("high"), f"{source}.high", positive=True)
        low = _number(row.get("low"), f"{source}.low", positive=True)
        close = _number(row.get("close"), f"{source}.close", positive=True)
        volume = _number(row.get("volume"), f"{source}.volume")
        if high < max(op, close, low) or low > min(op, close, high):
            raise ResearchIngestionError(f"{source}: invalid OHLC relationship at candle {index}")
        normalized.append({
            "timestamp": stamp.isoformat(), "open": op, "high": high,
            "low": low, "close": close, "volume": volume,
        })
    return {
        "source": source,
        "symbol": symbol,
        "interval": interval,
        "retrieved_at": retrieved.isoformat(),
        "bars": normalized,
    }


def prepare_research_dataset(
    source_payloads: list[dict],
    *,
    symbol: str,
    interval: str,
    ingested_at: str,
    max_age_seconds: int = 900,
    min_sources: int = 3,
    max_price_deviation: float = 0.01,
) -> dict:
    """Validate multi-source completed candles and return a deterministic bundle.

    The fingerprint excludes ingestion time but includes source provenance and
    every normalized candle. This output is not a holdout-freshness attestation.
    """
    if not isinstance(symbol, str) or not symbol.strip():
        raise ResearchIngestionError("symbol is required")
    seconds = _interval_seconds(interval)
    if isinstance(max_age_seconds, bool) or not isinstance(max_age_seconds, int) or max_age_seconds < 0:
        raise ResearchIngestionError("max_age_seconds must be a non-negative integer")
    if isinstance(min_sources, bool) or not isinstance(min_sources, int) or min_sources < 2:
        raise ResearchIngestionError("min_sources must be an integer >= 2")
    if (isinstance(max_price_deviation, bool)
            or not isinstance(max_price_deviation, (int, float))
            or not math.isfinite(max_price_deviation)
            or not 0 < max_price_deviation < 1):
        raise ResearchIngestionError("max_price_deviation must be between 0 and 1")
    observed = _timestamp(ingested_at, "ingested_at")
    if not isinstance(source_payloads, list) or len(source_payloads) < min_sources:
        raise ResearchIngestionError(f"at least {min_sources} source payloads are required")

    sources = [
        _normalize_source(item, symbol=symbol, interval=interval,
                          interval_seconds=seconds, ingested_at=observed,
                          max_age_seconds=max_age_seconds)
        for item in source_payloads
    ]
    source_names = [item["source"] for item in sources]
    if len(set(source_names)) != len(source_names):
        raise ResearchIngestionError("source names must be unique")
    sources.sort(key=lambda item: item["source"])
    names = [item["source"] for item in sources]

    reference = sources[0]["bars"]
    reference_times = [bar["timestamp"] for bar in reference]
    max_deviation = 0.0
    for source in sources[1:]:
        bars = source["bars"]
        if [bar["timestamp"] for bar in bars] != reference_times:
            raise ResearchIngestionError(f"{source['source']}: candle timestamps do not align exactly")
        for index, (left, right) in enumerate(zip(reference, bars)):
            deviation = abs(left["close"] - right["close"]) / left["close"]
            max_deviation = max(max_deviation, deviation)
            if deviation > max_price_deviation:
                raise ResearchIngestionError(
                    f"{source['source']}: close-price divergence exceeds tolerance at candle {index}"
                )

    core = {
        "schema_version": 1,
        "symbol": symbol,
        "interval": interval,
        "start": reference_times[0],
        "end": reference_times[-1],
        "row_count": len(reference),
        "sources": sources,
        "canonical_bars": reference,
        "cross_source": {
            "status": "cross_checked",
            "source_count": len(sources),
            "sources": names,
            "aligned_candles": len(reference),
            # A successful cross-check has no threshold breaches; malformed or
            # divergent source histories are rejected before this report exists.
            "divergent_candles": 0,
            "maximum_close_deviation": max_deviation,
            "tolerance": float(max_price_deviation),
        },
    }
    # Fingerprint dataset identity, not ingestion timing metadata.
    # Source names are sorted above, so caller ordering cannot affect the hash.
    fingerprint = compute_research_dataset_fingerprint(core)
    return {
        "status": "prepared",
        "dataset_fingerprint": fingerprint,
        "dataset": core,
        "provenance": {
            "ingested_at": observed.isoformat(),
            "source_count": len(sources),
            "sources": names,
            "symbol": symbol,
            "interval": interval,
            "start": core["start"],
            "end": core["end"],
            "row_count": len(reference),
            "quality_status": "pass",
            "dataset_fingerprint": fingerprint,
        },
        "holdout_status": "not_assessed",
        "limitations": [
            "Inputs are caller-supplied normalized payloads; this function performs no network retrieval.",
            "No sorting, dropping, interpolation, filling, resampling, or silent repair is performed.",
            "A deterministic fingerprint does not establish that a dataset or holdout is fresh or unused.",
            "Candidate preregistration and holdout-ledger checks remain mandatory before evaluation.",
            "Cross-source agreement is not proof against shared upstream errors or manipulation.",
        ],
    }
