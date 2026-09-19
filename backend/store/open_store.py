"""Which store the app is talking to, decided in exactly one place.

There are two implementations -- SQLite on this machine, DynamoDB in AWS -- and one
environment variable chooses between them:

    GARMIN_DASHBOARD_TABLE set    ->  DynamoDB, that table
    not set                       ->  SQLite, the local file

That is the entire difference. No code changes, no configuration file, no flag threaded
through a dozen functions. It works because both classes offer the same five methods with
the same arguments, and because the same test suite is run against both.

Why a Protocol rather than a base class
---------------------------------------
`Store` below is a `typing.Protocol`: a description of the shape a store has to have,
which the type checker enforces and which neither class has to inherit from or even know
about. If it had been a base class, both would have to import it and subclass it, and
adding a third store later -- or writing a fake one in a test -- would mean editing it.
The protocol just describes; the classes are free.

At runtime this changes nothing at all. Python never checks, and both classes would work
just as well without it. It exists so that a reader, and the type checker, can see what
the two have in common in one place.
"""

from __future__ import annotations

import os
from typing import Any
from typing import Protocol

from backend.store import database
from backend.store import dynamo

#: The environment variable that chooses the store. Named here rather than spelled out at
#: each call site, so the name cannot drift between the code and the documentation.
TABLE_NAME_VARIABLE = "GARMIN_DASHBOARD_TABLE"

#: Which AWS region the table lives in, when one is not already set in the environment.
#: Montreal: the health data stays in Canada, and it is the closest region to Vancouver.
DEFAULT_REGION_VARIABLE = "AWS_REGION"
DEFAULT_REGION = "ca-central-1"


class Store(Protocol):
    """What every store can do. Both implementations satisfy this."""

    def close(self) -> None: ...

    def save(self, partition_key: str, sort_key: str, body: dict[str, Any]) -> None: ...

    def load(self, partition_key: str, sort_key: str) -> dict[str, Any] | None: ...

    def load_by_prefix(
        self,
        partition_key: str,
        sort_key_prefix: str,
    ) -> list[tuple[str, dict[str, Any]]]: ...

    def load_by_range(
        self,
        partition_key: str,
        lowest_sort_key: str,
        highest_sort_key: str,
    ) -> list[tuple[str, dict[str, Any]]]: ...

    def delete(self, partition_key: str, sort_key: str) -> None: ...


def table_name_from_environment() -> str | None:
    """The configured table name, or None when nothing is set.

    An empty string counts as unset. Exporting a variable to the empty value is a common
    way to try to turn something off, and treating it as a table named "" would produce a
    baffling error from AWS rather than the local behaviour that was clearly intended.
    """
    name = os.environ.get(TABLE_NAME_VARIABLE, "")

    if name.strip() == "":
        return None

    return name.strip()


def open_store() -> Store:
    """Open whichever store this machine is configured for.

    Every command and every endpoint calls this rather than naming a class, which is what
    makes the switch a single environment variable instead of a code change.
    """
    table_name = table_name_from_environment()

    if table_name is None:
        return database.Database()

    region_name = os.environ.get(DEFAULT_REGION_VARIABLE, DEFAULT_REGION)

    return dynamo.DynamoStore(table_name=table_name, region_name=region_name)


def describe_store() -> str:
    """One line saying where the data is coming from, for a command to print.

    Worth showing. Running an import and having it silently go to the wrong place --
    local when you meant AWS, or the reverse -- is the kind of mistake that is invisible
    until much later.
    """
    table_name = table_name_from_environment()

    if table_name is None:
        return f"local SQLite file ({database.DEFAULT_DATABASE_PATH})"

    return f"DynamoDB table {table_name}"
