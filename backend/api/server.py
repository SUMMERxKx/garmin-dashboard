"""The API: the same payload the exporter writes, served over HTTP, plus two writes.

    .venv/bin/uvicorn backend.api.server:app --reload --port 8000

What FastAPI is, if you have not met it
---------------------------------------
A web framework that turns ordinary Python functions into HTTP endpoints. You write a
function, decorate it with the path it answers (`@app.get("/api/days")`), and declare
the request body as a class. FastAPI reads the request, checks it against the class
(wrong type or missing field -> a 422 response with the problem spelled out, before your
code runs), calls the function, and turns the return value into JSON. There is nothing
else to learn for what this file does.

`uvicorn` is the server that actually listens on the port and hands requests to the
app. FastAPI describes the app; uvicorn runs it. The split is standard and you never
think about it after the first day.

Why the browser talks to `/api` and not to port 8000
----------------------------------------------------
Vite's dev server proxies anything under `/api` to this process (see
`dashboard/vite.config.ts`). The browser only ever sees one origin, so there is no
cross-origin setup to get wrong, and the dashboard code has one URL to change when this
moves to AWS.

Reading and writing
-------------------
    GET  /api/days?days=400     the whole payload, exactly as `export.py` writes it
    POST /api/intake            { day, kilocalories, note? }  a typed-in daily total
    POST /api/weigh             { day, kilograms, fat_percent?, force? }  a weigh-in
    POST /api/login             { password }  sets the session cookie
    POST /api/logout            clears it

The writes apply the same checks the command line does, from the same modules, and
answer with the same sentences. A weigh-in that is far from the last one is refused
with 409 until `force` is sent -- the API must not be an easier way to record 173 kg
than the terminal is.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterator
from typing import Any

import fastapi
import pydantic

from backend.api import auth
from backend.api import payload
from backend.body import weight
from backend.food import intake
from backend.store import intake_store
from backend.store import open_store
from backend.store import weight_store

#: The default span, matching the exporter so the two answers are the same.
DEFAULT_DAYS = 400

#: How far back to look for a previous weigh-in when checking a new one. The same six
#: weeks the command line uses, for the same reason: long enough to find one after a
#: holiday, short enough that the comparison still means something.
WEIGH_IN_LOOKBACK_DAYS = 42

app = fastapi.FastAPI(
    title="Garmin Dashboard API",
    description="One span of days, and the two things you type in yourself.",
)


def open_database() -> Iterator[open_store.Store]:
    """Open the store for one request and close it afterwards.

    A *dependency* in FastAPI terms: a function whose result is handed to any endpoint
    that asks for it. The `yield` is what makes the close reliable -- the code after it
    runs once the response has gone out, whether or not the endpoint raised. Tests swap
    this for one that yields an in-memory store, and nothing else has to change.

    Which store it opens is decided by `open_store`, from one environment variable:
    SQLite on this laptop, DynamoDB in AWS. This function does not know which it got, and
    neither does any endpoint below.
    """
    connection = open_store.open_store()

    try:
        yield connection
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


@app.get("/api/days")
def read_days(
    days: int = fastapi.Query(DEFAULT_DAYS, ge=1, le=2000),
    connection: open_store.Store = fastapi.Depends(open_database),
) -> dict[str, Any]:
    """The payload the dashboard draws, for the last `days` days."""
    last_day = datetime.date.today()
    first_day = last_day - datetime.timedelta(days=days - 1)

    return payload.build_payload(
        connection,
        first_day,
        last_day,
        datetime.datetime.now(),
        payload.read_fixed_facts(last_day),
    )


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


class IntakeRequest(pydantic.BaseModel):
    """What the browser sends to record a day's calories."""

    day: datetime.date
    kilocalories: float
    note: str | None = None


@app.post("/api/intake", status_code=201)
def record_intake(
    request: IntakeRequest,
    connection: open_store.Store = fastapi.Depends(open_database),
) -> dict[str, Any]:
    """Record a typed-in total for one day, replacing any earlier one for that day."""
    problem = intake.describe_problem(request.kilocalories)

    if problem is not None:
        # 422 is "I understood the request and it is not acceptable" -- the right code
        # for a number that parsed fine but cannot be a day's eating.
        raise fastapi.HTTPException(status_code=422, detail=problem)

    already_there = intake_store.load_intake(connection, request.day)

    one_intake = intake.ManualIntake(
        day=request.day,
        kilocalories=request.kilocalories,
        # The clock is read here, at the edge, never inside the intake module.
        recorded_at=datetime.datetime.now(),
        note=request.note,
    )

    intake_store.save_intake(connection, one_intake)

    return {
        "day": request.day.isoformat(),
        "kilocalories": request.kilocalories,
        "replaced": None if already_there is None else already_there.kilocalories,
    }


