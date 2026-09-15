"""The list of Garmin endpoints we fetch, and why each one is on the list.

This module holds no logic. It is a description of *what* to fetch. The code that
actually does the fetching reads this list and loops over it, which means the fetching
is written once instead of seventeen times.

Why a list of records instead of seventeen function calls
---------------------------------------------------------
The `garminconnect` library exposes far more than we use: golf metrics, race
predictors, per-second sensor streams. The seventeen below were chosen against the
questions this dashboard answers, not against what the API happens to offer. Keeping
that choice in one visible place means the reason for each call is written down next to
the call itself, rather than living in someone's memory.

It also handles an awkwardness in the API: most endpoints take a single date, but two of
them take a start date and an end date. Recording that difference as a field means no
caller ever has to remember which is which.
"""

from __future__ import annotations

import dataclasses
import enum


class ArgumentStyle(enum.Enum):
    """How a particular endpoint wants its dates.

    An Enum is a fixed set of named values -- the same idea as an enum in Java. Using
    one here rather than plain strings means a typo like "one_dat" fails immediately
    instead of quietly matching nothing at the point we build the call.
    """

    #: The method takes one date: method("2026-09-10")
    ONE_DATE = "one_date"

    #: The method takes a start and an end: method("2026-09-10", "2026-09-10")
    #: We pass the same day twice, because we always fetch exactly one day at a time.
    START_AND_END_DATE = "start_and_end_date"


@dataclasses.dataclass(frozen=True)
class Endpoint:
    """One Garmin call: what to invoke, how to invoke it, and what it is for.

    `@dataclasses.dataclass` writes the constructor and the comparison methods for us
    from the field list below. It is close to a `record` in modern Java.

    `frozen=True` makes an instance read-only after it is built, the way `final` fields
    do. These describe fixed facts about the API, so nothing should ever modify one at
    runtime, and making that impossible is cheaper than trusting it.
    """

    #: Our own short name for this call. It becomes the filename the raw response is
    #: saved under, so it must be safe to put in a path: lowercase, underscores only.
    name: str

    #: The exact method name to call on the logged-in garminconnect client. Looked up
    #: by name at fetch time, which is why this is a string rather than the function.
    client_method_name: str

    #: Whether the method wants one date or a start and an end. See ArgumentStyle.
    argument_style: ArgumentStyle

    #: 1 means the dashboard has to work using only tier 1 endpoints. 2 means the data
    #: is enrichment: nice to have, and every field derived from it stays optional.
    tier: int

    #: Which part of the dashboard consumes this. Free text, for humans reading the file.
    feeds: str

    #: Anything worth knowing before you rely on this endpoint -- especially what the
    #: Phase 0 probe found when it was run against the real watch.
    note: str = ""


# ---------------------------------------------------------------------------
# The list itself
# ---------------------------------------------------------------------------
#
# Written with the field names spelled out on every line. That is far longer than
# packing each endpoint onto one line, and it is deliberate: this is a reference table
# people will read more often than they edit, and reading it should not require
# counting commas to work out which value is the tier.

