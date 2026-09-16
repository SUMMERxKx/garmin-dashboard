"""The command line: one parser, and dispatch to the module that does the work.

This file deliberately holds no printing and no logic. It declares what commands exist
and hands each one to the module that owns it, which is what keeps it readable as the
command list grows.

    .venv/bin/python -m backend.cli.main today
    .venv/bin/python -m backend.cli.main import
    .venv/bin/python -m backend.cli.main days 14

Where the work actually happens:

    formatting.py      how a number becomes text
    day_view.py        `today`
    data_commands.py   `import`, `days`
    food_commands.py   `foods`, `log`, `meal`, `template`, `copy-yesterday`, `ate`
    body_commands.py   `weigh`, `weights`, `body`

Why a CLI still exists at all
-----------------------------
The dashboard is the interface now, and its Log page can record a weigh-in or a day's
calories when the API is running. These commands do the same things without a browser or
a server, and they are still the only way to log food item by item. Both routes call the
same modules, so a number recorded either way is checked the same way.
"""

from __future__ import annotations

import argparse
import datetime

from backend.cli import body_commands
from backend.cli import data_commands
from backend.cli import day_view
from backend.cli import food_commands


def build_argument_parser() -> argparse.ArgumentParser:
    """Describe the commands this tool accepts.

    Subcommands (`today`) rather than one flat set of options, because this will grow:
    logging food and recording a weigh-in are coming, and they are separate verbs. The
    shape is easier to set up now than to retrofit later.
    """
    parser = argparse.ArgumentParser(
        prog="backend.cli.main",
        description="Show saved Garmin data, and store it for reading a span at a time.",
    )

    subcommands = parser.add_subparsers(dest="command")

    today = subcommands.add_parser(
        "today",
        help="print one day (default: yesterday, because today is still unfinished)",
    )
    today.add_argument(
        "--date",
        help="the day to show, as YYYY-MM-DD (default: yesterday)",
    )
    today.add_argument(
        "--provenance",
        action="store_true",
        help="also list where each value was read from",
    )

    import_command = subcommands.add_parser(
        "import",
        help="read saved raw responses into the database (safe to re-run)",
    )
    import_command.add_argument(
        "--date",
        help="import one day only, as YYYY-MM-DD (default: every saved day)",
    )

    weigh_command = subcommands.add_parser(
        "weigh",
        help="record a weigh-in",
    )
    weigh_command.add_argument("kilograms", type=float, help="your weight in kg, e.g. 80.0")
    weigh_command.add_argument("--date", help="the day it belongs to (default: today)")
    weigh_command.add_argument(
        "--force",
        action="store_true",
        help="record it even though it is far from your last weigh-in",
    )

    weights_command = subcommands.add_parser(
        "weights",
        help="recent weigh-ins and the change between them",
    )
    weights_command.add_argument(
        "--days",
        type=int,
        default=30,
        help="how many days back to show (default: 30)",
    )

    subcommands.add_parser(
        "body",
        help="show the most recent DEXA scan and what has changed since",
    )

    subcommands.add_parser(
        "foods",
        help="list the food library and check it for mistakes",
    )

    log_command = subcommands.add_parser(
        "log",
        help="log a food you have eaten",
    )
    log_command.add_argument("food_id", help="which food, e.g. whey-protein")
    log_command.add_argument(
        "servings",
        type=float,
        help="how many servings, e.g. 1.5",
    )
    log_command.add_argument(
        "--date",
        help="the day to log it against, as YYYY-MM-DD (default: today)",
    )

    ate_command = subcommands.add_parser(
        "ate",
        help="record a whole day's calories as one number, e.g. ate 2100",
    )
    ate_command.add_argument("kilocalories", type=float, help="the day's total, e.g. 2100")
    ate_command.add_argument("--date", help="the day it belongs to (default: today)")
    ate_command.add_argument("--note", help="why it was typed rather than logged, if you like")

    meal_command = subcommands.add_parser(
        "meal",
        help="log one saved meal, e.g. morning",
    )
    meal_command.add_argument("meal_id", help="which meal, e.g. yogurt-bowl")
    meal_command.add_argument("--date", help="the day to log against (default: today)")
    meal_command.add_argument(
        "--set",
        action="append",
        dest="set_servings",
        help="answer a varying amount, e.g. --set rice-jasmine=1.25 (repeatable)",
    )

    template_command = subcommands.add_parser(
        "template",
        help="log a whole day from a template, e.g. normal-day",
    )
    template_command.add_argument("template_id", help="which template, e.g. normal-day")
    template_command.add_argument("--date", help="the day to log against (default: today)")
    template_command.add_argument(
        "--set",
        action="append",
        dest="set_servings",
        help="answer a varying amount, e.g. --set rice-jasmine=1.25 (repeatable)",
    )
    template_command.add_argument(
        "--replace",
        action="store_true",
        help="clear the day's food first, then log the template",
    )
    template_command.add_argument(
        "--add",
        action="store_true",
        help="log the template on top of what is already there",
    )

    copy_command = subcommands.add_parser(
        "copy-yesterday",
        help="copy yesterday's entries onto today",
    )
    copy_command.add_argument("--date", help="the day to copy INTO (default: today)")
    copy_command.add_argument(
        "--replace",
        action="store_true",
        help="clear the day's food first",
    )
    copy_command.add_argument(
        "--add",
        action="store_true",
        help="copy on top of what is already there",
    )

    days_command = subcommands.add_parser(
        "days",
        help="one line per stored day, to see a span at a glance",
    )
    days_command.add_argument(
        "--days",
        type=int,
        default=14,
        help="how many days back to show (default: 14)",
    )

    return parser


