"""Fetching one day of data from Garmin.

This is the code that finally uses the other two modules: `login` gives us a client
that can make calls, `endpoints` says which calls to make, and this walks the list and
makes them.

It does not save anything and it does not try to understand the responses. It hands
back exactly what Garmin sent, plus a note of anything that went wrong. Turning those
responses into useful numbers is a separate job, kept separate on purpose: if we ever
get the interpretation wrong, we want to fix it and re-run it against data we already
have, rather than having to go back and ask Garmin again.
"""

from __future__ import annotations

import dataclasses
import datetime
from typing import Any

from backend.garmin import endpoints


@dataclasses.dataclass
class DayFetchResult:
    """Everything that came back from one day's fetch, including the failures.

    Both dictionaries are keyed by our short endpoint name -- "sleep", "hrv" and so on,
    the `name` field from the endpoint list.

    A given endpoint appears in exactly one of the two: either we got a response from
    it, or we got an error. Never both, and never neither.
    """

    #: The day we asked about.
    day: datetime.date

    #: endpoint name -> whatever Garmin sent back. The value could be a dictionary, a
    #: list, or None, because different endpoints return different shapes. We are not
    #: inspecting it here, only carrying it.
    responses: dict[str, Any]

    #: endpoint name -> a description of what went wrong, for the calls that failed.
    errors: dict[str, str]

    def names_that_worked(self) -> list[str]:
        """The endpoints that returned something without raising."""
        return sorted(self.responses.keys())

    def names_that_failed(self) -> list[str]:
        """The endpoints that raised an error."""
        return sorted(self.errors.keys())

    def every_tier_one_endpoint_worked(self) -> bool:
        """True if all seven tier-1 endpoints came back.

        This is the question worth asking after a fetch. "Did all seventeen calls
        succeed?" is the wrong bar -- tier-2 endpoints fail routinely and harmlessly.
        "Can the dashboard be drawn from what we got?" is the real one, and that is
        exactly the tier-1 set.
        """
        for endpoint in endpoints.tier_one_endpoints():
            if endpoint.name not in self.responses:
                return False

        return True


def build_arguments_for(endpoint: endpoints.Endpoint, day: datetime.date) -> list[str]:
    """Work out what arguments this particular endpoint wants, for this day.

    Garmin's methods are not consistent about dates: most take a single one, but a
    couple were designed for ranges and take a start and an end. We handle that here,
    in one place, rather than remembering it at every call site.

    Dates go over the wire as text in the form "2026-09-10". `date.isoformat()` is the
    standard library's name for exactly that format, so we never build it by hand.
    """
    day_as_text = day.isoformat()

    if endpoint.argument_style is endpoints.ArgumentStyle.ONE_DATE:
        return [day_as_text]

    elif endpoint.argument_style is endpoints.ArgumentStyle.START_AND_END_DATE:
        # The same day twice: start of the range and end of the range are both today,
        # because we always fetch exactly one day at a time.
        return [day_as_text, day_as_text]

    else:
        # This can only happen if someone adds a new ArgumentStyle to the enum and
        # forgets to handle it here. Failing loudly is much better than quietly
        # calling the method with no arguments and getting a confusing error later.
        raise ValueError(
            f"Endpoint '{endpoint.name}' has argument style {endpoint.argument_style}, "
            f"which build_arguments_for does not know how to handle."
        )


def call_one_endpoint(
    client: Any,
    endpoint: endpoints.Endpoint,
    day: datetime.date,
) -> Any:
    """Make a single call and return whatever came back.

    This is where the endpoint list stops being a description and becomes a real
    method call.

    `getattr(client, "get_sleep_data")` looks up a method on an object *by its name as
    text* and hands back the method itself, ready to be called. In Java this is
    reflection -- `getClass().getMethod(...)`. It is what lets a list of strings drive
    real calls, and it is why the endpoint list stores the method name as text rather
    than storing the function.
    """
    method_to_call = getattr(client, endpoint.client_method_name)

    arguments = build_arguments_for(endpoint, day)

    # The `*` unpacks the list into separate arguments, so a list of one becomes
    # method("2026-09-10") and a list of two becomes method("2026-09-10", "2026-09-10").
    return method_to_call(*arguments)


def fetch_one_day(client: Any, day: datetime.date) -> DayFetchResult:
    """Call every endpoint on the list for one day, and collect the results.

    The important design decision is in the `except` below: one endpoint failing must
    not cost us the other sixteen.

    That is not a hypothetical. HRV returns nothing at all for the first few weeks of
    owning a watch, while Garmin builds its baseline. If a missing HRV reading aborted
    the whole run, we would lose that day's sleep, steps, calories and workouts too --
    over something entirely expected.

    So each call is wrapped on its own. A failure is recorded and the loop moves on.
    """
    responses: dict[str, Any] = {}
    errors: dict[str, str] = {}

    for endpoint in endpoints.ENDPOINTS:
        try:
            response = call_one_endpoint(client, endpoint, day)
            responses[endpoint.name] = response

        except Exception as error:
            # Catching every exception is usually a bad habit, because it hides bugs.
            # Here it is the entire point: we cannot predict what an unofficial API
            # behind someone else's library will raise -- a network timeout, a 404, a
            # parsing failure inside the library itself -- and every one of those means
            # the same thing to us, which is "this endpoint did not work today".
            #
            # We record the exception's type as well as its message, because
            # "ConnectionError: timed out" and "KeyError: 'dailySleepDTO'" are very
            # different problems and the message alone does not always say which.
            errors[endpoint.name] = f"{type(error).__name__}: {error}"

    return DayFetchResult(day=day, responses=responses, errors=errors)
