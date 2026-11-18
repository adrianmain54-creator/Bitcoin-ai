from datetime import datetime, timedelta, timezone

import pytest

from bitcoin_ai.research_ingestion import (
    ResearchIngestionError,
    prepare_research_dataset,
)


INGESTED = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)


def payload(source, *, closes=None, timestamps=None, retrieved_at=None, symbol="BTC-USDT", interval="5m"):
    closes = closes or [100.0, 101.0, 102.0]
    timestamps = timestamps or [INGESTED - timedelta(minutes=15 - 5 * i) for i in range(3)]
    return {
        "source": source,
        "symbol": symbol,
        "interval": interval,
        "retrieved_at": retrieved_at or (INGESTED - timedelta(seconds=5)).isoformat(),
        "bars": [
            {
                "timestamp": stamp.isoformat(),
                "open": close - 0.2,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "volume": 10 + i,
            }
            for i, (stamp, close) in enumerate(zip(timestamps, closes))
        ],
    }


def ingest(sources=None, **kwargs):
    return prepare_research_dataset(
        sources or [payload("binance"), payload("coinbase"), payload("kraken")],
        symbol="BTC-USDT",
        interval="5m",
        ingested_at=INGESTED.isoformat(),
        **kwargs,
    )


def test_three_source_clean_history_prepares_provenance_bundle():
    report = ingest()
    assert report["status"] == "prepared"
    assert report["provenance"]["quality_status"] == "pass"
    assert report["provenance"]["row_count"] == 3
    assert report["dataset"]["cross_source"]["source_count"] == 3
    assert report["holdout_status"] == "not_assessed"
    assert len(report["dataset_fingerprint"]) == 64


def test_fingerprint_is_deterministic_and_source_order_independent():
    forward = ingest()
    reverse = ingest([payload("kraken"), payload("binance"), payload("coinbase")])
    assert forward["dataset_fingerprint"] == reverse["dataset_fingerprint"]


def test_duplicate_or_out_of_order_timestamps_fail_without_repair():
    rows = [INGESTED - timedelta(minutes=15), INGESTED - timedelta(minutes=10),
            INGESTED - timedelta(minutes=10)]
    bad = [payload(name, timestamps=rows) for name in ("binance", "kraken", "coinbase")]
    with pytest.raises(ResearchIngestionError, match="duplicate or out-of-order"):
        ingest(bad)
    assert [row["timestamp"] for row in bad[0]["bars"]] == [x.isoformat() for x in rows]


def test_missing_interval_fails_without_resampling():
    rows = [INGESTED - timedelta(minutes=15), INGESTED - timedelta(minutes=5),
            INGESTED]
    with pytest.raises(ResearchIngestionError, match="missing or irregular"):
        ingest([payload(name, timestamps=rows) for name in ("binance", "kraken", "coinbase")])


@pytest.mark.parametrize("field,value", [
    ("open", float("nan")), ("high", 99.0), ("low", 103.0),
    ("close", float("inf")), ("volume", -1.0),
])
def test_invalid_ohlcv_fails_closed(field, value):
    sources = [payload(name) for name in ("binance", "kraken", "coinbase")]
    sources[0]["bars"][1][field] = value
    with pytest.raises(ResearchIngestionError):
        ingest(sources)


def test_stale_and_future_retrieval_times_are_rejected():
    stale = [payload(name, retrieved_at=(INGESTED - timedelta(hours=1)).isoformat())
             for name in ("binance", "kraken", "coinbase")]
    with pytest.raises(ResearchIngestionError, match="stale"):
        ingest(stale)
    future = [payload(name, retrieved_at=(INGESTED + timedelta(seconds=1)).isoformat())
              for name in ("binance", "kraken", "coinbase")]
    with pytest.raises(ResearchIngestionError, match="future"):
        ingest(future)


def test_future_candle_timestamp_is_rejected():
    future_times = [INGESTED - timedelta(minutes=10), INGESTED - timedelta(minutes=5), INGESTED + timedelta(minutes=5)]
    with pytest.raises(ResearchIngestionError, match="candle timestamp is in the future"):
        ingest([payload(name, timestamps=future_times) for name in ("binance", "kraken", "coinbase")])


def test_divergent_source_and_misaligned_sources_are_rejected():
    divergent = [payload("binance"), payload("kraken"), payload("coinbase", closes=[100, 104, 102])]
    with pytest.raises(ResearchIngestionError, match="divergence"):
        ingest(divergent)
    shifted = [payload("binance"), payload("kraken"),
               payload("coinbase", timestamps=[
                   INGESTED - timedelta(minutes=14),
                   INGESTED - timedelta(minutes=9),
                   INGESTED - timedelta(minutes=4),
               ])]
    with pytest.raises(ResearchIngestionError, match="do not align"):
        ingest(shifted)


def test_provenance_mismatch_and_duplicate_sources_are_rejected():
    with pytest.raises(ResearchIngestionError, match="provenance mismatch"):
        ingest([payload("binance"), payload("kraken"), payload("coinbase", symbol="BTC-USD")])
    with pytest.raises(ResearchIngestionError, match="unique"):
        ingest([payload("binance"), payload("binance"), payload("coinbase")])


def test_insufficient_sources_and_invalid_interval_are_rejected():
    with pytest.raises(ResearchIngestionError, match="at least 3 source"):
        ingest([payload("binance"), payload("kraken")])
    with pytest.raises(ResearchIngestionError, match="interval must"):
        prepare_research_dataset(
            [payload("binance"), payload("kraken"), payload("coinbase")],
            symbol="BTC-USDT", interval="5 minutes", ingested_at=INGESTED.isoformat(),
        )


def test_fingerprint_excludes_ingestion_time_but_includes_data_provenance():
    first = ingest()
    later = prepare_research_dataset(
        [payload("binance"), payload("coinbase"), payload("kraken")],
        symbol="BTC-USDT", interval="5m",
        ingested_at=(INGESTED + timedelta(minutes=1)).isoformat(),
    )
    assert first["dataset_fingerprint"] == later["dataset_fingerprint"]
    assert first["provenance"]["ingested_at"] != later["provenance"]["ingested_at"]
