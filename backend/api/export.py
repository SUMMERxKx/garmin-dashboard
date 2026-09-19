"""Write the dashboard's JSON to a file.

This was how the dashboard was fed before there was a server: run this, and Vite serves
the file out of `dashboard/public/data/`. It still works, and it is still useful -- it
is the fallback the browser reads when the API is not running, and it is a file you can
open and read.

Everything that decides WHAT goes in the payload lives in `payload.py`. This file only
picks the span, reads the clock, and writes the result to disk.

Run it from the project root:

    .venv/bin/python -m backend.api.export
    .venv/bin/python -m backend.api.export --days 90 --out dashboard/public/data/days.json
"""

from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path
from typing import Any

from backend import paths
from backend.api import payload
from backend.store import open_store

#: Where the web app expects to find it. A file under the dashboard's own `public`
#: folder is served at `/data/days.json`, which is what the browser fetches when the
#: API at `/api/days` does not answer.
DEFAULT_OUTPUT_PATH = paths.PROJECT_ROOT / "dashboard" / "public" / "data" / "days.json"

#: How many days to export when nothing is asked for. Wide enough to cover every day
#: fetched so far, so the default is "everything" rather than a window that quietly
#: starts dropping history.
DEFAULT_DAYS = 400


def write_payload(whole_payload: dict[str, Any], output_path: Path) -> None:
    """Write the JSON, creating the folder if it is not there yet.

    `indent=2` because this file gets read by a human more often than it gets parsed
    while we are still building. It costs a few kilobytes and saves squinting.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as open_file:
        json.dump(whole_payload, open_file, indent=2)
        # A trailing newline, so the file plays nicely with git and with `tail`.
        open_file.write("\n")


def main() -> int:
    """Entry point. 0 if the export worked, 1 if there was nothing to export."""
    parser = argparse.ArgumentParser(
        description="Export stored days as the JSON the dashboard reads."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help=f"how many days back to export (default: {DEFAULT_DAYS})",
    )
    parser.add_argument(
        "--out",
        default=str(DEFAULT_OUTPUT_PATH),
        help="where to write the file",
    )
    arguments = parser.parse_args()

    last_day = datetime.date.today()
    first_day = last_day - datetime.timedelta(days=arguments.days - 1)

    open_database = open_store.open_store()

    # The clock and the disk are read here, at the edge, and passed inwards -- so every
    # function that builds the payload stays testable with a fixed time and no files.
    whole_payload = payload.build_payload(
        open_database,
        first_day,
        last_day,
        datetime.datetime.now(),
        payload.read_fixed_facts(last_day),
    )

    open_database.close()

    if not whole_payload["days"]:
        print("Nothing to export: no stored days in that span.")
        print("Fetch and import some first.")
        return 1

    output_path = Path(arguments.out)
    write_payload(whole_payload, output_path)

    size_in_kilobytes = output_path.stat().st_size / 1024

    print(f"Wrote {len(whole_payload['days'])} day(s) to {output_path}")
    print(f"  {whole_payload['first_day']} .. {whole_payload['last_day']}")
    print(f"  {size_in_kilobytes:.1f} KB, schema version {whole_payload['schema_version']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
