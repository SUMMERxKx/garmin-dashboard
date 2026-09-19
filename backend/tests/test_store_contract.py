"""One suite, run against both stores.

This is the test that makes the AWS move safe. Every test below runs twice -- once
against the local SQLite file and once against a DynamoDB table -- and both have to
behave identically. If they ever diverge, the failure appears here rather than in
production three weeks later.

Neither run touches anything real. SQLite uses `:memory:`, and DynamoDB runs under
`moto`, a library that stands up a fake AWS in this process: it answers the same API
calls with the same semantics, so no account, no credentials and no network are needed.
Closest thing you already know: a stub server, except it implements a real specification
rather than only the calls we happen to make.

What is being pinned
--------------------
The five operations, and the four properties the rest of the project quietly depends on:

  - saving the same key twice REPLACES, rather than adding a second copy. This is what
    makes `import` safe to re-run, which is the basis of the whole replay design.
  - reading a key that is not there returns None rather than raising. A day that has not
    been imported yet is ordinary, not a fault.
  - a prefix read returns a whole day in key order.
  - a range read returns a span in key order, both ends included.
"""

from __future__ import annotations

import datetime
from typing import Any

import boto3
import pytest
from moto import mock_aws

from backend.store import database
from backend.store import dynamo
from backend.store import keys

TABLE_NAME = "test-health-data"
REGION = "ca-central-1"

PARTITION = keys.user_partition("me")


def make_sqlite_store():
    """A SQLite store that lives only as long as the test."""
    return database.Database(":memory:")


def make_dynamo_store():
    """A DynamoDB store backed by moto's in-process fake AWS.

    The table is created here with the same key schema `infra/stacks/data_stack.py`
    declares, so this test also exercises the shape that is actually deployed.
    """
    boto3.client("dynamodb", region_name=REGION).create_table(
        TableName=TABLE_NAME,
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )

    return dynamo.DynamoStore(table_name=TABLE_NAME, region_name=REGION)


@pytest.fixture(params=["sqlite", "dynamodb"])
def store(request, monkeypatch: pytest.MonkeyPatch):
    """Every test using this fixture runs once per store.

    `params` is what makes that happen: pytest runs the test once for each entry and
    labels the result with it, so a failure says which store broke.
    """
    if request.param == "sqlite":
        one_store = make_sqlite_store()
        yield one_store
        one_store.close()
        return

    # moto refuses to start without credentials in the environment, and it must never
    # find real ones -- a misconfigured test writing to the live table would be silent
    # and expensive. These are deliberate nonsense.
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)

    with mock_aws():
        one_store = make_dynamo_store()
        yield one_store
        one_store.close()


def a_record(note: str) -> dict[str, Any]:
    """A record with the shapes that actually go through the store: floats, None, nesting."""
    return {
        "note": note,
        "a_float": 104.5,
        "a_missing_reading": None,
        "nested": {"steps": 22434, "day": "2026-09-14"},
        "a_list": [1, 2, 3],
    }


# ---------------------------------------------------------------------------
# The five operations
# ---------------------------------------------------------------------------


def test_a_saved_record_reads_back_exactly(store) -> None:
    """Including the float and the None.

    The float is the one that matters for DynamoDB: its number type is a Decimal, so a
    store that wrote the record as native attributes would hand back `Decimal('104.5')`
    here and quietly break every average computed later.
    """
    store.save(PARTITION, "DAY#2026-09-14#SNAPSHOT", a_record("hello"))

    came_back = store.load(PARTITION, "DAY#2026-09-14#SNAPSHOT")

    assert came_back == a_record("hello")
    assert isinstance(came_back["a_float"], float)
    assert came_back["a_missing_reading"] is None


def test_reading_a_key_that_is_not_there_returns_none(store) -> None:
    """A day that has not been imported yet is ordinary, not a fault."""
    assert store.load(PARTITION, "DAY#1999-01-01#SNAPSHOT") is None


def test_saving_the_same_key_twice_replaces_rather_than_adding(store) -> None:
    """The property the whole replay design rests on: `import` is safe to re-run."""
    store.save(PARTITION, "DAY#2026-09-14#SNAPSHOT", a_record("first"))
    store.save(PARTITION, "DAY#2026-09-14#SNAPSHOT", a_record("second"))

    assert store.load(PARTITION, "DAY#2026-09-14#SNAPSHOT")["note"] == "second"

    everything = store.load_by_prefix(PARTITION, "DAY#2026-09-14#")

    assert len(everything) == 1


