from datetime import datetime, timedelta, timezone

import pytest

from bitcoin_ai.backtesting import Bar
from bitcoin_ai.data_quality import audit_price_bars


def make_bars(closes, seconds=60):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        Bar(start + timedelta(seconds=i * seconds), close)
        for i, close in enumerate(closes)
    ]


def test_clean_regular_series_passes():
    report = audit_price_bars(make_bars([100, 101, 100.5, 102]),
                              expected_interval_seconds=60)
    assert report["usable"] is True
    assert report["status"] == "pass"
    assert report["interval_audit"]["mismatch_count"] == 0


def test_missing_interval_fails_closed_without_repairing_data():
    bars = make_bars([100, 101, 102, 103])
    bars[2] = Bar(bars[2].timestamp + timedelta(minutes=1), bars[2].close)
    report = audit_price_bars(bars, expected_interval_seconds=60)
    assert report["usable"] is False
    assert report["status"] == "fail"
    assert report["interval_audit"]["mismatch_count"] == 2
    assert len(bars) == 4


def test_duplicate_or_out_of_order_timestamps_fail():
    bars = make_bars([100, 101, 102])
    bars[2] = Bar(bars[1].timestamp, bars[2].close)
    report = audit_price_bars(bars)
    assert not report["usable"]
    assert any("duplicate or out of order" in error for error in report["errors"])


def test_large_move_is_review_warning_not_silently_removed():
    report = audit_price_bars(make_bars([100, 101, 140]))
    assert report["usable"] is True
    assert report["status"] == "review"
    assert report["anomaly_audit"]["outlier_count"] == 1


def test_long_identical_close_run_is_flagged():
    report = audit_price_bars(make_bars([100] * 9), flatline_run=8)
    assert report["status"] == "review"
    assert report["anomaly_audit"]["longest_identical_close_run"] == 9


@pytest.mark.parametrize("kwargs", [
    {"expected_interval_seconds": 0},
    {"expected_interval_seconds": True},
    {"max_abs_return_pct": float("nan")},
    {"flatline_run": 1},
])
def test_invalid_audit_configuration_is_rejected(kwargs):
    with pytest.raises(ValueError):
        audit_price_bars(make_bars([100, 101, 102]), **kwargs)


def test_too_few_observations_fail():
    report = audit_price_bars(make_bars([100, 101]))
    assert report["status"] == "fail"
    assert not report["usable"]
