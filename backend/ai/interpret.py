"""Asking Claude what the numbers mean, and refusing to believe any number it writes back.

THE CONTRACT
============
The model is handed a fact sheet of finished figures and asked for English. Then every
number in its reply is checked against that sheet. A number that is not on the sheet was
invented, and an answer containing one is thrown away rather than shown.

That check is the whole reason this is safe to put on a health dashboard. A language model
asked to reason about figures will sometimes produce one that looks right and is not, with
no change in tone to warn you. Here it cannot: it has no arithmetic to do, and if it does
any anyway, the result never reaches the screen.

It is also the answer to the obvious interview question. "How do you stop it hallucinating
a number?" is not answered by a careful prompt. It is answered by never asking it for a
number, and by checking.

WHAT IT IS ALLOWED TO SAY
=========================
The product is observational. It reports what happened against your own baselines. It is
not a coach and does not prescribe: no training plans, no calorie targets, no "you should".
That is in the prompt, and the prompt is in this file rather than buried in a config, so
that what the model was told is as readable as what it replied.

COST
====
The fact sheet is about 300 tokens and the reply is capped well below that. At Haiku
prices a reading costs a small fraction of a cent, and one is generated per day at most --
see `cache_key`, which changes only when the facts change.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from typing import Any

import boto3

from backend.ai import factsheet

#: Which model. Haiku because the job is one paragraph of plain reading over a sheet that
#: has already done every calculation -- there is no reasoning load here worth paying for,
#: and a cheaper model called daily is the difference between pennies and not.
#:
#: The same model is named two ways because it can be reached two ways. See `ask`.
#: Amazon Nova Lite, through the CANADIAN inference profile. Three reasons, in order:
#:
#:   1. Cost. Nova Lite is roughly an order of magnitude cheaper per token than the
#:      Claude models, and the job here is one short paragraph over a sheet that has
#:      already done every calculation. There is no reasoning load worth paying for.
#:   2. Residency. `ca.` keeps the request in Canada, matching the rest of this project.
#:      The Claude profiles available here are `us.` and `global.` only, which would have
#:      been the one thing in the system leaving the country.
#:   3. It works today. Anthropic models on Bedrock need a use-case form submitted per
#:      account; Nova does not.
#:
#: An INFERENCE PROFILE, not a bare model id. Bedrock refuses a bare id for on-demand
#: calls to these models -- a profile is how it routes to available capacity.
#:
#: Nova can also be fine-tuned on Bedrock later, which the Claude models cannot, so this
#: is the direction that keeps that door open.
BEDROCK_MODEL_ID = "ca.amazon.nova-lite-v1:0"
#: If an Anthropic API key is configured instead, this is the model it uses. Kept as the
#: stopgap route; Bedrock with Nova is the default.
ANTHROPIC_MODEL_ID = "claude-haiku-4-5-20251001"
REGION = "ca-central-1"

#: Where an Anthropic API key is kept, if this deployment uses one. Encrypted, and under
#: the same prefix as the login password so one permission covers the pair.
API_KEY_PARAMETER_NAME = "/garmin-dashboard/anthropic-api-key"

#: Long enough for four short observations, short enough that a model which starts
#: rambling gets cut off rather than billed for.
MAXIMUM_REPLY_TOKENS = 400

#: Zero, because the same facts should give the same reading. A dashboard whose commentary
#: changes wording every refresh looks like it is thinking; it is just sampling.
TEMPERATURE = 0.0

#: How many observations to ask for.
WANTED_OBSERVATIONS = 4

SYSTEM_PROMPT = """You read a fact sheet from a personal health dashboard and say what it \
means, in plain English, for the one person whose data it is.

ABSOLUTE RULES

1. Never write a number that does not appear in the fact sheet. Not a rounded version, not \
a total you worked out, not a percentage, not an average. If you want to make a point that \
needs a number the sheet does not contain, make the point without the number or leave it out.

2. Never prescribe. Do not tell the reader what to eat, how to train, how much to sleep, or \
what to change. This dashboard reports; it does not coach. "Your sleep was short" is fine. \
"You should sleep more" is not.

3. Never diagnose, and never speculate about illness.

4. Say when the data does not support a conclusion. A figure marked ASSUMED was carried \
forward, not recorded. A span with few weigh-ins cannot show a weight trend. Pointing that \
out is more useful than a confident reading of thin data.

5. Prefer what is unusual over what is normal. If everything is typical, say so briefly \
rather than padding.

STYLE

Short sentences. No hedging phrases like "it seems" or "it appears". No encouragement, no \
congratulation, no motivational language. Write like a colleague reading an instrument \
panel, not like a fitness app.

OUTPUT

Reply with JSON only, no prose around it, in exactly this shape:

{"observations": ["...", "..."], "headline": "..."}

