"""Reading a value out of deeply nested JSON without crashing.

Garmin's responses nest. The numeric sleep score, for example, is not at the top level
next to something obvious. It is here:

    dailySleepDTO.sleepScores.overall.value

Written out by hand in Python, reaching that looks like:

    response["dailySleepDTO"]["sleepScores"]["overall"]["value"]

which is four chances to raise a KeyError. And a missing key is not an error here: a
watch left on the charger overnight is a normal Tuesday, not a bug. We want the answer
"we do not know" rather than a crash.

So this module lets you write the path as a single piece of text:

    read_path(response, "dailySleepDTO.sleepScores.overall.value")

and get either the value or None. Nothing in here ever raises because data is missing.

Why None, and not zero
----------------------
None means "we have no reading". Zero means "we measured, and it was zero". Those are
completely different facts and collapsing them would quietly corrupt every average
computed later: a week with two missing days would be averaged as though you had slept
zero hours on those days.
"""

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Sequence
from typing import Any


def split_path_into_steps(path: str) -> list[str | int]:
    """Turn a text path into a list of steps to follow, one at a time.

    Examples:
        "totalSteps"                -> ["totalSteps"]
        "hrvSummary.lastNightAvg"   -> ["hrvSummary", "lastNightAvg"]
        "dateWeightList[0].weight"  -> ["dateWeightList", 0, "weight"]

    A step that is text means "look up this key in a dictionary".
    A step that is a number means "take this position from a list".

    Splitting the path and following it are kept as two separate functions on purpose.
    Each one is then simple enough to check by eye, and this one can be tested on its
    own without any data to read from.
    """
    steps: list[str | int] = []

    # Parts of a path are separated by dots, so start there.
    for piece in path.split("."):
        # A piece may carry one or more list positions on the end, like
        # "dateWeightList[0]" or even "matrix[0][1]". Peel them off one at a time,
        # shortening `text_left_to_read` as we go. It starts as the whole piece, and
        # what survives the loop is whatever was not a bracket.
        text_left_to_read = piece

        while "[" in text_left_to_read:
            # `partition` splits on the first bracket and gives back three parts:
            # what came before it, the bracket itself, and what came after.
            name_before_bracket, _, after_the_bracket = text_left_to_read.partition("[")

            # There may be no name at all, if this piece was nothing but an index.
            if name_before_bracket:
                steps.append(name_before_bracket)

            index_as_text, _, text_after_the_index = after_the_bracket.partition("]")
            steps.append(int(index_as_text))

            # Loop again in case another index follows.
            text_left_to_read = text_after_the_index

        # Whatever is left over is an ordinary key name.
        if text_left_to_read:
            steps.append(text_left_to_read)

    return steps


def read_path(data: Any, path: str) -> Any:
    """Follow `path` into `data` and return what is there, or None.

    Returns None if anything at all goes wrong along the way: a key that is not there,
    a list position past the end, or a path that tries to go deeper than the data
    actually goes. Nothing raises.
    """
    current_value = data

    for step in split_path_into_steps(path):
        # If we have already run out of data, there is nowhere further to go.
        if current_value is None:
            return None

        if isinstance(step, str):
            # We are being asked for a dictionary key, so we need a dictionary.
            # `Mapping` is the general name for "behaves like a dictionary".
            if not isinstance(current_value, Mapping):
                return None

            # `.get()` returns None for a missing key instead of raising, which is
            # exactly the behaviour we want.
            current_value = current_value.get(step)

        else:
            # We are being asked for a list position, so we need a list.
            if not isinstance(current_value, Sequence):
                return None

            # A string is technically a sequence in Python, so "abc"[0] would give
            # "a". That is never what a path like "weights[0]" means, so strings and
            # bytes are excluded deliberately rather than by accident.
            if isinstance(current_value, str | bytes):
                return None

            if step >= len(current_value):
                return None

            current_value = current_value[step]

    return current_value


def as_optional_float(value: Any) -> float | None:
    """Turn a value into a float, or None if it cannot sensibly become one.

    Garmin sometimes sends a number as text ("45.0" rather than 45.0), so we convert
    rather than assume. Anything that will not convert becomes None, which keeps a
    surprising value from travelling onward pretending to be a measurement.

    Booleans are rejected on purpose: in Python, True would happily convert to 1.0, and
    a flag silently becoming a measurement is exactly the kind of bug that is invisible
    later.
    """
    if value is None:
        return None

    if isinstance(value, bool):
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        # TypeError: the value was something like a list or a dictionary.
        # ValueError: it was text that is not a number, such as "unknown".
        return None


def as_optional_integer(value: Any) -> int | None:
    """Turn a value into a whole number, or None if it cannot sensibly become one.

    Goes through `as_optional_float` first so that text like "1234" and a float like
    1234.0 both work. Anything after the decimal point is dropped, which is what we
    want for counts such as steps.
    """
    value_as_float = as_optional_float(value)

    if value_as_float is None:
        return None

    return int(value_as_float)


def read_float(data: Any, path: str) -> float | None:
    """Read a path and convert whatever is there to a float, or None."""
    return as_optional_float(read_path(data, path))


def read_integer(data: Any, path: str) -> int | None:
    """Read a path and convert whatever is there to a whole number, or None."""
    return as_optional_integer(read_path(data, path))


def as_optional_text(value: Any) -> str | None:
    """Turn a value into text, or None if it is not text worth keeping.

    Unlike the number conversions above, this one refuses to convert. A number, a list
    or a dictionary arriving where a name was expected means our path is wrong, and
    turning 348.0 into the string "348.0" would hide that instead of showing it.

    Empty text and whitespace become None as well, because Garmin fills some optional
    names with "" rather than leaving them out, and an empty string is not a reading.
    """
    if value is None:
        return None

    if not isinstance(value, str):
        return None

    text_without_padding = value.strip()

    if text_without_padding == "":
        return None

    return text_without_padding


def read_text(data: Any, path: str) -> str | None:
    """Read a path and return the text that is there, or None."""
    return as_optional_text(read_path(data, path))
