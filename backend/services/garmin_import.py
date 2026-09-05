"""Import saved Garmin responses into the repository as canonical snapshots.

The Phase 0 probe saved every raw response to `fixtures/raw/garmin/dt=YYYY-MM-DD/`.
This reads those folders, runs each day through the normalizer, and stores the result.

That separation is the point of keeping raw responses in the first place: if the
normalizer is fixed or extended, this can be re-run over the same saved files and every
snapshot is rebuilt. No re-fetching from Garmin, and no data lost to a parser bug.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from backend.adapters import repository as storage
from backend.providers import base as provider_base
from backend.providers import garmin_mapping

THIS_FILE = Path(__file__).resolve()
SERVICES_DIRECTORY = THIS_FILE.parent
BACKEND_DIRECTORY = SERVICES_DIRECTORY.parent
PROJECT_ROOT = BACKEND_DIRECTORY.parent

RAW_FIXTURE_DIRECTORY = PROJECT_ROOT / "fixtures" / "raw" / "garmin"
SAMPLE_FIXTURE_DIRECTORY = PROJECT_ROOT / "fixtures" / "sample"

# Folders are named "dt=2026-09-02".
DAY_FOLDER_PREFIX = "dt="


def day_from_folder_name(folder_name: str) -> date | None:
    """Read the date out of a folder name, or None if it is not one of ours."""
    if not folder_name.startswith(DAY_FOLDER_PREFIX):
        return None

    date_text = folder_name[len(DAY_FOLDER_PREFIX) :]

    try:
        return date.fromisoformat(date_text)
    except ValueError:
        return None


def read_day_folder(folder: Path) -> dict[str, Any]:
    """Load every saved response in one day's folder, keyed by endpoint name.

    The file name is the endpoint name, so `sleep.json` becomes the "sleep" payload.
    """
    payloads: dict[str, Any] = {}

    for response_file in sorted(folder.glob("*.json")):
        endpoint_name = response_file.stem
        payloads[endpoint_name] = json.loads(response_file.read_text(encoding="utf-8"))

    return payloads


def find_day_folders(directory: Path) -> list[tuple[date, Path]]:
    """Every day folder inside a fixture directory, oldest first."""
    if not directory.exists():
        return []

    found: list[tuple[date, Path]] = []

    for candidate in directory.iterdir():
        if not candidate.is_dir():
            continue

        day = day_from_folder_name(candidate.name)
        if day is None:
            continue

        found.append((day, candidate))

    found.sort(key=lambda pair: pair[0])
    return found


def import_day(
    repository: storage.HealthRepository,
    user_id: str,
    day: date,
    folder: Path,
) -> tuple[int, int]:
    """Normalize and store one day. Returns (fields present, fields missing).

    The counts are the field-coverage signal: an endpoint can return a successful
    response with no data in it, so "how many of the essential fields did we actually
    get" is a more useful health check than "did the request succeed".
    """
    payloads = read_day_folder(folder)

    raw = provider_base.RawPayloads(provider="garmin", on=day, payloads=payloads)
    snapshot = garmin_mapping.normalize_day(raw, on=day)

    repository.save_snapshot(user_id, snapshot)

    present, missing = garmin_mapping.coverage(snapshot)
    return len(present), len(missing)


def import_all_days(
    repository: storage.HealthRepository,
    user_id: str,
    *,
    directory: Path | None = None,
) -> list[tuple[date, int, int]]:
    """Import every saved day. Returns one (day, present, missing) row per day.

    Falls back to the committed sample fixtures if the real ones are not there, so this
    works on a fresh checkout where `fixtures/raw/` (gitignored) does not exist.
    """
    if directory is None:
        if find_day_folders(RAW_FIXTURE_DIRECTORY):
            directory = RAW_FIXTURE_DIRECTORY
        else:
            directory = SAMPLE_FIXTURE_DIRECTORY

    results: list[tuple[date, int, int]] = []

    for day, folder in find_day_folders(directory):
        present, missing = import_day(repository, user_id, day, folder)
        results.append((day, present, missing))

    return results
