"""Fetch yesterday from Garmin, on a schedule, with nobody watching.

This is the piece that makes the dashboard run without the laptop open. EventBridge calls
it a few times a day; it does what `run_fetch` plus `import` do on a laptop, and writes
the results where AWS can serve them.

    Parameter Store  ──► token bundle ──► /tmp
                                           │  garminconnect logs in, no password
                                           ▼
                                    17 Garmin endpoints
                                           │
                        ┌──────────────────┴──────────────────┐
                        ▼                                     ▼
              S3, raw and untouched                  DynamoDB, interpreted
              garmin/dt=YYYY-MM-DD/*.json            DAY#YYYY-MM-DD#SNAPSHOT

The archive is written BEFORE anything interprets it, exactly as on the laptop. That is
the property the whole project rests on: get the interpretation wrong and it is a replay,
not lost history.

The password problem, and how it is avoided
-------------------------------------------
Logging in to Garmin needs an email, a password and a two-factor code -- a human. The
TOKEN BUNDLE that login produces needs none of those, and `garminconnect` refreshes it
on its own as long as it is used regularly.

So the password never comes to AWS. You log in once on the laptop, the bundle is copied
into Parameter Store as an encrypted value, and this function reads it, uses it, and
writes the refreshed version back. If Garmin ever forces a real login again, the fetch
fails loudly rather than silently serving stale numbers -- see `describe_outcome`.

Why it fetches a few days rather than only yesterday
----------------------------------------------------
A watch uploads when your phone next syncs it, which might be hours later, and a day can
be incomplete for a while after midnight. Re-fetching the last few days every time costs
almost nothing and repairs any day that was thin when it was first seen. Writing the same
day twice leaves one copy, because the key is the address -- the same idempotence the
local `import` has.
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
from pathlib import Path
from typing import Any

import boto3

#: Where the token bundle lives, encrypted, in Parameter Store.
TOKEN_PARAMETER_NAME = "/garmin-dashboard/garmin-tokens"

#: Lambda's only writable directory.
WRITABLE_DIRECTORY = Path("/tmp")

#: Where the token bundle is unpacked to, and where raw responses are staged before they
#: go to S3. Both under /tmp, both thrown away when the container is recycled.
TOKEN_DIRECTORY = WRITABLE_DIRECTORY / "garmin_tokens"
RAW_DIRECTORY = WRITABLE_DIRECTORY / "raw"

#: How many days back to fetch on each run, ending with yesterday. Three covers a weekend
#: of a phone not syncing without making the run slow.
DEFAULT_DAYS_BACK = 3

#: The prefix raw responses land under in the bucket. The same `dt=YYYY-MM-DD` layout the
#: laptop uses, so a file can be matched to its local original by eye.
BUCKET_PREFIX = "garmin"


def read_token_bundle(client: Any) -> None:
    """Copy the token bundle out of Parameter Store and onto the local disk.

    `garminconnect` wants a directory of files, not a string, so the stored JSON is
    written back out into the shape the library expects.
    """
    TOKEN_DIRECTORY.mkdir(parents=True, exist_ok=True)

    answer = client.get_parameter(Name=TOKEN_PARAMETER_NAME, WithDecryption=True)
    stored = json.loads(answer["Parameter"]["Value"])

    for file_name, contents in stored.items():
        (TOKEN_DIRECTORY / file_name).write_text(contents, encoding="utf-8")

    print(f"token bundle restored: {len(stored)} file(s)")


def save_token_bundle(client: Any) -> None:
    """Write the refreshed bundle back, so the next run starts from the newer one.

    Skipped silently if nothing is there to save. A failure here must not fail the run:
    the data was already fetched and stored by this point, and the worst case is that the
    next run starts from a slightly older bundle, which still works.
    """
    if not TOKEN_DIRECTORY.exists():
        return

    bundle = {}

    for one_file in TOKEN_DIRECTORY.iterdir():
        if one_file.is_file():
            bundle[one_file.name] = one_file.read_text(encoding="utf-8")

    if not bundle:
        return

    client.put_parameter(
        Name=TOKEN_PARAMETER_NAME,
        Value=json.dumps(bundle),
        Type="SecureString",
        Overwrite=True,
    )

    print(f"token bundle saved back: {len(bundle)} file(s)")


def days_to_fetch(today: datetime.date, how_many: int) -> list[datetime.date]:
    """The days this run should ask for, oldest first, ending with YESTERDAY.

    Never today. The day is not over, the watch may not have synced since this morning,
    and calories and steps are still climbing -- the same reason every other part of this
    project defaults to yesterday.
    """
    yesterday = today - datetime.timedelta(days=1)

    return [yesterday - datetime.timedelta(days=offset) for offset in reversed(range(how_many))]


def upload_one_day(s3_client: Any, bucket_name: str, day: datetime.date) -> int:
    """Copy one day's staged files into the bucket. Returns how many went."""
    folder = RAW_DIRECTORY / f"dt={day.isoformat()}"

    if not folder.exists():
        return 0

    how_many = 0

    for one_file in sorted(folder.iterdir()):
        if not one_file.is_file():
            continue

        s3_client.upload_file(
            Filename=str(one_file),
            Bucket=bucket_name,
            Key=f"{BUCKET_PREFIX}/dt={day.isoformat()}/{one_file.name}",
            ExtraArgs={"ContentType": "application/json"},
        )

        how_many = how_many + 1

    return how_many


