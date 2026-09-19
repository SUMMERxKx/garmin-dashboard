"""Tests that every command the parser accepts can actually be dispatched.

The bug this exists for: `import` with no `--date` called
`data_commands.days_we_have_saved()`, but that function lives in `days.py`. It had moved
there when the 1,030-line `main.py` was split into one module per command group, and
nothing noticed for four chunks -- because every test called the command modules directly
and nothing exercised `main()` itself. It failed with an `AttributeError` the first time
it was run, which was in the middle of a 60-day backfill.

These tests do not check what the commands DO. They check that the wiring between the
parser and the modules is intact, which is the part no other test touches.
"""

from __future__ import annotations

import pytest

from backend.cli import body_commands
from backend.cli import data_commands
from backend.cli import day_view
from backend.cli import days
from backend.cli import food_commands
from backend.cli import main

#: Every function `main()` dispatches to, as (module, attribute) pairs. Written out by
#: hand rather than discovered, because the point is to state what the parser promises.
DISPATCH_TARGETS = [
    (body_commands, "run_weigh"),
    (body_commands, "run_weights"),
    (body_commands, "run_body"),
    (food_commands, "run_foods"),
    (food_commands, "run_log"),
    (food_commands, "run_meal"),
    (food_commands, "run_template"),
    (food_commands, "run_copy_yesterday"),
    (food_commands, "run_ate"),
    (data_commands, "run_days"),
    (data_commands, "run_import"),
    (day_view, "run_today"),
    (days, "days_we_have_saved"),
]


@pytest.mark.parametrize(("module", "attribute"), DISPATCH_TARGETS)
def test_every_dispatch_target_exists(module, attribute) -> None:
    """A command that dispatches to a function that moved fails only when it is run."""
    assert hasattr(module, attribute), f"{module.__name__} has no {attribute}"
    assert callable(getattr(module, attribute))


def test_every_subcommand_the_parser_accepts_is_handled() -> None:
    """The parser and the dispatch chain must list the same commands.

    Adding a subcommand and forgetting the `if` that handles it gives you a command that
    parses cleanly and then silently runs `today` instead, which is worse than an error.
    """
    parser = main.build_argument_parser()

    subcommand_actions = [
        action for action in parser._subparsers._group_actions if action.choices
    ]

    declared = set(subcommand_actions[0].choices)

    dispatch_source = main.main.__code__.co_consts
    handled = {one for one in dispatch_source if isinstance(one, str) and one in declared}

    # `today` is the fall-through at the end of main(), so it is handled without being
    # named in an `if`.
    missing = declared - handled - {"today"}

    assert missing == set(), f"parsed but never dispatched: {sorted(missing)}"
