"""Recovery status -- our own score, because the watch does not provide one.

The Forerunner 165 has no "Training Readiness" or "Training Status" number; Garmin
reserves those for its more expensive watches. It does report every ingredient though
(sleep, HRV, resting heart rate, Body Battery, stress), so we build the score ourselves.

Because it is ours and not Garmin's, it is labelled as derived everywhere it appears.
We never present a number we calculated as if the device had reported it.

The whole thing is designed to cope with missing data, because missing data is normal:
the watch gets left on the charger, and HRV needs about three weeks of nights before a
baseline means anything.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from datetime import timedelta

from backend.core import baselines
from backend.core import models
from backend.core import reasons


@dataclass(frozen=True)
class RecoveryInput:
    """One ingredient of the recovery score, and how to interpret it.

    `higher_is_better` is the important field. Both HRV and resting heart rate can go
    up, but they mean opposite things when they do: higher HRV is a good sign, and a
    higher resting heart rate is a bad one. Without this flag the score would treat
    them the same way and be actively misleading.
    """

    metric_name: str
    higher_is_better: bool
    reason_when_worse: reasons.ReasonCode
    unit: str | None = None


# The ingredients, in the order they are reported. Any of them may be missing.
RECOVERY_INPUTS: tuple[RecoveryInput, ...] = (
    RecoveryInput(
        metric_name="sleep_duration_min",
        higher_is_better=True,
        reason_when_worse=reasons.ReasonCode.SLEEP_BELOW_BASELINE,
        unit="min",
    ),
    RecoveryInput(
        metric_name="sleep_score",
        higher_is_better=True,
        reason_when_worse=reasons.ReasonCode.SLEEP_SCORE_BELOW_BASELINE,
    ),
    RecoveryInput(
        metric_name="hrv_ms",
        higher_is_better=True,
        reason_when_worse=reasons.ReasonCode.HRV_BELOW_BASELINE,
        unit="ms",
    ),
    RecoveryInput(
        metric_name="resting_hr",
        higher_is_better=False,      # a rising resting heart rate is a warning sign
        reason_when_worse=reasons.ReasonCode.RHR_ABOVE_BASELINE,
        unit="bpm",
    ),
    RecoveryInput(
        metric_name="body_battery_high",
        higher_is_better=True,
        reason_when_worse=reasons.ReasonCode.BODY_BATTERY_BELOW_BASELINE,
    ),
    RecoveryInput(
        metric_name="stress_avg",
        higher_is_better=False,      # more stress is worse
        reason_when_worse=reasons.ReasonCode.STRESS_ABOVE_BASELINE,
    ),
)

# Metrics we expect to have most days. If one of these is absent it is worth saying so,
# because it usually means the watch was not worn.
METRICS_WORTH_REPORTING_AS_MISSING = ("sleep_duration_min", "hrv_ms")

# How far the average vote has to swing before we call the whole day good or bad.
# Roughly: a third of the available inputs have to agree.
VOTE_THRESHOLD = 0.34

# HRV below baseline for this many days in a row stops being noise and becomes a signal.
CONSECUTIVE_DAYS_WORTH_FLAGGING = 3


def score_from_average_vote(average_vote: float) -> float:
    """Turn an average vote between -1 and +1 into a 0-100 score.

        average vote  -1  ->  score 0    (everything worse than normal)
        average vote   0  ->  score 50   (a normal day)
        average vote  +1  ->  score 100  (everything better than normal)
    """
    score = 50.0 + (50.0 * average_vote)

    # Clamp, so rounding can never produce 100.4 or -0.2.
    if score < 0.0:
        return 0.0
    if score > 100.0:
        return 100.0
    return score


def status_from_average_vote(average_vote: float) -> models.Status:
    """Turn the average vote into an overall verdict."""
    if average_vote <= -VOTE_THRESHOLD:
        return models.Status.BELOW
    if average_vote >= VOTE_THRESHOLD:
        return models.Status.ABOVE
    return models.Status.NORMAL


def recovery_status(
    current: dict[str, float | None],
    history: dict[str, baselines.Series],
    on: date,
    *,
    window_days: int = 30,
) -> models.RecoveryResult:
    """Score today's recovery against this person's own normal.

    Each ingredient that has both a value today AND enough history to form a baseline
    casts one vote:

        +1  better than normal
         0  about normal
        -1  worse than normal

    The votes are AVERAGED, not added up. That choice matters: dividing by the number of
    ingredients that actually voted means a missing ingredient reduces our confidence
    rather than quietly counting as "normal". A weighted formula would silently change
    meaning whenever a term went missing.
    """
    votes: list[float] = []
    recovery_reasons: list[reasons.Reason] = []
    metrics_that_voted: list[str] = []
    baselines_used: dict[str, models.Baseline] = {}

    for recovery_input in RECOVERY_INPUTS:
        metric_name = recovery_input.metric_name
        value_today = current.get(metric_name)
        past_values = history.get(metric_name, [])

        # --- case 1: no reading today ------------------------------------
        if value_today is None:
            if metric_name in METRICS_WORTH_REPORTING_AS_MISSING:
                recovery_reasons.append(reasons.Reason(code=reasons.ReasonCode.METRIC_MISSING, metric=metric_name))
            continue

        # --- case 2: not enough history to know what "normal" is ---------
        this_metrics_baseline = baselines.baseline(past_values, metric_name, window_days, on)

        if this_metrics_baseline is None:
            readings_so_far = 0
            for _day, value in past_values:
                if value is not None:
                    readings_so_far += 1

            recovery_reasons.append(
                reasons.Reason(
                    code=reasons.ReasonCode.BASELINE_BUILDING,
                    metric=metric_name,
                    window_days=window_days,
                    n=readings_so_far,
                    detail={"required": max(3, window_days // 2)},
                )
            )
            continue

        # --- case 3: we can compare today against normal -----------------
        today_versus_normal = baselines.deviation(value_today, this_metrics_baseline)

        # `deviation` only returns None when a value or baseline is missing, and we
        # have already established that both exist.
        assert today_versus_normal is not None

        baselines_used[metric_name] = this_metrics_baseline
        metrics_that_voted.append(metric_name)

        if today_versus_normal.status is models.Status.NORMAL:
            votes.append(0.0)
            continue

        # Work out whether the movement is good news for this particular metric.
        metric_went_up = today_versus_normal.status is models.Status.ABOVE

        if recovery_input.higher_is_better:
            this_is_good_news = metric_went_up
        else:
            this_is_good_news = not metric_went_up

        if this_is_good_news:
            votes.append(1.0)
        else:
            votes.append(-1.0)

            # Only bad news gets an explanation. The dashboard's "Why?" panel is for
            # understanding a poor score, not for celebrating a good one.
            recovery_reasons.append(
                reasons.Reason(
                    code=recovery_input.reason_when_worse,
                    metric=metric_name,
                    current=value_today,
                    baseline=this_metrics_baseline.mean,
                    unit=recovery_input.unit,
                    difference=today_versus_normal.difference,
                    difference_percent=today_versus_normal.difference_percent,
                    window_days=window_days,
                    n=this_metrics_baseline.n,
                )
            )

    # Nothing could vote, so we genuinely do not know. Say that instead of inventing a
    # number -- a brand-new user should see "building your baseline", not a score of 72.
    if not votes:
        return models.RecoveryResult(
            status=models.Status.UNKNOWN,
            score=None,
            inputs_used=[],
            reasons=recovery_reasons,
        )

    average_vote = sum(votes) / len(votes)

    # One bad night is noise. Several in a row is worth pointing out, and it is
    # something a single-day score cannot express on its own.
    hrv_baseline = baselines_used.get("hrv_ms")
    if hrv_baseline is not None:
        days_in_a_row = baselines.consecutive_beyond(
            history.get("hrv_ms", []),
            hrv_baseline,
            direction=models.Status.BELOW,
            on=on,
        )
        if days_in_a_row >= CONSECUTIVE_DAYS_WORTH_FLAGGING:
            recovery_reasons.append(
                reasons.Reason(
                    code=reasons.ReasonCode.HRV_SUPPRESSED_CONSECUTIVE,
                    metric="hrv_ms",
                    detail={"consecutive_days": days_in_a_row},
                )
            )

    return models.RecoveryResult(
        status=status_from_average_vote(average_vote),
        score=score_from_average_vote(average_vote),
        inputs_used=metrics_that_voted,
        reasons=recovery_reasons,
    )


def sleep_debt(
    series: baselines.Series,
    on: date,
    target_hours: float = 8.0,
    *,
    window: int = 7,
) -> float | None:
    """Total hours of sleep missed over the window, compared to a nightly target.

    A positive number means you are short overall. A negative one means you slept more
    than the target. Returns None if nothing was recorded.
    """
    first_day_in_window = on - timedelta(days=window - 1)

    nights_in_window = []
    for day, minutes_slept in series:
        if minutes_slept is None:
            continue
        if first_day_in_window <= day <= on:
            nights_in_window.append(minutes_slept)

    if not nights_in_window:
        return None

    total_shortfall = 0.0
    for minutes_slept in nights_in_window:
        hours_slept = minutes_slept / 60.0
        total_shortfall += target_hours - hours_slept

    return total_shortfall


def sleep_consistency(
    bedtimes: Sequence[tuple[date, float]],
    on: date,
    *,
    window: int = 14,
) -> float | None:
    """How consistent your bedtime is, as a spread in hours. Lower is more consistent.

    Takes bedtimes as a clock hour (23.5 meaning 11:30pm) and reports the standard
    deviation. Needs at least three nights to mean anything.
    """
    first_day_in_window = on - timedelta(days=window - 1)

    hours_in_window = []
    for day, bedtime_hour in bedtimes:
        if first_day_in_window <= day <= on:
            hours_in_window.append(bedtime_hour)

    if len(hours_in_window) < 3:
        return None

    average_bedtime = sum(hours_in_window) / len(hours_in_window)

    total_squared_distance = 0.0
    for bedtime_hour in hours_in_window:
        distance_from_average = bedtime_hour - average_bedtime
        total_squared_distance += distance_from_average * distance_from_average

    variance = total_squared_distance / (len(hours_in_window) - 1)
    return variance**0.5
