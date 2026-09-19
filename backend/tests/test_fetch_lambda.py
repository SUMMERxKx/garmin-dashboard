"""Tests for the scheduled fetcher's decisions.

Not for the fetching itself, which is somebody else's network and is covered by running
it. What is worth pinning is the small amount of judgement in the file: which days a run
asks for, and how it reports what happened.
"""

from __future__ import annotations

import datetime

from backend.garmin import fetch_lambda


def test_a_run_never_asks_for_today() -> None:
    """Today is unfinished: the day is not over, the watch may not have synced since this
    morning, and calories and steps are still climbing. Every other part of this project
    defaults to yesterday for the same reason."""
    days = fetch_lambda.days_to_fetch(datetime.date(2026, 9, 19), how_many=3)

    assert datetime.date(2026, 9, 19) not in days
    assert days[-1] == datetime.date(2026, 9, 18)


def test_a_run_asks_for_the_right_span_oldest_first() -> None:
    days = fetch_lambda.days_to_fetch(datetime.date(2026, 9, 19), how_many=3)

    assert days == [
        datetime.date(2026, 9, 16),
        datetime.date(2026, 9, 17),
        datetime.date(2026, 9, 18),
    ]


def test_asking_for_one_day_gives_exactly_yesterday() -> None:
    days = fetch_lambda.days_to_fetch(datetime.date(2026, 1, 1), how_many=1)

    assert days == [datetime.date(2025, 12, 31)]


def test_the_outcome_says_ok_only_when_nothing_failed() -> None:
    """The scheduler and any alarm read this, so 'ok' has to mean it."""
    assert fetch_lambda.describe_outcome(["2026-09-18"], [])["ok"] is True
    assert fetch_lambda.describe_outcome(["2026-09-18"], ["2026-09-17"])["ok"] is False
    assert fetch_lambda.describe_outcome([], ["2026-09-18"])["ok"] is False


def test_the_outcome_lists_both_sides() -> None:
    """Which days worked matters as much as whether any did: a run that gets two of three
    is fine and self-repairing, and one that gets none is a dead token bundle."""
    outcome = fetch_lambda.describe_outcome(["a", "b"], ["c"])

    assert outcome["fetched"] == ["a", "b"]
    assert outcome["failed"] == ["c"]
