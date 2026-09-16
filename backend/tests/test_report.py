"""Tests for the dashboard's baseline summaries.

`baselines.py` is already pinned by its own tests. These check the packaging around it:
that the window ends on the right day, that the latest reading is the right one, and that
a metric with too little history says so rather than inventing a normal.
"""

from __future__ import annotations

import datetime

from backend.engine import report
from backend.garmin import normalize

FIRST = datetime.date(2026, 8, 16)


def day(offset: int) -> datetime.date:
    return FIRST + datetime.timedelta(days=offset)


def a_snapshot(on: datetime.date, hrv: float | None, resting_heart_rate: int | None) -> normalize.DailySnapshot:
    return normalize.DailySnapshot(
        day=on,
        energy=normalize.Energy(),
        sleep=normalize.Sleep(),
        recovery=normalize.Recovery(hrv_last_night=hrv, resting_heart_rate=resting_heart_rate),
        body=normalize.Body(),
    )


def thirty_days() -> list[normalize.DailySnapshot]:
    """Thirty consecutive days with an HRV that climbs from 90 to 119 and a flat RHR."""
    snapshots = []

    for offset in range(30):
        snapshots.append(a_snapshot(day(offset), 90.0 + offset, 45))

    return snapshots


def test_the_windows_end_on_the_last_day_with_garmin_data_not_the_last_day() -> None:
    """A weigh-in creates a day with no readings; ending a window there shortens it."""
    snapshots = thirty_days()
    empty_morning = normalize.normalize_day({}, day(30))

    assert report.last_day_with_garmin_data([*snapshots, empty_morning]) == day(29)


def test_no_garmin_data_at_all_gives_no_end_day() -> None:
    assert report.last_day_with_garmin_data([normalize.normalize_day({}, day(0))]) is None


def test_the_latest_reading_is_the_newest_one_with_a_value() -> None:
    snapshots = thirty_days()
    # The final night produced no HRV.
    snapshots[-1].recovery.hrv_last_night = None

    summary = report.summarise_readings(
        "hrv_last_night",
        report.readings_for(snapshots, report.read_hrv),
        ending_on=day(29),
    )

    assert summary.latest_day == day(28)
    assert summary.latest_value == 118.0


def test_both_windows_are_built_when_there_is_enough_history() -> None:
    summaries = report.summarise_snapshots(thirty_days(), ending_on=day(29))

    hrv = summaries["hrv_last_night"]

    assert hrv.short_window is not None
    assert hrv.short_window.sample_size == 7
    assert hrv.long_window is not None
    assert hrv.long_window.sample_size == 30

    # The newest reading (119) against a rising month: above its 30-day normal.
    assert hrv.position_against_long_window == "above"


def test_a_flat_metric_reads_typical() -> None:
    summaries = report.summarise_snapshots(thirty_days(), ending_on=day(29))

    assert summaries["resting_heart_rate"].position_against_long_window == "typical"


def test_too_little_history_gives_no_long_window_and_no_position() -> None:
    """Ten days is enough for a week's normal and not for a month's. Say so."""
    summaries = report.summarise_snapshots(thirty_days()[:10], ending_on=day(9))

    hrv = summaries["hrv_last_night"]

    assert hrv.short_window is not None
    assert hrv.long_window is None
    assert hrv.position_against_long_window is None
    # The latest reading is still reported; it is the comparison that is withheld.
    assert hrv.latest_value == 99.0


def test_every_dashboard_metric_gets_a_summary_even_when_empty() -> None:
    """The browser looks each one up by name; a missing key would be a crash, not a gap."""
    summaries = report.summarise_snapshots([normalize.normalize_day({}, day(0))], ending_on=day(0))

    assert set(summaries) == set(report.SNAPSHOT_METRICS)

    for one_summary in summaries.values():
        assert one_summary.latest_value is None
        assert one_summary.short_window is None
