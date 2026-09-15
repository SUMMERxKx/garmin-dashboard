"""Turning values into the text that appears on screen.

Every function here answers one question: how should this number look? None of them
decide WHAT to show, only how -- which is why they take plain values and return plain
strings, and why none of them print anything themselves.

Kept apart from the commands so that a column of figures lines up the same way in the
day view, the span table and the weight list, without three files each having their own
idea of how wide a label is.
"""

from __future__ import annotations

#: What to print where a value is missing. Every field in a snapshot can genuinely be
#: absent -- a watch left on the charger is a normal Tuesday -- so this is a normal
#: sight rather than an error. Two dashes read as "nothing here" at a glance, where the
#: word `None` reads as something having gone wrong.
NOTHING_TO_SHOW = "--"

#: How wide the label column is, so the numbers line up underneath each other. Columns
#: that line up are much faster to scan than columns that do not.
LABEL_WIDTH = 20

#: Metres in a kilometre. Named rather than written as a bare 1000 inside a sum.
METRES_PER_KILOMETRE = 1000.0

#: Minutes in an hour, for the same reason.
MINUTES_PER_HOUR = 60

#: Seconds in a minute, used to turn a fractional pace into mm:ss.
SECONDS_PER_MINUTE = 60

def show_number(
    value: float | int | None,
    unit: str = "",
    decimal_places: int = 0,
) -> str:
    """Format one number for the screen, or `--` if we have no reading for it.

    Every field goes through here rather than each print line deciding for itself what
    to do about a missing value. One place to decide means one place to change.
    """
    if value is None:
        return NOTHING_TO_SHOW

    formatted_number = f"{value:,.{decimal_places}f}"

    if unit == "":
        return formatted_number

    return f"{formatted_number} {unit}"

def show_duration(minutes: float | None) -> str:
    """Format a number of minutes as hours and minutes, e.g. `5 h 36 m`.

    Sleep is stored in minutes because that is the smallest unit anybody cares about,
    but 336 minutes is not a quantity a person feels. `5 h 36 m` is.
    """
    if minutes is None:
        return NOTHING_TO_SHOW

    whole_minutes = round(minutes)
    hours = whole_minutes // MINUTES_PER_HOUR
    minutes_left_over = whole_minutes % MINUTES_PER_HOUR

    if hours == 0:
        return f"{minutes_left_over} m"

    return f"{hours} h {minutes_left_over:02d} m"

def show_signed_number(value: int | None, sign: str) -> str:
    """Format a number with a leading + or -, or `--` if we have no reading.

    Body battery is reported as two separate amounts, one gained and one spent, and the
    signs are what make that readable at a glance. A missing reading must not pick up a
    sign, because `+--` looks like a bug rather than an absence.
    """
    if value is None:
        return NOTHING_TO_SHOW

    return f"{sign}{show_number(value)}"

def to_kilometres(metres: float | None) -> float | None:
    """Convert metres to kilometres, passing None straight through.

    Garmin reports every distance in metres. Nobody reads a run in metres, so the
    division happens here, once, rather than at each of the three places below that
    print a distance.
    """
    if metres is None:
        return None

    return metres / METRES_PER_KILOMETRE

def show_pace(duration_minutes: float | None, distance_metres: float | None) -> str:
    """Minutes per kilometre, the unit a run is actually read in.

    Garmin reports speed in metres per second, which nobody thinks in. This is derived
    from duration and distance rather than read from `averageSpeed`, so that the pace on
    screen always agrees with the two numbers printed directly above it.
    """
    if duration_minutes is None:
        return NOTHING_TO_SHOW

    if distance_metres is None:
        return NOTHING_TO_SHOW

    # A lifting session records no distance. Dividing by it would crash, and a pace for
    # a session that did not move anywhere would be meaningless even if it did not.
    if distance_metres <= 0:
        return NOTHING_TO_SHOW

    # Safe to divide by: the check above has already ruled out None and zero.
    kilometres = to_kilometres(distance_metres)
    minutes_per_kilometre = duration_minutes / kilometres

    whole_minutes = int(minutes_per_kilometre)
    seconds = round((minutes_per_kilometre - whole_minutes) * SECONDS_PER_MINUTE)

    return f"{whole_minutes}:{seconds:02d} /km"

def print_line(label: str, value: str, label_width: int = LABEL_WIDTH) -> None:
    """Print one indented `label    value` row, with the labels all the same width.

    `label_width` is adjustable because the provenance listing uses the raw field names,
    which are longer than the labels on the main view. Without it the longest names ran
    straight into their values with no gap.
    """
    print(f"  {label.ljust(label_width)}{value}")

def print_heading(heading: str) -> None:
    """Print a section heading with a blank line above it."""
    print()
    print(heading)
