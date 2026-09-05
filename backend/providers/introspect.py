"""Response introspection for the Phase 0 probe.

Pure functions, so the discovery logic is unit-testable and the probe script stays a thin
CLI around it.

Privacy property enforced by `summarize`: it emits field PATHS and TYPE NAMES only, never
a value. That is what makes the generated report safe to commit from a repo holding real
health data.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

#: Metrics we care about, and key fragments that would indicate them. Matched
#: case-insensitively against leaf key names, so discovery does not depend on guessing
#: Garmin's exact field naming.
METRIC_PATTERNS: dict[str, tuple[str, ...]] = {
    "sleep duration":     ("sleeptimeseconds", "sleepdurationseconds", "totalsleepseconds"),
    "sleep score":        ("sleepscore", "overallsleepscore", "sleepqualityscore"),
    "sleep start/end":    ("sleepstarttimestamp", "sleependtimestamp", "sleepstart"),
    "deep sleep":         ("deepsleepseconds", "deepsleep"),
    "light sleep":        ("lightsleepseconds", "lightsleep"),
    "REM sleep":          ("remsleepseconds", "remsleep"),
    "awake time":         ("awakesleepseconds", "awakeduration", "awakecount"),
    "HRV":                ("hrv", "lastnightavg", "weeklyavg", "hrvsummary"),
    "resting HR":         ("restingheartrate", "restinghr"),
    "body battery":       ("bodybattery", "charged", "drained"),
    "stress":             ("stresslevel", "averagestresslevel", "stressduration"),
    "respiration":        ("respiration", "avgwakingrespirationvalue", "breathsperminute"),
    "SpO2 / pulse ox":    ("spo2", "averagespo2", "pulseox"),
    "steps":              ("totalsteps", "steps"),
    "distance":           ("totaldistancemeters", "distance"),
    "active calories":    ("activekilocalories", "activecalories"),
    "resting calories":   ("bmrkilocalories", "restingkilocalories"),
    "total calories":     ("totalkilocalories",),
    "intensity minutes":  ("intensityminutes", "moderateintensityminutes", "vigorousintensityminutes"),
    "VO2 max":            ("vo2max", "vo2maxvalue", "vo2maxprecisevalue"),
    "weight":             ("weight",),
    "training readiness": ("trainingreadiness", "readinessscore"),
    "training status":    ("trainingstatus", "trainingstatuskey"),
}

#: The metrics the Recovery and Energy screens cannot be built without.
TIER_1_METRICS: tuple[str, ...] = (
    "sleep duration", "HRV", "resting HR", "body battery", "total calories", "steps",
)


def summarize(
    obj: Any,
    prefix: str = "",
    depth: int = 0,
    max_depth: int = 3,
) -> list[tuple[str, str]]:
    """Walk a JSON response and describe its SHAPE: field paths and type names only.

    Given {"sleep": {"durationSeconds": 25440}} this returns:

        [("sleep", "dict"), ("sleep.durationSeconds", "int")]

    NEVER A VALUE. That is the privacy property that makes the generated report safe to
    keep beside real health data, and there is a test asserting it.

    Two other behaviours worth knowing:

      * Lists are sampled at the FIRST element only. One entry is enough to learn the
        shape, and walking a 1,440-point intraday heart-rate series would bury the
        signal in noise.
      * A None value is reported as the type "null", not skipped. That distinction is
        what revealed that some endpoints return a complete object full of nulls.

    Arguments:
        obj        the piece of JSON being described right now
        prefix     the path that led here, e.g. "dailySleepDTO"
        depth      how deep we currently are (starts at 0)
        max_depth  stop descending past this depth
    """
    described_fields: list[tuple[str, str]] = []

    # Stop before the recursion goes too deep. Garmin nests intraday data quite far,
    # and past a few levels it is all repetition.
    if depth > max_depth:
        return described_fields

    if isinstance(obj, dict):
        for key, value in obj.items():
            # Build the dotted path to this field. At the top level there is no prefix
            # yet, so the key itself is the whole path.
            if prefix:
                path = f"{prefix}.{key}"
            else:
                path = str(key)

            if isinstance(value, (dict, list)):
                # Record the container itself, then describe what is inside it.
                described_fields.append((path, type(value).__name__))
                described_fields.extend(summarize(value, path, depth + 1, max_depth))
            else:
                # A plain value. Record its TYPE, never the value itself.
                if value is None:
                    type_name = "null"
                else:
                    type_name = type(value).__name__

                described_fields.append((path, type_name))

    elif isinstance(obj, list):
        # Note the length, which tells us whether the endpoint returned anything.
        described_fields.append((f"{prefix}[]", f"list[{len(obj)}]"))

        if obj:
            described_fields.extend(summarize(obj[0], f"{prefix}[0]", depth + 1, max_depth))

    return described_fields


def normalize_key_for_matching(path: str) -> str:
    """Reduce a field path to just its last key, in a comparable form.

    "dailySleepDTO.sleep_Time_Seconds[]"  ->  "sleeptimeseconds"

    Lower case, underscores removed and any trailing "[]" stripped, so the patterns
    below match regardless of how Garmin happened to punctuate a name.
    """
    last_key = path.rsplit(".", 1)[-1]
    return last_key.lower().replace("_", "").rstrip("[]")


def find_metrics(payloads: dict[str, Any], *, max_depth: int = 4) -> dict[str, list[str]]:
    """Search every response for the metrics we care about, and report where each lives.

    This is the inversion at the heart of the probe. The obvious approach is to read a
    field path we assume exists -- and if the assumption is wrong you get a KeyError and
    learn nothing. Searching instead means the tool TELLS US where each metric actually
    is, which is how we found the numeric sleep score buried at
    `dailySleepDTO.sleepScores.overall.value` next to three text fields with almost the
    same names.

    Returns a dictionary of metric name -> list of places it was found.
    """
    locations_by_metric: dict[str, list[str]] = defaultdict(list)

    for endpoint_name, payload in payloads.items():
        if payload is None:
            continue

        for path, type_name in summarize(payload, max_depth=max_depth):
            # A field that exists but is null tells us the metric is NOT available, so
            # it should not count as having been found.
            if type_name == "null":
                continue

            leaf_key = normalize_key_for_matching(path)

            for metric_name, patterns in METRIC_PATTERNS.items():
                matches_this_metric = False
                for pattern in patterns:
                    if pattern in leaf_key:
                        matches_this_metric = True
                        break

                if not matches_this_metric:
                    continue

                location = f"`{endpoint_name}` -> `{path}`"

                # The same metric often appears in several endpoints; record each place
                # once so the report does not repeat itself.
                if location not in locations_by_metric[metric_name]:
                    locations_by_metric[metric_name].append(location)

    return dict(locations_by_metric)


def missing_tier_1(locations_by_metric: dict[str, list[str]]) -> list[str]:
    """Which essential metrics were not found anywhere.

    If this comes back non-empty, the dashboard cannot be built as designed and that is
    worth stopping to look at before writing any more code.
    """
    not_found: list[str] = []

    for metric_name in TIER_1_METRICS:
        found_locations = locations_by_metric.get(metric_name)
        if not found_locations:
            not_found.append(metric_name)

    return not_found
