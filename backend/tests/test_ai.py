"""Tests for the AI layer, and above all for the check that makes it safe.

The feature is a model writing English about numbers. The risk is a model writing a
number. Everything below is about that boundary: the fact sheet is built from finished
figures, and any figure in the reply that is not on the sheet means the whole reply is
discarded.

No AWS, no network, no key. The Bedrock client is a fake, which is possible because
`interpret.ask` takes one.
"""

from __future__ import annotations

import pytest

from backend.ai import factsheet
from backend.ai import interpret


def a_payload() -> dict:
    """A small payload with the shapes the fact sheet reads."""
    return {
        "first_day": "2026-08-16",
        "last_day": "2026-09-15",
        "macro_target": {"kilocalories": 2350.0, "protein_grams": 180.0, "goal": "cutting"},
        "baselines": {
            "as_of": "2026-09-14",
            "metrics": {
                "hrv_last_night": {
                    "latest_value": 104.0,
                    "window_30": {"mean": 107.3, "standard_deviation": 13.7},
                    "position_vs_30": "typical",
                },
                "steps": {
                    "latest_value": 22434,
                    "window_30": {"mean": 22156.0, "standard_deviation": 5743.0},
                    "position_vs_30": "typical",
                },
            },
        },
        "days": [
            {
                "day": "2026-09-14",
                "energy": {"total_kilocalories": 3351},
                "intake": {"kilocalories": 2078.0, "source": "logged", "from_day": "2026-09-14"},
                "weight": None,
                "activities": [{"type_key": "strength_training"}],
            },
            {
                # Burn known AND intake carried, so this day lands in the balance average
                # as an assumption -- which is exactly what the sheet has to disclose.
                "day": "2026-09-15",
                "energy": {"total_kilocalories": 3100},
                "intake": {"kilocalories": 2078.0, "source": "carried", "from_day": "2026-09-14"},
                "weight": {"kilograms": 77.7},
                "activities": [],
            },
        ],
    }


# ---------------------------------------------------------------------------
# The fact sheet
# ---------------------------------------------------------------------------


def test_the_sheet_carries_the_figures_and_their_normals() -> None:
    sheet = factsheet.build(a_payload())

    assert "104" in sheet
    assert "107" in sheet
    assert "22,434" in sheet
    assert "typical" in sheet


def test_the_sheet_says_when_intake_was_assumed() -> None:
    """The honest reading of a mostly-assumed balance is 'we do not really know yet', and
    the model cannot reach that conclusion unless it is told."""
    sheet = factsheet.build(a_payload())

    assert "ASSUMED" in sheet


def test_the_sheet_reports_weigh_in_consistency() -> None:
    """Every average below it gets worse as this drops, so it belongs on the sheet."""
    sheet = factsheet.build(a_payload())

    assert "consistency" in sheet


def test_an_empty_payload_produces_a_sheet_rather_than_a_crash() -> None:
    assert factsheet.build({"days": []}) == "No data yet."


def test_numbers_are_found_including_negatives_and_separators() -> None:
    found = factsheet.numbers_in("balance -1,273 kcal, weight 77.7 kg, steps 22,434")

    assert "-1,273" in found
    assert "77.7" in found
    assert "22,434" in found


# ---------------------------------------------------------------------------
# The check that makes it safe
# ---------------------------------------------------------------------------


def test_a_reply_using_only_the_sheets_numbers_is_accepted() -> None:
    sheet = "- HRV: 104 ms (30-day normal 107 ms)"

    assert interpret.check_the_numbers(sheet, "HRV of 104 sits near the normal of 107.") == []


def test_a_reply_inventing_a_number_is_caught() -> None:
    """The whole point. A model that computes an average is producing a figure nobody
    tested, and it looks exactly as confident as one that is right."""
    sheet = "- HRV: 104 ms (30-day normal 107 ms)"

    caught = interpret.check_the_numbers(sheet, "Your HRV averaged 98.6 over the period.")

    assert "98.6" in caught


def test_a_rounded_version_of_a_real_number_is_still_caught() -> None:
    """`107.3` when the sheet says `107` was produced, not repeated. Subtle, and exactly
    the kind of quiet drift worth refusing."""
    sheet = "- HRV: 104 ms (30-day normal 107 ms)"

    assert "107.3" in interpret.check_the_numbers(sheet, "The normal is 107.3 ms.")


def test_small_counts_are_allowed_through() -> None:
    """'over the last 7 days' is sentence furniture, not a measurement. Rejecting good
    answers over it would make the check so annoying it would get turned off."""
    sheet = "- HRV: 104 ms"

    assert interpret.check_the_numbers(sheet, "Across the last 7 days, 3 nights stood out.") == []


def test_percentages_the_model_worked_out_are_caught() -> None:
    sheet = "- steps: 22,434 (30-day normal 22,156)"

    assert interpret.check_the_numbers(sheet, "Steps were 27% above normal.") == ["27"]


# ---------------------------------------------------------------------------
# The reply, end to end, against a fake model
# ---------------------------------------------------------------------------


