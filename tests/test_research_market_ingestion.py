from datetime import datetime, timezone
import json

import pytest

from bitcoin_ai.research_market_ingestion import (
    PublicResearchMarketIngestor,
    ResearchMarketFetchError,
)


NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)


class Response:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def venue_payloads():
    end = int(NOW.timestamp())
    base = end - 25 * 300
    prices = [100.0 + i * 0.1 for i in range(25)]
    binance = [
        [((base + i * 300) * 1000), str(p), str(p + 1), str(p - 1),
         str(p), "12.5", ((base + (i + 1) * 300) * 1000 - 1)]
        for i, p in enumerate(prices)
    ]
    kraken_rows = [
        [base + i * 300, str(p), str(p + 1), str(p - 1),
         str(p), str(p), "12.5", 20]
        for i, p in enumerate(prices)
    ]
    coinbase = [
        [base + i * 300, str(p - 1), str(p + 1), str(p),
         str(p), "12.5"]
        for i, p in enumerate(prices)
    ][::-1]
    return binance, {"error": [], "result": {"XXBTZUSDT": kraken_rows, "last": 1}}, coinbase


def client_for(payloads):
    def opener(request, **kwargs):
        url = request.full_url
        if "api.binance.com" in url:
            return Response(payloads[0])
        if "api.kraken.com" in url:
            return Response(payloads[1])
        if "api.exchange.coinbase.com" in url:
            return Response(payloads[2])
        raise AssertionError(f"unexpected endpoint: {url}")
    return PublicResearchMarketIngestor(opener=opener)


def test_fetches_three_public_sources_and_prepares_full_ohlcv_bundle():
    client = client_for(venue_payloads())
    report = client.fetch_and_prepare(interval="5m", limit=25, now=NOW)
    assert report["status"] == "prepared"
    assert report["provider"] == "public-exchange-apis"
    assert report["dataset"]["cross_source"]["sources"] == ["binance", "coinbase", "kraken"]
    assert report["provenance"]["row_count"] == 25
    assert set(report["dataset"]["canonical_bars"][0]) == {
        "timestamp", "open", "high", "low", "close", "volume"
    }
    assert report["holdout_status"] == "not_assessed"


def test_source_failure_aborts_instead_of_downgrading_to_two_sources():
    class FailingClient(PublicResearchMarketIngestor):
        def _kraken(self, interval, limit, now):
            raise ResearchMarketFetchError("simulated Kraken outage")
    payloads = venue_payloads()
    client = client_for(payloads)
    client._kraken = FailingClient()._kraken
    with pytest.raises(ResearchMarketFetchError, match="Kraken outage"):
        client.fetch_and_prepare(interval="5m", limit=25, now=NOW)


def test_divergent_third_venue_rejected_by_shared_ingestion_gate():
    payloads = list(venue_payloads())
    payloads[2] = [
        [row[0], row[1],
         str(float(row[4]) * 1.05 + 1) if i == 8 else row[2],
         row[3], str(float(row[4]) * (1.05 if i == 8 else 1)), row[5]]
        for i, row in enumerate(payloads[2])
    ]
    with pytest.raises(ResearchMarketFetchError, match="divergence"):
        client_for(payloads).fetch_and_prepare(interval="5m", limit=25, now=NOW)


def test_coinbase_unexpected_order_is_rejected_not_sorted():
    payloads = list(venue_payloads())
    payloads[2] = list(reversed(payloads[2]))
    with pytest.raises(ResearchMarketFetchError, match="newest-first"):
        client_for(payloads).fetch_and_prepare(interval="5m", limit=25, now=NOW)


def test_provider_interval_intersection_is_required():
    client = client_for(venue_payloads())
    with pytest.raises(ValueError, match="supported by all three"):
        client.fetch_and_prepare(interval="3m", limit=25, now=NOW)


@pytest.mark.parametrize("limit", [True, 19, 301, 1.5])
def test_invalid_history_limit_is_rejected(limit):
    with pytest.raises(ValueError, match="limit must"):
        client_for(venue_payloads()).fetch_and_prepare(limit=limit, now=NOW)


def test_timezone_naive_now_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        client_for(venue_payloads()).fetch_and_prepare(
            interval="5m", limit=25, now=datetime(2026, 11, 18, 12, 0),
        )
