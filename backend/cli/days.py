"""Working out which day a command means, and which days exist at all.

Three small functions that every other command module needs, which is exactly why they
live here rather than in whichever one happened to need them first.

The defaults differ on purpose, and the difference is the whole point:

    work_out_which_day_to_show      defaults to YESTERDAY
    work_out_day_for_logging        defaults to TODAY

You VIEW a finished day -- today is still running, the watch may not have synced, and
calories and steps are still climbing. You LOG food as you eat it, which is necessarily
today. Getting these the same way round would make one of the two commands wrong every
single time it was used.
"""

from __future__ import annotations

import datetime

from backend.garmin import raw_files


def days_we_have_saved() -> list[datetime.date]:
    """Every day that has a folder of saved responses on disk, oldest first.

    Used only to give a helpful message when the day asked for is not there. Folders
    are named `dt=YYYY-MM-DD`, which is the same layout the S3 bucket will use later.
    """
    if not raw_files.DEFAULT_RAW_DIRECTORY.exists():
        return []

    days = []

    for one_folder in raw_files.DEFAULT_RAW_DIRECTORY.iterdir():
        if not one_folder.is_dir():
            continue

        if not one_folder.name.startswith("dt="):
            continue

        date_text = one_folder.name.removeprefix("dt=")

        try:
            days.append(datetime.date.fromisoformat(date_text))
        except ValueError:
            # A folder whose name is not a date is not ours. Skip it rather than
            # crashing the whole command over it.
            continue

    return sorted(days)


def work_out_which_day_to_show(date_text: str | None) -> datetime.date:
    """Turn the `--date` option into a date.

    The default is YESTERDAY, matching `run_fetch` for the same reason: today is always
    incomplete. The day is not over, the watch may not have synced since this morning,
    and calories and steps are still climbing. Showing a half-finished day next to a
    baseline built from finished ones invites a wrong conclusion every single time.
    """
    if date_text is None:
        return datetime.date.today() - datetime.timedelta(days=1)

    # Raises ValueError on anything that is not a date; main() turns that into a
    # readable sentence rather than a stack trace.
    return datetime.date.fromisoformat(date_text)


def work_out_day_for_logging(date_text: str | None) -> datetime.date | None:
    """Which day a logging command writes to. Defaults to today; None means bad input."""
    if date_text is None:
        return datetime.date.today()

    try:
        return datetime.date.fromisoformat(date_text)
    except ValueError:
        print(f"'{date_text}' is not a date. Use the form 2026-09-12.")
        return None
