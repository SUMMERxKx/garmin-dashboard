"""Turning the dashboard's payload into a short sheet of finished facts.

THE RULE THIS FILE EXISTS TO ENFORCE
=====================================
The model never computes anything. Every number it will ever see has already been worked
out by code that is tested, and it arrives here finished. The model's only job is to say
what the numbers mean in a sentence or two.

That is not a stylistic preference. A language model asked to do arithmetic will produce
an answer that looks exactly as confident whether it is right or wrong, and on a health
dashboard the wrong answer is one you might act on. So the split is structural: Python
owns every figure, and the model owns only the English.

`interpret.py` completes the enforcement by checking the reply: any number the model
writes that does not appear on this sheet is treated as invented, and the whole answer is
rejected.

WHY IT IS SHORT
===============
It would be easy to send sixty days of readings and let the model find the story. That
costs more, takes longer, and makes the number-checking useless -- with enough figures in
front of it, almost any number it invents would coincidentally match one. A compact sheet
of the figures that actually matter keeps the check meaningful and the bill small.

Nothing here reads the clock, the database or the network. It takes the payload the
dashboard already has and returns text.
"""

from __future__ import annotations

from typing import Any

#: Metrics worth putting in front of the model, and how to say them in English. The
#: order is the order they appear on the sheet, which is roughly most to least important.
METRIC_LABELS = [
    ("hrv_last_night", "HRV", "ms", 0),
    ("resting_heart_rate", "resting heart rate", "bpm", 0),
    ("sleep_total_minutes", "sleep", "minutes", 0),
    ("sleep_score", "sleep score", "/100", 0),
    ("body_battery_charged", "body battery charged overnight", "", 0),
    ("average_stress", "average stress", "", 0),
    ("steps", "steps", "", 0),
    ("total_kilocalories", "calories burned", "kcal", 0),
]

#: How many recent days of energy balance to summarise.
RECENT_DAYS = 7


def format_number(value: float | None, places: int = 0) -> str:
    """One way of writing a number, used everywhere on the sheet.

    Consistency matters more than prettiness here: the reply-checker in `interpret.py`
    looks for these exact strings, so a figure written two different ways would make a
    legitimate answer look invented.
    """
    if value is None:
        return "no reading"

    if places == 0:
        return f"{round(value):,}"

    return f"{value:,.{places}f}"


def describe_metric(name: str, label: str, unit: str, places: int, baselines: dict) -> str | None:
    """One line about one metric: today's reading, the normal, and where it sits."""
    metrics = baselines.get("metrics", {})
    summary = metrics.get(name)

    if summary is None:
        return None

    latest = summary.get("latest_value")

    if latest is None:
        return None

    unit_text = f" {unit}" if unit and not unit.startswith("/") else unit
    line = f"- {label}: {format_number(latest, places)}{unit_text}"

    window = summary.get("window_30")

    if window is not None:
        mean = format_number(window.get("mean"), places)
        deviation = format_number(window.get("standard_deviation"), places)
        line = f"{line} (30-day normal {mean}{unit_text}, give or take {deviation})"

        position = summary.get("position_vs_30")

        if position in ("above", "below"):
            line = f"{line} [{position} normal]"
        elif position == "typical":
            line = f"{line} [typical]"
    else:
        line = f"{line} (not enough history for a 30-day normal yet)"

    return line


def describe_energy(days: list[dict]) -> list[str]:
    """Intake against burn over the recent days, and how complete the record is."""
    lines: list[str] = []

    both_known = []

    for one_day in days:
        intake = one_day.get("intake")
        burned = one_day.get("energy", {}).get("total_kilocalories")

        if intake is not None and burned is not None:
            both_known.append(
                {
                    "day": one_day["day"],
                    "balance": intake["kilocalories"] - burned,
                    "source": intake["source"],
                }
            )

    if not both_known:
        return ["- energy balance: not enough recorded to say"]

    recent = both_known[-RECENT_DAYS:]
    total = sum(one["balance"] for one in recent)
    average = total / len(recent)

    assumed = sum(1 for one in recent if one["source"] == "carried")

    lines.append(
        f"- energy balance, last {len(recent)} days with both sides: "
        f"{format_number(average)} kcal per day on average"
    )

    if assumed:
        # The model must know how much of this is assumption, because the honest reading
        # of a mostly-assumed balance is "we do not really know yet".
        lines.append(
            f"- of those {len(recent)} days, {assumed} had intake ASSUMED "
            "(carried forward from an earlier day, not recorded)"
        )

    return lines