`headline` is at most eight words summarising the span. `observations` is a list of at most \
four entries, each one or two sentences."""


@dataclasses.dataclass
class Reading:
    """What the model said, and whether it is trustworthy enough to show."""

    headline: str
    observations: list[str]

    #: The model that produced it, and what it cost, for the record.
    model_id: str
    input_tokens: int
    output_tokens: int

    #: Numbers the model wrote that were NOT on the fact sheet. Empty is the only
    #: acceptable state; anything else means the reading is discarded.
    invented_numbers: list[str]

    @property
    def is_trustworthy(self) -> bool:
        return len(self.invented_numbers) == 0


class NotAvailable(Exception):
    """The model could not be reached, or is not enabled for this deployment.

    Its own exception because it is not a failure of this code and the dashboard should
    say something different about it: "not switched on yet" rather than "something broke".

    It carries TWO messages, and the distinction matters. `public_reason` is a short
    sentence safe to send to a browser. The exception's own text is the provider's raw
    error, which is for the log only -- AWS error strings routinely contain the account
    id, the IAM role name and the function name, and that is exactly the sort of thing
    that should never travel to a client where it lands in network logs and screenshots.
    """

    def __init__(self, raw_message: str, public_reason: str) -> None:
        super().__init__(raw_message)
        self.public_reason = public_reason


def describe_failure_safely(raw_message: str) -> str:
    """Turn a provider error into something safe to show, revealing nothing about AWS.

    Deliberately coarse. Three possible answers, none of which names an account, a role,
    a function, a region or an ARN. Anybody debugging this reads the log, where the whole
    error is printed.
    """
    lowered = raw_message.lower()

    if "use case" in lowered or "agreement" in lowered:
        return "The model has not been enabled for this AWS account yet."

    if "accessdenied" in lowered or "not authorized" in lowered or "resourcenotfound" in lowered:
        return "This deployment is not permitted to call the model yet."

    if "throttl" in lowered or "timeout" in lowered or "timed out" in lowered:
        return "The model was busy. Try again shortly."

    return "The model could not be reached."


def cache_key(sheet: str) -> str:
    """A short fingerprint of the facts, used as the stored reading's address.

    Keyed on the FACTS rather than on the date. A reading is then reused all day, and
    regenerated the moment anything it was based on changes -- a new weigh-in, a fetch
    landing a new day -- without anybody having to decide when it goes stale.
    """
    return hashlib.sha256(sheet.encode("utf-8")).hexdigest()[:16]


def check_the_numbers(sheet: str, reply_text: str) -> list[str]:
    """Every number in the reply that does not appear on the fact sheet.

    Compared as written rather than as values. If the sheet says `107` and the reply says
    `107.3`, that is a number the model produced rather than repeated, and it is exactly
    the kind of quiet invention worth catching.

    Years and small counts are allowed through: a sentence like "over the last 7 days"
    uses a number that is structural rather than a measurement, and the sheet usually
    contains it anyway.
    """
    on_the_sheet = factsheet.numbers_in(sheet)
    in_the_reply = factsheet.numbers_in(reply_text)

    invented = []

    for number in sorted(in_the_reply):
        if number in on_the_sheet:
            continue

        # A bare small integer is almost always "one of the four points" or "the last 7
        # days", not a measurement. Allowing these avoids rejecting good answers over
        # sentence furniture, and nothing dangerous hides in a number under ten.
        without_separators = number.replace(",", "")

        if without_separators.isdigit() and int(without_separators) <= 10:
            continue

        invented.append(number)

    return invented


def parse_reply(reply_text: str) -> tuple[str, list[str]]:
    """Pull the headline and observations out of the model's JSON.

    Tolerant of a model that wraps its JSON in a code fence, which they sometimes do
    however clearly the instruction says not to.
    """
    text = reply_text.strip()

    if text.startswith("```"):
        # Drop the first line (```json) and the trailing fence.
        lines = text.splitlines()
        text = "\n".join(lines[1:])
        text = text.rsplit("```", 1)[0].strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Not JSON at all. Rather than fail, treat the whole reply as one observation --
        # the number check still applies to it, which is what actually matters.
        return ("", [text])

    headline = str(parsed.get("headline", "")).strip()
    observations = [str(one).strip() for one in parsed.get("observations", []) if str(one).strip()]

    return (headline, observations)


def find_api_key() -> str | None:
    """An Anthropic API key from Parameter Store, or None if this deployment has none.

    Absence is a normal state, not an error: it simply means Bedrock is the route.
    """
    client = boto3.client("ssm", region_name=REGION)

    try:
        answer = client.get_parameter(Name=API_KEY_PARAMETER_NAME, WithDecryption=True)
    except Exception:
        # Not set, or no permission to read it. Either way, fall through to Bedrock.
        return None

    value = answer["Parameter"]["Value"].strip()

    return value or None


def ask_bedrock(sheet: str, client: Any = None) -> tuple[str, dict, str]:
    """Call the model through Bedrock. Returns the reply text, usage, and model name."""
    if client is None:
        client = boto3.client("bedrock-runtime", region_name=REGION)

    answer = client.converse(
        modelId=BEDROCK_MODEL_ID,
        system=[{"text": SYSTEM_PROMPT}],
        messages=[{"role": "user", "content": [{"text": sheet}]}],
        inferenceConfig={
            "maxTokens": MAXIMUM_REPLY_TOKENS,
            "temperature": TEMPERATURE,
        },
    )

    usage = answer.get("usage", {})

    return (
        answer["output"]["message"]["content"][0]["text"],
        {"input": usage.get("inputTokens", 0), "output": usage.get("outputTokens", 0)},
        f"bedrock/{BEDROCK_MODEL_ID}",
    )


def ask_anthropic(sheet: str, api_key: str) -> tuple[str, dict, str]:
    """Call the same model through Anthropic's own API, with a key.

    Written against `urllib` from the standard library rather than the `anthropic`
    package, so the Lambda gains no dependency for a single HTTP call it makes once a day.
    """
    import json as json_module
    import urllib.request

    body = json_module.dumps(
        {
            "model": ANTHROPIC_MODEL_ID,
            "max_tokens": MAXIMUM_REPLY_TOKENS,
            "temperature": TEMPERATURE,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": sheet}],
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        answer = json_module.loads(response.read())

    usage = answer.get("usage", {})

    return (
        answer["content"][0]["text"],
        {"input": usage.get("input_tokens", 0), "output": usage.get("output_tokens", 0)},
        f"anthropic/{ANTHROPIC_MODEL_ID}",
    )


def ask(sheet: str, client: Any = None, api_key: str | None = None) -> Reading:
    """Send the fact sheet to the model and return a CHECKED reading.

    Two routes to the same model, and the choice is made by what is configured rather than
    by a flag anybody has to remember:

      an Anthropic API key in Parameter Store  ->  Anthropic's API directly
      no key                                   ->  Bedrock, authenticated by the IAM role

    Bedrock is the better arrangement for this project -- no key to store or rotate, and
    the request never leaves AWS -- so it is the default, and the key exists as the way to
    work while a new AWS account is still being verified for Bedrock access. Removing the
    parameter switches back with no deploy.

    Whichever route answered, the reply goes through the same number check. That check is
    the point of this module and it is not route-specific.

    `client` and `api_key` are injectable so the tests can run the whole path -- prompt,
    parsing, number checking -- against a fake, with no account and no network.
    """
    if api_key is None and client is None:
        api_key = find_api_key()

    try:
        if api_key is not None:
            reply_text, usage, model_name = ask_anthropic(sheet, api_key)
        else:
            reply_text, usage, model_name = ask_bedrock(sheet, client)
    except Exception as problem:
        # Includes a new AWS account whose Bedrock access is still being verified, which
        # reads as AccessDenied and is the normal state for the first couple of hours.
        # The raw text goes to the log; only the sanitised reason may reach a browser.
        raw = str(problem)
        raise NotAvailable(raw, describe_failure_safely(raw)) from problem

    headline, observations = parse_reply(reply_text)

    return Reading(
        headline=headline,
        observations=observations,
        model_id=model_name,
        input_tokens=usage["input"],
        output_tokens=usage["output"],
        invented_numbers=check_the_numbers(sheet, reply_text),
    )


#: The only keys a reading may carry to a browser. Anything else a stored record happens
#: to hold -- including fields an older version of this code wrote -- is dropped on the
#: way out. Written as an allow list rather than a list of things to remove, so a field
#: added later is excluded by default instead of leaking until somebody notices.
PUBLIC_READING_FIELDS = ["headline", "observations", "facts_fingerprint"]


def public_reading(stored: dict[str, Any]) -> dict[str, Any]:
    """Strip a stored reading down to what may leave the server.

    Applied to CACHED readings as well as fresh ones. A record written before this rule
    existed still holds the model name and token counts, and would otherwise keep serving
    them until the cache happened to turn over.
    """
    return {key: stored[key] for key in PUBLIC_READING_FIELDS if key in stored}


def reading_to_json(reading: Reading, sheet: str) -> dict[str, Any]:
    """The shape the dashboard receives, and the shape that gets cached.

    Which model wrote it and what it cost are deliberately NOT here. They are useful in a
    log and useless on a screen: a reader wants the reading, not the plumbing behind it,
    and naming a vendor in the interface means the interface has to be edited every time
    the vendor changes. Both are printed to CloudWatch instead.
    """
    return {
        "headline": reading.headline,
        "observations": reading.observations,
        "facts_fingerprint": cache_key(sheet),
    }