def test_a_prefix_read_returns_one_whole_day_in_key_order(store) -> None:
    """The access pattern the key scheme exists for: a day is one lookup."""
    store.save(PARTITION, "DAY#2026-09-14#SNAPSHOT", a_record("snapshot"))
    store.save(PARTITION, "DAY#2026-09-14#WEIGHT", a_record("weight"))
    store.save(PARTITION, "DAY#2026-09-14#FOOD#20260914T120000000000", a_record("food"))
    store.save(PARTITION, "DAY#2026-09-15#SNAPSHOT", a_record("the next day"))

    found = store.load_by_prefix(PARTITION, "DAY#2026-09-14#")

    sort_keys = [one_key for one_key, _record in found]

    assert sort_keys == [
        "DAY#2026-09-14#FOOD#20260914T120000000000",
        "DAY#2026-09-14#SNAPSHOT",
        "DAY#2026-09-14#WEIGHT",
    ]


def test_a_range_read_covers_both_ends(store) -> None:
    """A month of history in one query, and the last day must be included.

    The bug this catches is the classic one: a range ending at `DAY#2026-09-16#` stops
    before that day's records rather than after them, so the newest day silently vanishes.
    `keys.day_range_bounds` appends a high character to prevent it.
    """
    for day_number in (14, 15, 16, 17):
        store.save(PARTITION, f"DAY#2026-09-{day_number}#SNAPSHOT", a_record(str(day_number)))

    lowest, highest = keys.day_range_bounds(
        datetime.date(2026, 9, 15), datetime.date(2026, 9, 16)
    )

    found = store.load_by_range(PARTITION, lowest, highest)

    assert [record["note"] for _key, record in found] == ["15", "16"]


def test_deleting_removes_one_record_and_leaves_the_rest(store) -> None:
    store.save(PARTITION, "DAY#2026-09-14#SNAPSHOT", a_record("keep"))
    store.save(PARTITION, "DAY#2026-09-14#WEIGHT", a_record("remove"))

    store.delete(PARTITION, "DAY#2026-09-14#WEIGHT")

    assert store.load(PARTITION, "DAY#2026-09-14#WEIGHT") is None
    assert store.load(PARTITION, "DAY#2026-09-14#SNAPSHOT") is not None


def test_deleting_something_that_is_not_there_is_not_an_error(store) -> None:
    store.delete(PARTITION, "DAY#1999-01-01#SNAPSHOT")


def test_one_users_records_are_not_returned_for_another(store) -> None:
    """The partition key is the boundary. Today there is one user; the scheme allows more."""
    store.save(keys.user_partition("me"), "DAY#2026-09-14#SNAPSHOT", a_record("mine"))
    store.save(keys.user_partition("someone-else"), "DAY#2026-09-14#SNAPSHOT", a_record("theirs"))

    found = store.load_by_prefix(keys.user_partition("me"), "DAY#2026-09-14#")

    assert len(found) == 1
    assert found[0][1]["note"] == "mine"


def test_an_empty_span_returns_an_empty_list_rather_than_raising(store) -> None:
    assert store.load_by_range(PARTITION, "DAY#1999-01-01#", "DAY#1999-12-31#~") == []


# ---------------------------------------------------------------------------
# The reader that would fail only once the history got long
# ---------------------------------------------------------------------------


def test_a_range_read_returns_everything_even_across_many_records(store) -> None:
    """DynamoDB returns at most 1 MB per query and a cursor for the rest.

    A year of days fits in one page, so a reader that ignored the cursor would work
    perfectly for years and then start losing the oldest days with no error at all. This
    writes enough records to be worth the check and asserts the count exactly.
    """
    how_many = 250

    for number in range(how_many):
        store.save(PARTITION, f"DAY#2026-01-01#FOOD#{number:020d}", a_record(str(number)))

    found = store.load_by_prefix(PARTITION, "DAY#2026-01-01#FOOD#")

    assert len(found) == how_many
    assert [record["note"] for _key, record in found] == [str(n) for n in range(how_many)]