ENDPOINTS: tuple[Endpoint, ...] = (
    # ---- Tier 1 ----------------------------------------------------------
    # The dashboard is designed to work on these seven alone. If one of them stops
    # returning data, that is a real outage rather than a degraded display.
    Endpoint(
        name="user_summary",
        client_method_name="get_user_summary",
        argument_style=ArgumentStyle.ONE_DATE,
        tier=1,
        feeds="energy and activity",
        note="steps, distance, active/resting/total calories, intensity minutes",
    ),
    Endpoint(
        name="stats",
        client_method_name="get_stats",
        argument_style=ArgumentStyle.ONE_DATE,
        tier=1,
        feeds="energy",
        note="daily totals; overlaps user_summary, kept because the two disagree sometimes",
    ),
    Endpoint(
        name="sleep",
        client_method_name="get_sleep_data",
        argument_style=ArgumentStyle.ONE_DATE,
        tier=1,
        feeds="recovery",
        note="duration, score and stages; the numeric score is buried several levels down",
    ),
    Endpoint(
        name="hrv",
        client_method_name="get_hrv_data",
        argument_style=ArgumentStyle.ONE_DATE,
        tier=1,
        feeds="recovery",
        note="often missing for the first few weeks, until Garmin has formed a baseline",
    ),
    Endpoint(
        name="rhr",
        client_method_name="get_rhr_day",
        argument_style=ArgumentStyle.ONE_DATE,
        tier=1,
        feeds="recovery",
        note="resting heart rate",
    ),
    Endpoint(
        name="body_battery",
        client_method_name="get_body_battery",
        argument_style=ArgumentStyle.START_AND_END_DATE,
        tier=1,
        feeds="recovery",
        note="",
    ),
    Endpoint(
        name="activities",
        client_method_name="get_activities_by_date",
        argument_style=ArgumentStyle.START_AND_END_DATE,
        tier=1,
        feeds="activity",
        note="workouts: type, duration, calories, heart rate",
    ),

    # ---- Tier 2 ----------------------------------------------------------
    # Enrichment. Everything derived from these stays optional, so a missing one
    # degrades the display rather than breaking the run.
    Endpoint(
        name="stress",
        client_method_name="get_stress_data",
        argument_style=ArgumentStyle.ONE_DATE,
        tier=2,
        feeds="recovery",
        note="",
    ),
    Endpoint(
        name="heart_rates",
        client_method_name="get_heart_rates",
        argument_style=ArgumentStyle.ONE_DATE,
        tier=2,
        feeds="activity",
        note="heart rate sampled through the day, not a single number",
    ),
    Endpoint(
        name="intensity_minutes",
        client_method_name="get_intensity_minutes_data",
        argument_style=ArgumentStyle.ONE_DATE,
        tier=2,
        feeds="activity",
        note="",
    ),
    Endpoint(
        name="respiration",
        client_method_name="get_respiration_data",
        argument_style=ArgumentStyle.ONE_DATE,
        tier=2,
        feeds="recovery",
        note="",
    ),
    Endpoint(
        name="spo2",
        client_method_name="get_spo2_data",
        argument_style=ArgumentStyle.ONE_DATE,
        tier=2,
        feeds="recovery",
        note="returns a full response on the FR165 with every value inside it null",
    ),
    Endpoint(
        name="max_metrics",
        client_method_name="get_max_metrics",
        argument_style=ArgumentStyle.ONE_DATE,
        tier=2,
        feeds="trends",
        note="VO2 max. The probe found this EMPTY: the FR165 does not measure it.",
    ),
    Endpoint(
        name="daily_weigh_ins",
        client_method_name="get_daily_weigh_ins",
        argument_style=ArgumentStyle.ONE_DATE,
        tier=2,
        feeds="body",
        note="picks up a weight typed into Garmin Connect by hand; there is no smart scale",
    ),
    Endpoint(
        name="steps_intraday",
        client_method_name="get_steps_data",
        argument_style=ArgumentStyle.ONE_DATE,
        tier=2,
        feeds="activity",
        note="steps broken down through the day",
    ),

    # ---- Known to be unavailable on this watch ---------------------------
    # We call these anyway. Knowing for certain that an endpoint returns nothing is a
    # finding worth keeping, and if a firmware update ever fills them in, the saved
    # responses are how we would notice.
    Endpoint(
        name="training_readiness",
        client_method_name="get_training_readiness",
        argument_style=ArgumentStyle.ONE_DATE,
        tier=2,
        feeds="nothing yet",
        note="The probe found this EMPTY. Garmin ships it on the FR265 and above.",
    ),
    Endpoint(
        name="training_status",
        client_method_name="get_training_status",
        argument_style=ArgumentStyle.ONE_DATE,
        tier=2,
        feeds="nothing yet",
        note="Responds, but every field inside is null on the FR165.",
    ),
)


# ---------------------------------------------------------------------------
# Small helpers for reading the list
# ---------------------------------------------------------------------------


def tier_one_endpoints() -> list[Endpoint]:
    """Just the endpoints the dashboard cannot work without.

    Useful when checking whether a day's fetch was good enough to display, as opposed
    to whether every single call happened to succeed.
    """
    important_endpoints = []

    for endpoint in ENDPOINTS:
        if endpoint.tier == 1:
            important_endpoints.append(endpoint)

    return important_endpoints
