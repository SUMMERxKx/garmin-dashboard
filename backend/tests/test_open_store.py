"""Tests for the one environment variable that decides where the data lives.

Small surface, high stakes. If this picks the wrong store, an import writes a month of
days into the wrong place and nothing says so until much later -- which is exactly the
kind of mistake that is cheap to prevent and expensive to find.
"""

from __future__ import annotations

import pytest

from backend.store import database
from backend.store import dynamo
from backend.store import open_store


def test_no_variable_means_the_local_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(open_store.TABLE_NAME_VARIABLE, raising=False)

    assert open_store.table_name_from_environment() is None

    opened = open_store.open_store()

    assert isinstance(opened, database.Database)

    opened.close()


def test_a_table_name_means_dynamodb(monkeypatch: pytest.MonkeyPatch) -> None:
    """Constructing the store must not call AWS, or every test would need credentials."""
    monkeypatch.setenv(open_store.TABLE_NAME_VARIABLE, "SomeTable")

    opened = open_store.open_store()

    assert isinstance(opened, dynamo.DynamoStore)
    assert opened.table_name == "SomeTable"


def test_an_empty_variable_counts_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """`export GARMIN_DASHBOARD_TABLE=` is how people turn things off.

    Treating it as a table literally named "" would produce a baffling error from AWS
    rather than the local behaviour that was obviously intended.
    """
    monkeypatch.setenv(open_store.TABLE_NAME_VARIABLE, "")

    assert open_store.table_name_from_environment() is None

    opened = open_store.open_store()

    assert isinstance(opened, database.Database)

    opened.close()


def test_surrounding_space_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """A name pasted out of the deploy output often brings a trailing newline with it."""
    monkeypatch.setenv(open_store.TABLE_NAME_VARIABLE, "  SomeTable\n")

    assert open_store.table_name_from_environment() == "SomeTable"


def test_the_description_says_which_store_and_where(monkeypatch: pytest.MonkeyPatch) -> None:
    """Printed by the commands, because running an import against the wrong store is
    invisible until much later."""
    monkeypatch.delenv(open_store.TABLE_NAME_VARIABLE, raising=False)

    assert "SQLite" in open_store.describe_store()

    monkeypatch.setenv(open_store.TABLE_NAME_VARIABLE, "SomeTable")

    assert "DynamoDB" in open_store.describe_store()
    assert "SomeTable" in open_store.describe_store()


def test_both_stores_satisfy_the_protocol() -> None:
    """The five methods, spelled once in `Store` and checked here against both.

    A method added to one store and forgotten on the other is the failure this catches,
    and it would otherwise only appear the first time that code path ran in AWS.
    """
    for one_class in (database.Database, dynamo.DynamoStore):
        for method_name in ("close", "save", "load", "load_by_prefix", "load_by_range", "delete"):
            assert hasattr(one_class, method_name), f"{one_class.__name__} has no {method_name}"
