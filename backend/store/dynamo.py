"""The same store, on DynamoDB instead of SQLite.

This class and `database.Database` offer exactly the same five operations, take the same
arguments and return the same shapes. That is the whole point, and it is why the local
store was written to look like DynamoDB from the first day rather than like a normal
relational schema: moving to AWS is a swap, not a rewrite.

    save            put one record, replacing whatever was at that key
    load            one record, or None
    load_by_prefix  every record whose sort key starts with something
    load_by_range   every record with a sort key between two values
    delete          remove one record

Why the record is stored as a JSON string
-----------------------------------------
A DynamoDB item could hold the record's fields as real attributes. This stores the whole
thing as text in a single `body` attribute instead, exactly as the SQLite table does.

Two reasons, and the second is the one that matters:

1. **DynamoDB has no float.** Its number type maps to Python's `Decimal`, so writing
   `hrv_last_night: 104.0` and reading it back gives you `Decimal('104.0')` -- which is
   not equal to the float in any comparison, breaks `statistics.mean`, and cannot be
   passed to `json.dumps`. Every caller would need to know. Storing text sidesteps the
   problem entirely rather than pushing it outward.

2. **Nothing ever searches inside the body.** That is already true of the SQLite store,
   and deliberately so -- `database.py` explains that DynamoDB cannot search inside an
   item cheaply either, and a local convenience that does not survive the move is a trap.
   Since no query ever looks in there, there is nothing to gain by making it queryable.

Pagination is not optional
--------------------------
DynamoDB returns at most 1 MB per query and hands back a cursor if there is more. A month
of days fits comfortably in one page today, which is exactly why forgetting to follow the
cursor would work perfectly until the year the history got long enough -- and then lose
the oldest days silently, with no error. Both readers below follow it.
"""

from __future__ import annotations

import json
from typing import Any

import boto3

#: Sorts after every character that can appear in one of our keys. Used to turn a prefix
#: into a range, because DynamoDB has `begins_with` for a prefix but the range reader
#: needs two bounds.
HIGHEST_CHARACTER = "￿"


class DynamoStore:
    """One DynamoDB table, addressed by the key scheme in `keys.py`."""

    def __init__(self, table_name: str, region_name: str | None = None) -> None:
        """Open a handle on the table.

        Nothing is fetched here and no connection is made -- boto3 builds a client lazily
        and reuses it. That matters in Lambda: a handle built once outside the request is
        reused by every later invocation of the same container, which removes the setup
        cost from all but the first call.
        """
        self.table_name = table_name

        session = boto3.session.Session(region_name=region_name)
        self.table = session.resource("dynamodb").Table(table_name)

    def close(self) -> None:
        """Nothing to close. Here so callers can treat both stores identically.

        The SQLite store holds a file handle and must be closed. This one holds an HTTPS
        client that manages itself. Rather than make every caller ask which kind it has,
        this exists and does nothing.
        """
        return None

    def save(self, partition_key: str, sort_key: str, body: dict[str, Any]) -> None:
        """Write one record, replacing whatever was at that key.

        `put_item` replaces by default, which is the same behaviour as the SQLite store's
        `INSERT OR REPLACE` -- and it is what makes re-running an import safe.
        """
        self.table.put_item(
            Item={
                "pk": partition_key,
                "sk": sort_key,
                "body": json.dumps(body),
            }
        )

    def load(self, partition_key: str, sort_key: str) -> dict[str, Any] | None:
        """Read one record, or None if there is nothing at that key."""
        response = self.table.get_item(Key={"pk": partition_key, "sk": sort_key})

        item = response.get("Item")

        if item is None:
            return None

        return json.loads(item["body"])

    def load_by_prefix(
        self,
        partition_key: str,
        sort_key_prefix: str,
    ) -> list[tuple[str, dict[str, Any]]]:
        """Every record whose sort key starts with this prefix, in key order.

        Expressed as a range rather than with `begins_with`, so there is one query path
        below instead of two. A prefix covers exactly the keys between the prefix itself
        and the prefix followed by the highest character there is.
        """
        return self.load_by_range(
            partition_key=partition_key,
            lowest_sort_key=sort_key_prefix,
            highest_sort_key=sort_key_prefix + HIGHEST_CHARACTER,
        )

    def load_by_range(
        self,
        partition_key: str,
        lowest_sort_key: str,
        highest_sort_key: str,
    ) -> list[tuple[str, dict[str, Any]]]:
        """Every record with a sort key between these two, both ends included.

        This is the read everything else is built on: a month of days, or ninety, comes
        back in one query because sort keys are stored in order and our dates are written
        so that sorting them as text sorts them as dates.
        """
        found: list[tuple[str, dict[str, Any]]] = []

        # The cursor DynamoDB hands back when a page was not the whole answer. None on
        # the first time round, which is why the loop is written as a while-True with the
        # exit at the bottom rather than as a condition at the top.
        start_key = None

        while True:
            arguments: dict[str, Any] = {
                "KeyConditionExpression": (
                    "pk = :partition AND sk BETWEEN :lowest AND :highest"
                ),
                "ExpressionAttributeValues": {
                    ":partition": partition_key,
                    ":lowest": lowest_sort_key,
                    ":highest": highest_sort_key,
                },
            }

            if start_key is not None:
                arguments["ExclusiveStartKey"] = start_key

            response = self.table.query(**arguments)

            for item in response.get("Items", []):
                found.append((item["sk"], json.loads(item["body"])))

            start_key = response.get("LastEvaluatedKey")

            if start_key is None:
                break

        return found

    def delete(self, partition_key: str, sort_key: str) -> None:
        """Remove one record. Deleting something that is not there is not an error."""
        self.table.delete_item(Key={"pk": partition_key, "sk": sort_key})