def describe_weight(days: list[dict], baselines: dict) -> list[str]:
    """What the scale did, and how often it was used."""
    weighings = [one for one in days if one.get("weight") is not None]

    if not weighings:
        return ["- weight: no weigh-ins recorded"]

    latest = weighings[-1]["weight"]["kilograms"]
    lines = [f"- weight: {format_number(latest, 1)} kg on {weighings[-1]['day']}"]

    if len(weighings) > 1:
        first = weighings[0]["weight"]["kilograms"]
        change = latest - first
        lines.append(
            f"- weight change across the span: {format_number(change, 1)} kg "
            f"over {len(weighings)} weigh-ins between {weighings[0]['day']} and {weighings[-1]['day']}"
        )

    lines.append(
        f"- weigh-in consistency: {len(weighings)} mornings recorded out of {len(days)} days"
    )

    return lines


def describe_training(days: list[dict]) -> list[str]:
    """How much was done, counted rather than judged."""
    workouts = []

    for one_day in days:
        for activity in one_day.get("activities", []):
            workouts.append(activity)

    if not workouts:
        return ["- training: no workouts recorded in the span"]

    recent_days = days[-RECENT_DAYS:]
    recent_count = sum(len(one.get("activities", [])) for one in recent_days)

    kinds: dict[str, int] = {}

    for activity in workouts:
        kind = activity.get("type_key") or "unknown"
        kinds[kind] = kinds.get(kind, 0) + 1

    described = ", ".join(f"{count} {kind.replace('_', ' ')}" for kind, count in sorted(kinds.items()))

    return [
        f"- training: {len(workouts)} sessions across the span ({described})",
        f"- training in the last {len(recent_days)} days: {recent_count} sessions",
    ]


def build(payload: dict[str, Any]) -> str:
    """The whole fact sheet, as plain text.

    Plain text rather than JSON on purpose. The model reads it either way, and text is
    what a person can read in a log when they want to know exactly what was sent.
    """
    days = payload.get("days", [])
    baselines = payload.get("baselines") or {}

    if not days:
        return "No data yet."

    lines = [
        "FACT SHEET",
        f"Span: {payload.get('first_day')} to {payload.get('last_day')} ({len(days)} days).",
    ]

    as_of = baselines.get("as_of")

    if as_of:
        lines.append(f"Most recent day with watch data: {as_of}.")

    lines.append("")
    lines.append("Latest readings against your own 30-day normals:")

    for name, label, unit, places in METRIC_LABELS:
        line = describe_metric(name, label, unit, places, baselines)

        if line is not None:
            lines.append(line)

    lines.append("")
    lines.append("Energy:")
    lines.extend(describe_energy(days))

    lines.append("")
    lines.append("Body:")
    lines.extend(describe_weight(days, baselines))

    lines.append("")
    lines.append("Training:")
    lines.extend(describe_training(days))

    target = payload.get("macro_target")

    if target is not None:
        lines.append("")
        lines.append(
            f"Stated daily target: {format_number(target['kilocalories'])} kcal, "
            f"{format_number(target['protein_grams'])} g protein "
            f"(goal: {target.get('goal', 'unstated')})."
        )

    return "\n".join(lines)


def numbers_in(text: str) -> set[str]:
    """Every number that appears in a piece of text, as written.

    Used on both the fact sheet and the model's reply, so that the reply's numbers can be
    checked against the sheet's. Comparing the written forms rather than parsed values is
    deliberate: it is the string a person reads that has to be justified, and it means a
    model writing "107.3" when the sheet says "107" is caught rather than quietly allowed.
    """
    import re

    found = set()

    # Numbers with optional thousands separators and an optional decimal part. The minus
    # sign is included because a balance can legitimately be negative.
    for match in re.finditer(r"-?\d[\d,]*(?:\.\d+)?", text):
        found.add(match.group(0))

    return found
