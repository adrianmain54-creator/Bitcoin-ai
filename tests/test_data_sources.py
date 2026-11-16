import json

import pytest

from bitcoin_ai.data_sources import DataSourceError, MempoolSpaceClient


class FakeResponse:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def fake_opener_for(routes, calls):
    def opener(request, timeout):
        calls.append((request.full_url, timeout))
        path = request.full_url.removeprefix("https://mempool.space/api/")
        return FakeResponse(routes[path])
    return opener


def sample_routes():
    return {
        "v1/prices": {"USD": 65000.25, "JPY": 9800000},
        "blocks/tip/height": "900000",
        "mempool": {"count": 1234, "vsize": 987654, "total_fee": 123456},
        "v1/fees/recommended": {
            "fastestFee": 12, "halfHourFee": 10, "hourFee": 8,
            "economyFee": 4, "minimumFee": 1
        },
    }


def test_snapshot_returns_provenance_and_expected_metrics():
    calls = []
    client = MempoolSpaceClient(opener=fake_opener_for(sample_routes(), calls), clock=lambda: 100)
    result = client.snapshot("usd")
    assert result["price"]["value"] == 65000.25
    assert result["block_height"]["value"] == 900000
    assert result["mempool"]["value"]["count"] == 1234
    assert result["recommended_fees"]["value"]["fastestFee"] == 12
    assert result["provider"] == "mempool.space"
    assert result["price"]["source_url"].endswith("/v1/prices")
    assert result["price"]["freshness"] == "fresh"


def test_short_ttl_cache_avoids_repeated_requests():
    calls = []
    client = MempoolSpaceClient(
        opener=fake_opener_for(sample_routes(), calls), clock=lambda: 100
    )
    client.snapshot()
    first_call_count = len(calls)
    result = client.snapshot()
    assert len(calls) == first_call_count
    assert result["price"]["cache_hit"] is True
    assert result["price"]["freshness"] == "cached"


def test_invalid_currency_is_rejected_before_network_call():
    calls = []
    client = MempoolSpaceClient(opener=fake_opener_for(sample_routes(), calls))
    with pytest.raises(ValueError, match="three-letter"):
        client.snapshot("US")
    assert calls == []


def test_missing_price_is_reported_as_data_source_error():
    routes = sample_routes()
    routes["v1/prices"] = {"EUR": 60000}
    client = MempoolSpaceClient(opener=fake_opener_for(routes, []))
    with pytest.raises(DataSourceError, match="No valid USD price"):
        client.snapshot()


def test_nonpositive_cache_and_timeout_settings_are_rejected():
    with pytest.raises(ValueError):
        MempoolSpaceClient(cache_ttl_seconds=-1)
    with pytest.raises(ValueError):
        MempoolSpaceClient(timeout_seconds=0)
