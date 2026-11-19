from datetime import datetime, timezone

from bitcoin_ai.market_data_smoke import run_market_data_smoke_check


class FakeIngestor:
    def __init__(self):
        self.kwargs = None

    def fetch_and_prepare(self, **kwargs):
        self.kwargs = kwargs
        return {
            "status": "prepared",
            "dataset_fingerprint": "f" * 64,
            "dataset": {
                "symbol": "BTC-USDT", "interval": "5m",
                "start": "2026-11-19T00:00:00+00:00",
                "end": "2026-11-19T08:15:00+00:00",
                "cross_source": {
                    "status": "cross_checked", "source_count": 3,
                    "sources": ["binance", "coinbase", "kraken"],
                    "maximum_close_deviation": 0.0002,
                },
            },
            "provenance": {"row_count": 100},
            "holdout_status": "not_assessed",
        }


def test_smoke_check_returns_provenance_without_strategy_or_execution():
    client = FakeIngestor()
    now = datetime(2026, 11, 19, tzinfo=timezone.utc)
    result = run_market_data_smoke_check(interval="5m", limit=100, ingestor=client, now=now)
    assert client.kwargs == {"interval": "5m", "limit": 100, "now": now}
    assert result["status"] == "market_data_validated"
    assert result["source_count"] == 3
    assert result["sources"] == ["binance", "coinbase", "kraken"]
    assert result["holdout_status"] == "not_assessed"
    assert result["strategy_evaluation"] == "not_run"
    assert result["execution_authority"] == "none"


def test_smoke_check_propagates_provider_failure_without_fallback():
    class BrokenIngestor:
        def fetch_and_prepare(self, **kwargs):
            raise RuntimeError("venue unavailable")
    try:
        run_market_data_smoke_check(ingestor=BrokenIngestor())
    except RuntimeError as exc:
        assert "venue unavailable" in str(exc)
    else:
        raise AssertionError("provider failure must fail closed")