class FakeBedrock:
    """A Bedrock client that answers with whatever text it was given."""

    def __init__(self, reply_text: str) -> None:
        self.reply_text = reply_text
        self.last_request: dict = {}

    def converse(self, **arguments):
        self.last_request = arguments

        return {
            "output": {"message": {"content": [{"text": self.reply_text}]}},
            "usage": {"inputTokens": 300, "outputTokens": 120},
        }


def test_a_clean_reading_comes_back_trustworthy() -> None:
    sheet = "- HRV: 104 ms (30-day normal 107 ms)"
    reply = '{"headline": "A typical week", "observations": ["HRV at 104 is near your normal of 107."]}'

    reading = interpret.ask(sheet, client=FakeBedrock(reply))

    assert reading.is_trustworthy
    assert reading.headline == "A typical week"
    assert len(reading.observations) == 1
    assert reading.input_tokens == 300


def test_a_reading_with_an_invented_number_is_not_trustworthy() -> None:
    sheet = "- HRV: 104 ms (30-day normal 107 ms)"
    reply = '{"headline": "Down", "observations": ["HRV fell 14.2% this week."]}'

    reading = interpret.ask(sheet, client=FakeBedrock(reply))

    assert not reading.is_trustworthy
    assert "14.2" in reading.invented_numbers


def test_a_reply_wrapped_in_a_code_fence_is_still_parsed() -> None:
    """Models do this however plainly the instruction says not to."""
    sheet = "- HRV: 104 ms"
    reply = '```json\n{"headline": "Fine", "observations": ["HRV 104."]}\n```'

    reading = interpret.ask(sheet, client=FakeBedrock(reply))

    assert reading.headline == "Fine"
    assert reading.is_trustworthy


def test_a_reply_that_is_not_json_still_gets_number_checked() -> None:
    """Falling back to plain text must not fall back on the safety check."""
    sheet = "- HRV: 104 ms"

    reading = interpret.ask(sheet, client=FakeBedrock("HRV averaged 91.5 this week."))

    assert not reading.is_trustworthy
    assert "91.5" in reading.invented_numbers


def test_the_model_is_told_not_to_prescribe() -> None:
    """The product is observational. This pins the instruction so it cannot quietly go."""
    fake = FakeBedrock('{"headline": "x", "observations": []}')

    interpret.ask("- HRV: 104 ms", client=fake)

    system_text = fake.last_request["system"][0]["text"]

    assert "Never prescribe" in system_text
    assert "Never write a number that does not appear" in system_text
    assert fake.last_request["inferenceConfig"]["temperature"] == 0.0


def test_an_unreachable_model_raises_its_own_exception() -> None:
    """Bedrock being off is a normal state for a new account, not a fault, and the
    dashboard says something different about it."""

    class Broken:
        def converse(self, **arguments):
            raise RuntimeError("AccessDeniedException: account is being verified")

    with pytest.raises(interpret.NotAvailable):
        interpret.ask("- HRV: 104 ms", client=Broken())


# ---------------------------------------------------------------------------
# The cache
# ---------------------------------------------------------------------------


def test_the_cache_key_follows_the_facts_not_the_date() -> None:
    """A reading survives exactly as long as the numbers it describes. No expiry to tune,
    and no stale commentary to explain."""
    first = interpret.cache_key("- HRV: 104 ms")
    same = interpret.cache_key("- HRV: 104 ms")
    different = interpret.cache_key("- HRV: 105 ms")

    assert first == same
    assert first != different


# ---------------------------------------------------------------------------
# What may leave the server
# ---------------------------------------------------------------------------


def test_a_reading_sent_to_a_browser_names_no_vendor_and_no_cost() -> None:
    """Which model wrote it and what it cost belong in a log, not on a screen.

    An interface that names its supplier has to be edited every time the supplier
    changes, and the reader came for the reading rather than the plumbing.
    """
    reading = interpret.Reading(
        headline="A typical week",
        observations=["HRV is near normal."],
        model_id="bedrock/ca.amazon.nova-lite-v1:0",
        input_tokens=891,
        output_tokens=113,
        invented_numbers=[],
    )

    as_json = interpret.reading_to_json(reading, "- HRV: 104 ms")

    assert set(as_json) == {"headline", "observations", "facts_fingerprint"}
    assert "nova" not in str(as_json).lower()
    assert "bedrock" not in str(as_json).lower()


def test_a_reading_cached_by_an_older_version_is_stripped_on_the_way_out() -> None:
    """The failure this catches actually happened: the fields were removed from what gets
    WRITTEN, and a record already in the cache kept serving them."""
    stored_by_an_older_version = {
        "headline": "h",
        "observations": ["o"],
        "facts_fingerprint": "abc",
        "model_id": "bedrock/ca.amazon.nova-lite-v1:0",
        "input_tokens": 891,
        "output_tokens": 113,
    }

    cleaned = interpret.public_reading(stored_by_an_older_version)

    assert set(cleaned) == {"headline", "observations", "facts_fingerprint"}


def test_a_field_added_later_is_excluded_by_default() -> None:
    """An allow list rather than a block list, so the next field to be added does not
    leak until somebody remembers to exclude it."""
    cleaned = interpret.public_reading(
        {"headline": "h", "observations": [], "facts_fingerprint": "x", "some_new_debug_field": "secret"}
    )

    assert "some_new_debug_field" not in cleaned
