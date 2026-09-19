"""Copy what is on this laptop into AWS: the database into DynamoDB, the archive into S3.

Run it with `--dry-run` first. That reads everything, counts it, prints what would move,
and writes nothing at all.

    .venv/bin/python -m scripts.move_to_aws --dry-run
    .venv/bin/python -m scripts.move_to_aws

It reads the table and bucket names from the environment, so nothing about your account
is written down in this repository:

    export GARMIN_DASHBOARD_TABLE=HealthDashboardData-HealthData...
    export GARMIN_DASHBOARD_BUCKET=healthdashboarddata-rawresponses...

Safe to run more than once
--------------------------
Both halves replace rather than append. A record written twice to DynamoDB leaves one
copy, because the key is the address; a file uploaded twice to S3 overwrites itself, for
the same reason. So an interrupted run is fixed by running it again, and there is no
half-migrated state to reason about. That property is not an accident -- it is the same
idempotence the local `import` command has, and for the same reason.

What it does NOT do
-------------------
It does not delete anything locally, and it does not touch the local database at all. The
laptop keeps working exactly as before; this only adds a copy in AWS. Deleting the local
copy, if you ever want to, is a separate and deliberate act.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import boto3

from backend.garmin import raw_files
from backend.store import database
from backend.store import dynamo
from backend.store import keys
from backend.store import open_store

#: Where the raw responses land in the bucket. The same `dt=YYYY-MM-DD` layout the local
#: archive uses, because a partitioned prefix is what lets a query engine read one day
#: without listing the whole bucket -- and because keeping the two identical means a file
#: can be matched to its local original by eye.
BUCKET_PREFIX = "garmin"

#: The environment variable naming the bucket. The table's variable is the one the app
#: already uses, so it is imported rather than restated.
BUCKET_NAME_VARIABLE = "GARMIN_DASHBOARD_BUCKET"

#: How many records to report progress after. Purely cosmetic: without it a few thousand
#: records look like a hung program.
REPORT_EVERY = 100


def describe_record(sort_key: str) -> str:
    """Which kind of thing a sort key names, for the summary.

    Read from the key rather than from the record, because the key IS the type in a
    single-table design -- that is the whole point of the scheme.
    """
    if sort_key.endswith("SNAPSHOT"):
        return "Garmin day"

    if sort_key.endswith("WEIGHT"):
        return "weigh-in"

    if sort_key.endswith("INTAKE"):
        return "typed intake"

    if keys.FOOD_MARKER in sort_key:
        return "food entry"

    return "other"


def read_everything_local(
    local_database: database.Database,
    user_id: str = keys.DEFAULT_USER_ID,
) -> list[tuple[str, dict]]:
    """Every record for this user, in key order.

    Read with one very wide range rather than by walking days, because the store offers
    exactly that and it is the same call the dashboard already makes.
    """
    return local_database.load_by_range(
        partition_key=keys.user_partition(user_id),
        lowest_sort_key="",
        highest_sort_key="￿",
    )


def move_the_database(
    records: list[tuple[str, dict]],
    table_name: str,
    dry_run: bool,
    user_id: str = keys.DEFAULT_USER_ID,
) -> None:
    """Write every local record into the DynamoDB table."""
    counts_by_kind: dict[str, int] = {}

    for sort_key, _record in records:
        kind = describe_record(sort_key)
        counts_by_kind[kind] = counts_by_kind.get(kind, 0) + 1

    print(f"  {len(records)} record(s) in the local database:")

    for kind in sorted(counts_by_kind):
        print(f"    {counts_by_kind[kind]:>5}  {kind}")

    if dry_run:
        print(f"  would write them to {table_name}")
        return

    remote = dynamo.DynamoStore(table_name=table_name)
    partition = keys.user_partition(user_id)

    for number, (sort_key, record) in enumerate(records, start=1):
        remote.save(partition_key=partition, sort_key=sort_key, body=record)

        if number % REPORT_EVERY == 0:
            print(f"    {number} of {len(records)}…")

    print(f"  wrote {len(records)} record(s) to {table_name}")


def find_raw_files(raw_directory: Path) -> list[Path]:
    """Every saved Garmin response on disk, oldest day first."""
    if not raw_directory.exists():
        return []

    found = []

    for day_folder in sorted(raw_directory.iterdir()):
        if not day_folder.is_dir():
            continue

        if not day_folder.name.startswith("dt="):
            continue

        for one_file in sorted(day_folder.iterdir()):
            if one_file.is_file() and one_file.suffix == ".json":
                found.append(one_file)

    return found


def key_for_raw_file(one_file: Path, raw_directory: Path) -> str:
    """Where one local file goes in the bucket.

    `fixtures/raw/garmin/dt=2026-09-14/sleep.json` becomes
    `garmin/dt=2026-09-14/sleep.json` -- the same shape, under one prefix.
    """
    relative = one_file.relative_to(raw_directory)

    return f"{BUCKET_PREFIX}/{relative.as_posix()}"


def move_the_archive(raw_files_found: list[Path], bucket_name: str, dry_run: bool) -> None:
    """Upload every saved Garmin response to the bucket."""
    total_bytes = 0

    for one_file in raw_files_found:
        total_bytes = total_bytes + one_file.stat().st_size

    megabytes = total_bytes / (1024 * 1024)

    print(f"  {len(raw_files_found)} raw response file(s), {megabytes:.1f} MB")

    if not raw_files_found:
        return

    print(f"    first: {key_for_raw_file(raw_files_found[0], raw_files.DEFAULT_RAW_DIRECTORY)}")
    print(f"    last:  {key_for_raw_file(raw_files_found[-1], raw_files.DEFAULT_RAW_DIRECTORY)}")

    if dry_run:
        print(f"  would upload them to s3://{bucket_name}/{BUCKET_PREFIX}/")
        return

    s3 = boto3.client("s3")

    for number, one_file in enumerate(raw_files_found, start=1):
        s3.upload_file(
            Filename=str(one_file),
            Bucket=bucket_name,
            Key=key_for_raw_file(one_file, raw_files.DEFAULT_RAW_DIRECTORY),
            # The bucket already refuses unencrypted storage and plain HTTP; this says
            # the content type plainly so anything reading it later does not guess.
            ExtraArgs={"ContentType": "application/json"},
        )

        if number % REPORT_EVERY == 0:
            print(f"    {number} of {len(raw_files_found)}…")

    print(f"  uploaded {len(raw_files_found)} file(s) to s3://{bucket_name}/{BUCKET_PREFIX}/")


def main() -> int:
    """Entry point. 0 if everything moved, 1 if something was not configured."""
    parser = argparse.ArgumentParser(
        description="Copy the local database and raw archive into AWS."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="read and report, but write nothing",
    )
    parser.add_argument(
        "--table",
        default=os.environ.get(open_store.TABLE_NAME_VARIABLE),
        help=f"DynamoDB table name (default: ${open_store.TABLE_NAME_VARIABLE})",
    )
    parser.add_argument(
        "--bucket",
        default=os.environ.get(BUCKET_NAME_VARIABLE),
        help=f"S3 bucket name (default: ${BUCKET_NAME_VARIABLE})",
    )
    arguments = parser.parse_args()

    if arguments.table is None or arguments.bucket is None:
        print("Both a table and a bucket are needed. Either pass them:")
        print("    --table NAME --bucket NAME")
        print("or set them in the environment:")
        print(f"    export {open_store.TABLE_NAME_VARIABLE}=...")
        print(f"    export {BUCKET_NAME_VARIABLE}=...")
        print()
        print("Both names are printed by `cdk deploy`.")
        return 1

    print()

    if arguments.dry_run:
        print("DRY RUN — nothing will be written.")
        print()

    # Read the LOCAL database explicitly rather than through `open_store`. If
    # GARMIN_DASHBOARD_TABLE is already exported -- and it has to be, for the table name
    # default above to work -- then `open_store` would hand back the remote store and
    # this would copy AWS onto itself.
    local_database = database.Database()

    print(f"FROM  {local_database.database_path}")
    print(f"  AND {raw_files.DEFAULT_RAW_DIRECTORY}")
    print(f"TO    {arguments.table}")
    print(f"  AND s3://{arguments.bucket}/")
    print()

    print("Database:")
    records = read_everything_local(local_database)
    move_the_database(records, arguments.table, arguments.dry_run)
    local_database.close()

    print()
    print("Raw archive:")
    raw_files_found = find_raw_files(raw_files.DEFAULT_RAW_DIRECTORY)
    move_the_archive(raw_files_found, arguments.bucket, arguments.dry_run)

    print()

    if arguments.dry_run:
        print("Nothing was written. Run again without --dry-run to do it.")
    else:
        print("Done. The local copies are untouched.")
        print(f"Point the app at AWS with: export {open_store.TABLE_NAME_VARIABLE}={arguments.table}")

    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