def describe_outcome(fetched: list[str], failed: list[str]) -> dict[str, Any]:
    """What the run did, as the JSON the invocation returns.

    Returned rather than only logged so that a failure is visible in the scheduler's own
    metrics and in an alarm, instead of only to somebody reading CloudWatch by hand.
    """
    return {
        "fetched": fetched,
        "failed": failed,
        "ok": len(failed) == 0,
    }


def handler(event: dict | None = None, context: Any = None) -> dict[str, Any]:
    """The function EventBridge calls.

    Imports of the project's own modules happen inside here rather than at the top of the
    file. `garminconnect` pulls in a compiled HTTP library, and doing that work lazily
    keeps it out of any code path that only wants to read a constant from this module.
    """
    from backend.garmin import fetch
    from backend.garmin import normalize
    from backend.garmin import raw_files
    from backend.store import day_store
    from backend.store import open_store

    # Point the login code at /tmp before importing it, because it reads this when the
    # module is first loaded.
    os.environ["GARMIN_TOKEN_DIRECTORY"] = str(TOKEN_DIRECTORY)

    from backend.garmin import login

    login.TOKEN_DIRECTORY = TOKEN_DIRECTORY

    bucket_name = os.environ["GARMIN_DASHBOARD_BUCKET"]
    how_many_days = int(os.environ.get("GARMIN_FETCH_DAYS", DEFAULT_DAYS_BACK))

    ssm_client = boto3.client("ssm")
    s3_client = boto3.client("s3")

    # A warm container keeps /tmp from the previous run. Clearing it means a file that
    # failed to write last time cannot be mistaken for this run's data.
    if RAW_DIRECTORY.exists():
        shutil.rmtree(RAW_DIRECTORY)

    RAW_DIRECTORY.mkdir(parents=True, exist_ok=True)

    read_token_bundle(ssm_client)

    garmin_client = login.log_in()

    store = open_store.open_store()

    fetched: list[str] = []
    failed: list[str] = []

    for day in days_to_fetch(datetime.date.today(), how_many_days):
        try:
            result = fetch.fetch_one_day(garmin_client, day)

            # The archive first, always, before anything interprets it.
            raw_files.save_whole_day(result, raw_directory=RAW_DIRECTORY)
            uploaded = upload_one_day(s3_client, bucket_name, day)

            saved = raw_files.load_whole_day(day, raw_directory=RAW_DIRECTORY)
            snapshot = normalize.normalize_day(saved, day)
            day_store.save_snapshot(store, snapshot)

            found = snapshot.how_many_fields_found()
            print(f"{day.isoformat()}: {found} fields, {uploaded} file(s) to S3")
            fetched.append(day.isoformat())
        except Exception as problem:
            # One bad day must not lose the others. Garmin occasionally fails a single
            # endpoint or a single date, and the next run will pick that day up again.
            print(f"{day.isoformat()}: FAILED {type(problem).__name__}: {problem}")
            failed.append(day.isoformat())

    store.close()

    try:
        save_token_bundle(ssm_client)
    except Exception as problem:
        # Deliberately not fatal. The data is already in, and the only cost is that the
        # next run starts from a slightly older bundle.
        print(f"could not save the token bundle back: {type(problem).__name__}: {problem}")

    outcome = describe_outcome(fetched, failed)
    print(json.dumps(outcome))

    if failed and not fetched:
        # Every day failed: almost certainly the token bundle has expired and Garmin
        # wants a real login. Raise, so the invocation is recorded as an error and an
        # alarm can notice, rather than reporting success while the dashboard goes stale.
        raise RuntimeError(
            f"every day failed ({', '.join(failed)}). "
            "The Garmin token bundle may have expired -- log in on the laptop and "
            "re-run scripts/upload_garmin_token.py."
        )

    return outcome
