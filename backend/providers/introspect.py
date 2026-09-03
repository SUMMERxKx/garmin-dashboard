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
    obj: Any, prefix: str = "", depth: int = 0, max_depth: int = 3
) -> list[tuple[str, str]]:
    """Field paths and type names. Never values.

    Recurses into the first element of a list only -- one sample is enough to learn a
    shape, and walking a 1,440-point intraday series would bury the signal.
    """
    out: list[tuple[str, str]] = []
    if depth > max_depth:
        return out
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, dict | list):
                out.append((path, type(value).__name__))
                out.extend(summarize(value, path, depth + 1, max_depth))
            else:
                out.append((path, "null" if value is None else type(value).__name__))
    elif isinstance(obj, list):
        out.append((f"{prefix}[]", f"list[{len(obj)}]"))
        if obj:
            out.extend(summarize(obj[0], f"{prefix}[0]", depth + 1, max_depth))
    return out


def find_metrics(payloads: dict[str, Any], *, max_depth: int = 4) -> dict[str, list[str]]:
    """Which endpoint and path each metric of interest actually turned up at."""
    hits: dict[str, list[str]] = defaultdict(list)
    for endpoint, payload in payloads.items():
        if payload is None:
            continue
        for path, kind in summarize(payload, max_depth=max_depth):
            if kind == "null":
                continue
            leaf = path.rsplit(".", 1)[-1].lower().replace("_", "").rstrip("[]")
            for metric, patterns in METRIC_PATTERNS.items():
                if any(pattern in leaf for pattern in patterns):
                    location = f"`{endpoint}` -> `{path}`"
                    if location not in hits[metric]:
                        hits[metric].append(location)
    return dict(hits)


def missing_tier_1(hits: dict[str, list[str]]) -> list[str]:
    return [metric for metric in TIER_1_METRICS if not hits.get(metric)]