def main() -> int:
    """Entry point. Returns 0 if everything went well and 1 if it did not.

    Returning a number rather than just printing is the long-standing shell convention:
    0 means success, anything else means failure. It is what lets another script -- or
    a scheduler, later on -- tell whether this run worked.
    """
    parser = build_argument_parser()
    arguments = parser.parse_args()

    if arguments.command is None:
        # Nobody typed a subcommand. Show the help rather than doing nothing silently.
        parser.print_help()
        return 1

    if arguments.command == "weigh":
        return body_commands.run_weigh(arguments.kilograms, arguments.date, arguments.force)

    if arguments.command == "weights":
        return body_commands.run_weights(arguments.days)

    if arguments.command == "body":
        return body_commands.run_body()

    if arguments.command == "foods":
        return food_commands.run_foods()

    if arguments.command == "log":
        return food_commands.run_log(arguments.food_id, arguments.servings, arguments.date)

    if arguments.command == "ate":
        return food_commands.run_ate(arguments.kilocalories, arguments.date, arguments.note)

    if arguments.command == "meal":
        return food_commands.run_meal(arguments.meal_id, arguments.date, arguments.set_servings)

    if arguments.command == "template":
        return food_commands.run_template(
            arguments.template_id,
            arguments.date,
            arguments.set_servings,
            replace_existing=arguments.replace,
            add_to_existing=arguments.add,
        )

    if arguments.command == "copy-yesterday":
        return food_commands.run_copy_yesterday(
            arguments.date,
            replace_existing=arguments.replace,
            add_to_existing=arguments.add,
        )

    if arguments.command == "days":
        return data_commands.run_days(arguments.days)

    if arguments.command == "import":
        if arguments.date is None:
            # No day named, so import everything already on disk. Re-importing is
            # harmless, and this is the command you want after improving the mapping.
            return data_commands.run_import(data_commands.days_we_have_saved())

        try:
            return data_commands.run_import([datetime.date.fromisoformat(arguments.date)])
        except ValueError:
            print(f"'{arguments.date}' is not a date. Use the form 2026-09-12.")
            return 1

    return day_view.run_today(arguments.date, arguments.provenance)


# This block runs only when the file is executed directly, not when it is imported by
# another module. `raise SystemExit(...)` is how a Python program sets the exit code the
# shell sees.
if __name__ == "__main__":
    raise SystemExit(main())
