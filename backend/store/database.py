"""The local database: one SQLite file, shaped like the DynamoDB table it will become.

This looks nothing like a normal relational schema, and that is deliberate. There is
ONE table with three columns: a partition key, a sort key, and the record itself as
JSON text. No columns per field, no joins, no foreign keys.

Why do that to a perfectly good relational database
---------------------------------------------------
Because it is not pretending to be a relational database. It is standing in for
DynamoDB, which works exactly this way, and copying that shape now has two payoffs:

  1. Moving to AWS later swaps this class for a DynamoDB one and changes nothing else.
     The keys are already right, the access patterns are already right.
  2. The access patterns get tested now, while changing them is still cheap. If some
     screen turns out to need a lookup this shape cannot do, far better to discover
     that today than after the data is in the cloud.

The three operations below -- fetch one, fetch by prefix, fetch by range -- are exactly
what DynamoDB offers. Nothing here searches inside the JSON body, because DynamoDB
cannot do that cheaply either, and a local convenience that does not survive the move
is a trap rather than a feature.

`sqlite3` ships with Python, so this adds no dependency and there is no ORM to learn.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

#: One table, three columns. The primary key is the PAIR (pk, sk), which is what makes
#: a save either insert a new record or replace whatever was at that key -- the same
#: behaviour as a DynamoDB PutItem.
SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    pk   TEXT NOT NULL,
    sk   TEXT NOT NULL,
    body TEXT NOT NULL,
    PRIMARY KEY (pk, sk)
);
"""

THIS_FILE = Path(__file__).resolve()
STORE_PACKAGE_DIRECTORY = THIS_FILE.parent
BACKEND_DIRECTORY = STORE_PACKAGE_DIRECTORY.parent
PROJECT_ROOT = BACKEND_DIRECTORY.parent

#: Where the database file lives by default. It holds real health data, so `*.db` is in
#: .gitignore and it must never be committed.
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "dashboard.db"


class Database:
    """One SQLite file, addressed by the key scheme in `keys.py`."""

    def __init__(self, database_path: str | Path = DEFAULT_DATABASE_PATH) -> None:
        """Open the database, creating the file and the table if they are not there.

        Passing ":memory:" gives a database that lives only as long as the program
        does, which is what tests want: no file to clean up, and no chance of a test
        writing over real data.
        """
        self.database_path = str(database_path)

        self.connection = sqlite3.connect(self.database_path)

        # Hand back rows that can be read by column name -- row["body"] rather than
        # row[2]. Position-based access silently reads the wrong column the moment
        # anybody adds one.
        self.connection.row_factory = sqlite3.Row

        self.connection.execute(SCHEMA)
        self.connection.commit()

    def close(self) -> None:
        """Close the connection. Safe to call more than once."""
        self.connection.close()

    def save(self, partition_key: str, sort_key: str, body: dict[str, Any]) -> None:
        """Write one record, replacing whatever was at that key.

        Replacing rather than failing is what makes re-running an import safe: fetching
        the same day twice writes the same record twice and leaves one copy. An
        operation that can be repeated without changing the result beyond the first
        time is called *idempotent*, and it is worth having here because the scheduled
        fetch on AWS will re-fetch today and yesterday every few hours on purpose.
        """
        body_as_text = json.dumps(body)

        self.connection.execute(
            "INSERT OR REPLACE INTO records (pk, sk, body) VALUES (?, ?, ?)",
            (partition_key, sort_key, body_as_text),
        )
        self.connection.commit()

    def load(self, partition_key: str, sort_key: str) -> dict[str, Any] | None:
        """Read one record, or None if there is nothing at that key.

        None rather than an exception, for the same reason the rest of the project
        prefers it: a day that has not been imported yet is an ordinary situation, not
        a fault.
        """
        cursor = self.connection.execute(
            "SELECT body FROM records WHERE pk = ? AND sk = ?",
            (partition_key, sort_key),
        )

        row = cursor.fetchone()

        if row is None:
            return None

        return json.loads(row["body"])

    def load_by_prefix(
        self,
        partition_key: str,
        sort_key_prefix: str,
    ) -> list[tuple[str, dict[str, Any]]]:
        """Every record whose sort key starts with this prefix, in key order.

        Returns pairs of (sort key, record), because the caller usually needs to know
        WHICH record each one is -- the key is the only thing that says whether a
        record is a snapshot, a weigh-in or a food entry.

        The `?` placeholders matter: the prefix is passed as a value rather than glued
        into the SQL text. Building SQL by string concatenation is how SQL injection
        happens, and the habit is worth keeping even in a single-user local file.
        """
        cursor = self.connection.execute(
            "SELECT sk, body FROM records"
            " WHERE pk = ? AND sk >= ? AND sk < ?"
            " ORDER BY sk",
            (partition_key, sort_key_prefix, sort_key_prefix + "￿"),
        )

        return self._rows_to_pairs(cursor.fetchall())

    def load_by_range(
        self,
        partition_key: str,
        lowest_sort_key: str,
        highest_sort_key: str,
    ) -> list[tuple[str, dict[str, Any]]]:
        """Every record with a sort key between these two, both ends included.

        This is the one baselines are built on: ninety days of history in a single
        lookup, because dates written as YYYY-MM-DD sort as text in the same order they
        sort as dates.
        """
        cursor = self.connection.execute(
            "SELECT sk, body FROM records"
            " WHERE pk = ? AND sk >= ? AND sk <= ?"
            " ORDER BY sk",
            (partition_key, lowest_sort_key, highest_sort_key),
        )

        return self._rows_to_pairs(cursor.fetchall())

    def delete(self, partition_key: str, sort_key: str) -> None:
        """Remove one record. Deleting something that is not there is not an error."""
        self.connection.execute(
            "DELETE FROM records WHERE pk = ? AND sk = ?",
            (partition_key, sort_key),
        )
        self.connection.commit()

    def _rows_to_pairs(self, rows: list[sqlite3.Row]) -> list[tuple[str, dict[str, Any]]]:
        """Turn database rows into (sort key, record) pairs.

        The leading underscore is Python's convention for "this is internal to the
        class". It is not enforced -- nothing stops you calling it -- it is a note to
        the next reader that it is not part of what this class offers.
        """
        pairs = []

        for one_row in rows:
            pairs.append((one_row["sk"], json.loads(one_row["body"])))

        return pairs
