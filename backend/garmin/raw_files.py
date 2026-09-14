"""Saving Garmin's responses to disk, exactly as they arrived.

This is the step that happens BEFORE anything tries to understand the data, and that
order is the whole point of the module.

Why save the raw response at all
--------------------------------
Reading a Garmin response and pulling useful numbers out of it means guessing which
field means what. Those guesses are sometimes wrong, and sometimes Garmin renames a
field and quietly breaks one.

If the only thing we kept was our interpretation, a mistake like that would mean the
data is gone: we would have to go back and ask Garmin again. But Garmin's API is
unofficial and does not keep your history forever, so "ask again" may not be available.

Keeping the original response turns that problem into an inconvenience. Fix the
interpreting code, run it over the files we already have, and the corrected history
appears. That is usually called a *replay*, and it is only possible if the raw data was
never thrown away.

These files contain real health data, so `fixtures/raw/` is in .gitignore and must
never be committed.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

from backend.garmin import fetch

# ---------------------------------------------------------------------------
# Where the files go
# ---------------------------------------------------------------------------
#
# Same walk up from this file to the project root as in login.py:
#   backend/garmin/raw_files.py -> backend/garmin -> backend -> the project root

THIS_FILE = Path(__file__).resolve()
GARMIN_PACKAGE_DIRECTORY = THIS_FILE.parent
BACKEND_DIRECTORY = GARMIN_PACKAGE_DIRECTORY.parent
PROJECT_ROOT = BACKEND_DIRECTORY.parent

#: The root of the saved responses. One folder per day lives underneath it.
DEFAULT_RAW_DIRECTORY = PROJECT_ROOT / "fixtures" / "raw" / "garmin"

#: The summary file written alongside each day's responses. The leading underscore
#: marks it as ours rather than something Garmin sent, and sorts it to the top of a
#: directory listing.
SUMMARY_FILE_NAME = "_fetch_summary.json"


def folder_for_day(
    day: datetime.date,
    raw_directory: Path = DEFAULT_RAW_DIRECTORY,
) -> Path:
    """The folder one day's responses belong in.

    The folder is named "dt=2026-09-10" rather than just "2026-09-10". The "dt=" prefix
    is a widespread convention for date-partitioned data, and tools that read data
    lakes recognise it without being told. It also keeps the folders sorted by date,
    because the date is written biggest-unit-first.

    `raw_directory` is a parameter with a default rather than a hard-coded path, so a
    test can point this at a temporary folder and not write into the real one.
    """
    folder_name = f"dt={day.isoformat()}"

    return raw_directory / folder_name


def save_one_response(
    day: datetime.date,
    endpoint_name: str,
    response: Any,
    raw_directory: Path = DEFAULT_RAW_DIRECTORY,
) -> Path:
    """Write a single endpoint's response to its own file, and return the path.

    Saving even an empty response is deliberate. "This endpoint reliably gives us
    nothing" is a real finding about the watch, and a missing file cannot tell the
    difference between that and a call we never made.
    """
    day_folder = folder_for_day(day, raw_directory)

    # `parents=True` creates any missing folder above this one too. `exist_ok=True`
    # means running the same fetch twice is fine rather than an error.
    day_folder.mkdir(parents=True, exist_ok=True)

    file_path = day_folder / f"{endpoint_name}.json"

    # `indent=2` pretty-prints the file across multiple lines. It makes the file
    # bigger, and that is worth it: these files get read by humans trying to work out
    # what a field means, and a single long line is unreadable.
    #
    # `default=str` tells json how to handle a value it does not know how to write --
    # a date object, for example. Without it, one odd value raises and we lose the
    # whole response. With it, that value is written as text and everything else
    # survives.
    file_contents = json.dumps(response, indent=2, default=str)

    file_path.write_text(file_contents, encoding="utf-8")

    return file_path


def save_fetch_summary(
    result: fetch.DayFetchResult,
    raw_directory: Path = DEFAULT_RAW_DIRECTORY,
) -> Path:
    """Write a small file recording how the fetch went, next to the responses.

    The responses alone cannot tell you that `hrv` failed, because a failed call
    produces no file. This records that, along with the error, so a gap in the data can
    be explained months later without re-running anything.
    """
    day_folder = folder_for_day(result.day, raw_directory)
    day_folder.mkdir(parents=True, exist_ok=True)

    summary = {
        "day": result.day.isoformat(),
        "endpoints_that_worked": result.names_that_worked(),
        "endpoints_that_failed": result.names_that_failed(),
        "errors": result.errors,
        "every_tier_one_endpoint_worked": result.every_tier_one_endpoint_worked(),
    }

    file_path = day_folder / SUMMARY_FILE_NAME
    file_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    return file_path


def save_whole_day(
    result: fetch.DayFetchResult,
    raw_directory: Path = DEFAULT_RAW_DIRECTORY,
) -> Path:
    """Save every response from one fetch, plus the summary. Returns the day's folder."""
    for endpoint_name, response in result.responses.items():
        save_one_response(result.day, endpoint_name, response, raw_directory)

    save_fetch_summary(result, raw_directory)

    return folder_for_day(result.day, raw_directory)


def load_one_response(
    day: datetime.date,
    endpoint_name: str,
    raw_directory: Path = DEFAULT_RAW_DIRECTORY,
) -> Any:
    """Read one saved response back, or None if that file does not exist.

    None means "we have no file for this", which is a normal situation: the call may
    have failed that day. The summary file says which it was.
    """
    file_path = folder_for_day(day, raw_directory) / f"{endpoint_name}.json"

    if not file_path.exists():
        return None

    file_contents = file_path.read_text(encoding="utf-8")

    return json.loads(file_contents)


def load_whole_day(
    day: datetime.date,
    raw_directory: Path = DEFAULT_RAW_DIRECTORY,
) -> dict[str, Any]:
    """Read every saved response for one day, keyed by endpoint name.

    This is the front door of the replay path: interpreting code reads from here rather
    than from the network, so it can be re-run over history as often as we like.
    """
    day_folder = folder_for_day(day, raw_directory)

    if not day_folder.exists():
        return {}

    responses: dict[str, Any] = {}

    for file_path in sorted(day_folder.glob("*.json")):
        # Skip our own summary file. It sits in the same folder but it is not something
        # Garmin sent, so it must not be mistaken for an endpoint response.
        if file_path.name == SUMMARY_FILE_NAME:
            continue

        # `.stem` is the filename without its extension, so "sleep.json" -> "sleep",
        # which is exactly the endpoint name it was saved under.
        endpoint_name = file_path.stem

        responses[endpoint_name] = json.loads(file_path.read_text(encoding="utf-8"))

    return responses
