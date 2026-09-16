"""Tests for the API.

The endpoints are thin: they call the same modules the command line does. What is worth
pinning is the seam -- that a write is checked before it is stored, that a refusal comes
back as the right status with a readable sentence, and that a write shows up in the very
next read with the label the intake rule gives it.

Every test runs against an in-memory database, swapped in through FastAPI's dependency
override. Nothing here touches `dashboard.db`.
"""

from __future__ import annotations

import datetime

import pytest
from fastapi import testclient

from backend.api import payload
from backend.api import server
from backend.store import database


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    """A test client whose every request sees the same in-memory database."""
    memory = database.Database(":memory:")

    def use_the_test_database():
        yield memory

    server.app.dependency_overrides[server.open_database] = use_the_test_database

    # The fixed facts are read from files on this machine (a scan, a food library).
    # A test must not depend on what happens to be on disk.
    monkeypatch.setattr(payload, "read_fixed_facts", lambda as_of: payload.FixedFacts())

    with testclient.TestClient(server.app) as test_client:
        yield test_client

    server.app.dependency_overrides.clear()
    memory.close()


TODAY = datetime.date.today()
YESTERDAY = TODAY - datetime.timedelta(days=1)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def test_an_empty_database_is_still_a_valid_payload(client) -> None:
    response = client.get("/api/days")

    assert response.status_code == 200
    assert response.json()["days"] == []
    assert response.json()["baselines"]["as_of"] is None


# ---------------------------------------------------------------------------
# Intake
# ---------------------------------------------------------------------------


def test_a_typed_total_is_stored_and_read_back_as_manual(client) -> None:
    response = client.post(
        "/api/intake", json={"day": YESTERDAY.isoformat(), "kilocalories": 2100}
    )

    assert response.status_code == 201
    assert response.json()["replaced"] is None

    days = client.get("/api/days").json()["days"]

    assert days[-1]["day"] == YESTERDAY.isoformat()
    assert days[-1]["intake"] == {
        "kilocalories": 2100.0,
        "source": "manual",
        "from_day": YESTERDAY.isoformat(),
    }


def test_a_day_after_a_typed_total_inherits_it_labelled_as_carried(client) -> None:
    """The write API and the carry rule meet here: type yesterday, and today is assumed."""
    client.post("/api/intake", json={"day": YESTERDAY.isoformat(), "kilocalories": 2100})
    # A weigh-in today creates today as a day, with nothing typed for it.
    client.post("/api/weigh", json={"day": TODAY.isoformat(), "kilograms": 78.0})

    days = client.get("/api/days").json()["days"]

    assert days[-1]["day"] == TODAY.isoformat()
    assert days[-1]["intake"]["source"] == "carried"
    assert days[-1]["intake"]["from_day"] == YESTERDAY.isoformat()


def test_a_second_total_for_the_same_day_replaces_the_first_and_says_so(client) -> None:
    client.post("/api/intake", json={"day": YESTERDAY.isoformat(), "kilocalories": 2100})
    response = client.post(
        "/api/intake", json={"day": YESTERDAY.isoformat(), "kilocalories": 2300}
    )

    assert response.json()["replaced"] == 2100.0


def test_an_unbelievable_total_is_refused_with_a_sentence(client) -> None:
    response = client.post("/api/intake", json={"day": YESTERDAY.isoformat(), "kilocalories": 210})

    assert response.status_code == 422
    assert "drop a digit" in response.json()["detail"]


def test_a_malformed_request_is_refused_before_any_code_runs(client) -> None:
    """FastAPI's own check: a missing field never reaches the endpoint."""
    response = client.post("/api/intake", json={"day": YESTERDAY.isoformat()})

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Weigh-ins
# ---------------------------------------------------------------------------


def test_a_weigh_in_is_stored_with_its_body_fat(client) -> None:
    response = client.post(
        "/api/weigh",
        json={"day": TODAY.isoformat(), "kilograms": 78.0, "fat_percent": 18.5},
    )

    assert response.status_code == 201

    days = client.get("/api/days").json()["days"]

    assert days[-1]["weight"]["kilograms"] == 78.0
    assert days[-1]["weight"]["fat_percent"] == 18.5
    assert days[-1]["weight"]["source"] == "manual"


def test_an_impossible_weight_is_refused(client) -> None:
    """A slipped decimal point (784 for 78.4) is beyond any human weight, so it never stores."""
    response = client.post("/api/weigh", json={"day": TODAY.isoformat(), "kilograms": 784})

    assert response.status_code == 422
    assert "pounds" in response.json()["detail"]


def test_a_surprising_jump_is_refused_until_forced(client) -> None:
    """The API must not be an easier way to record a typo than the terminal is."""
    client.post("/api/weigh", json={"day": YESTERDAY.isoformat(), "kilograms": 78.0})

    refused = client.post("/api/weigh", json={"day": TODAY.isoformat(), "kilograms": 84.0})

    assert refused.status_code == 409
    assert "away from your last weigh-in" in refused.json()["detail"]

    forced = client.post(
        "/api/weigh", json={"day": TODAY.isoformat(), "kilograms": 84.0, "force": True}
    )

    assert forced.status_code == 201
    assert forced.json()["change_since_previous"] == {"kilograms": 6.0, "days": 1}