class WeighRequest(pydantic.BaseModel):
    """What the browser sends to record a weigh-in."""

    day: datetime.date
    kilograms: float
    fat_percent: float | None = None

    #: Record it even though it is far from the last weigh-in. Off by default, so the
    #: browser has to ask twice to store a surprising number -- same as `--force`.
    force: bool = False


@app.post("/api/weigh", status_code=201)
def record_weighing(
    request: WeighRequest,
    connection: open_store.Store = fastapi.Depends(open_database),
) -> dict[str, Any]:
    """Record a weigh-in, with the same two checks the command line applies."""
    problem = weight.describe_problem(request.kilograms)

    if problem is not None:
        raise fastapi.HTTPException(status_code=422, detail=problem)

    # Compare against the most recent weigh-in BEFORE this day, which is what makes the
    # pounds-and-decimal-point check possible at all.
    earlier = weight_store.load_weighings_between(
        connection,
        request.day - datetime.timedelta(days=WEIGH_IN_LOOKBACK_DAYS),
        request.day - datetime.timedelta(days=1),
    )

    previous = earlier[-1] if earlier else None
    surprising = weight.describe_jump(previous, request.kilograms)

    if surprising is not None and not request.force:
        # 409 is "conflict": the request is well-formed but disagrees with what is
        # already recorded. The browser shows the sentence and offers to force it.
        raise fastapi.HTTPException(status_code=409, detail=surprising)

    already_there = weight_store.load_weighing(connection, request.day)

    one_weighing = weight.Weighing(
        day=request.day,
        kilograms=request.kilograms,
        recorded_at=datetime.datetime.now(),
        source="manual",
        fat_percent=request.fat_percent,
    )

    weight_store.save_weighing(connection, one_weighing)

    change = None

    if previous is not None:
        difference, days_between = weight.change_between(previous, one_weighing)
        change = {"kilograms": difference, "days": days_between}

    return {
        "day": request.day.isoformat(),
        "kilograms": request.kilograms,
        "replaced": None if already_there is None else already_there.kilograms,
        "change_since_previous": change,
    }



# ---------------------------------------------------------------------------
# Signing in
# ---------------------------------------------------------------------------
#
# These two exist so the dashboard can have a login page of its own instead of the
# browser's grey password box. The check that actually guards every request happens at the
# CloudFront edge, in `infra/functions/session_gate.js`, which verifies the cookie this
# endpoint mints. This is the only place a password is ever compared.


class LoginRequest(pydantic.BaseModel):
    """What the login page sends."""

    password: str


@app.post("/api/login")
def log_in(request: LoginRequest) -> fastapi.Response:
    """Check the password and, if it is right, set the session cookie.

    The same answer for a wrong password and for no password at all, and no hint about
    which part was wrong -- there is one account, so the only thing an error message can
    do here is help somebody guessing.
    """
    try:
        expected = auth.read_password()
        secret = auth.signing_secret()
    except auth.PasswordNotSet as problem:
        # A deployment that is not finished, not a failed sign-in. Saying so plainly is
        # the difference between a two-minute fix and an afternoon of guessing.
        raise fastapi.HTTPException(status_code=503, detail=str(problem)) from problem

    if not auth.password_matches(request.password, expected):
        raise fastapi.HTTPException(status_code=401, detail="Wrong password.")

    response = fastapi.Response(status_code=204)

    response.set_cookie(
        key=auth.COOKIE_NAME,
        value=auth.mint_cookie(secret),
        max_age=auth.SESSION_LENGTH_SECONDS,
        # JavaScript on the page cannot read it, so a script injected into the page
        # cannot steal it.
        httponly=True,
        # Never sent over plain HTTP.
        secure=True,
        # Not sent on requests started by another site, which is what stops a page you
        # visit elsewhere from quietly calling this API as you.
        samesite="lax",
        path="/",
    )

    return response


@app.post("/api/logout")
def log_out() -> fastapi.Response:
    """Clear the cookie.

    Only ends THIS browser's session. Signing every device out at once means rotating the
    signing secret, which is the emergency lever rather than the everyday one.
    """
    response = fastapi.Response(status_code=204)
    response.delete_cookie(key=auth.COOKIE_NAME, path="/")

    return response
