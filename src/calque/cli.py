"""Command-line entry point: parse options into a configuration and drive a synchronisation run."""

import logging
import re
import sys
from argparse import Action, ArgumentDefaultsHelpFormatter, ArgumentParser, BooleanOptionalAction, Namespace
from collections.abc import Iterable, Sequence
from dataclasses import fields
from typing import Any, cast

from calque.config import Config
from calque.errors import CalqueError
from calque.model import Participation
from calque.service import install, uninstall
from calque.store import CalendarStore
from calque.sync import synchronise


class CompilePatterns(Action):
    """Compile the given regular expressions and store them as the immutable pattern set."""

    def __call__(
        self,
        parser: ArgumentParser,  # noqa: ARG002
        namespace: Namespace,
        values: str | Sequence[Any] | None,
        option_string: str | None = None,
    ) -> None:
        """Compile every pattern and store the resulting tuple on the namespace."""
        setattr(namespace, self.dest, tuple(re.compile(pattern) for pattern in cast("Sequence[str]", values)))


class CollectCompilePatterns(Action):
    """Collect a ``--option KEY REGEX [REGEX ...]`` group into a mapping of key name to its compiled patterns.

    Requires that the destination is defaulted to a mutable mapping. Repeated groups naming the same key
    accumulate, so a key can be given several patterns across one or more uses of the option.
    """

    def __call__(
        self,
        parser: ArgumentParser,
        namespace: Namespace,
        values: str | Sequence[Any] | None,
        option_string: str | None = None,
    ) -> None:
        """Compile every pattern and append them under their key in the mapping."""
        key, *patterns = cast("Sequence[str]", values)
        if not patterns:
            parser.error(f"argument {option_string}: expected a key name and at least one pattern")
        mapping = getattr(namespace, self.dest)
        mapping[key] = (*mapping.get(key, ()), *(re.compile(pattern) for pattern in patterns))


class CollectMapping(Action):
    """Collect one or more ``--option-for KEY VALUE`` pairs into a mapping.

    Requires that the destination is defaulted to a mutable mapping, which it updates in-place with each pair.
    """

    def __call__(
        self,
        parser: ArgumentParser,  # noqa: ARG002
        namespace: Namespace,
        values: str | Sequence[Any] | None,
        option_string: str | None = None,
    ) -> None:
        """Store one parsed key/value pair into the mapping."""
        key, value = cast("Sequence[str]", values)
        getattr(namespace, self.dest)[key] = value


class CollectSet(Action):
    """Collect the given values into an immutable set on the namespace."""

    def __call__(
        self,
        parser: ArgumentParser,  # noqa: ARG002
        namespace: Namespace,
        values: str | Sequence[Any] | None,
        option_string: str | None = None,
    ) -> None:
        """Store the values as a frozenset on the namespace."""
        setattr(namespace, self.dest, frozenset(cast("Sequence[str]", values)))


def values_string(items: Iterable[Any]) -> str:
    """Return a list of the string values of a group of items."""
    return ", ".join(sorted(item.value for item in items))


class DefaultsHelpFormatter(ArgumentDefaultsHelpFormatter):
    """Append each option's default to its help unless the help already mentions it."""

    def _get_help_string(self, action: Action) -> str | None:
        """Return the help string for an action, appending the default if not already mentioned."""
        return action.help if action.help and "default: " in action.help else super()._get_help_string(action)


def parse_arguments(arguments: list[str] | None) -> Namespace:
    """Build the parser and parse the given command-line arguments."""
    defaults = Config()
    parser = ArgumentParser(
        prog="calque",
        description="Mirror accepted events from one local calendar into another as anonymised busy blocks.",
        formatter_class=DefaultsHelpFormatter,
    )
    parser.add_argument(
        "--list-calendars",
        action="store_true",
        help="list all local calendar titles (qualified account.calendar names) and exit",
    )
    parser.add_argument(
        "--title",
        default=defaults.title,
        help="title template used for every mirror block",
    )
    parser.add_argument(
        "--title-to",
        nargs=2,
        action=CollectMapping,
        default=defaults.title_to,
        metavar=("ACCOUNT", "TEMPLATE"),
        help="title template to use when writing into ACCOUNT's calendar, overriding --title; repeatable",
    )
    parser.add_argument(
        "--title-from",
        nargs=2,
        action=CollectMapping,
        default=defaults.title_from,
        metavar=("ACCOUNT", "TEMPLATE"),
        help="title template for events read from ACCOUNT's calendar, overriding both --title and --title-to; repeatable",
    )
    parser.add_argument(
        "--lookback",
        type=int,
        default=defaults.lookback,
        help="days before now to mirror; with --cleanup, the window within which finished events are removed",
    )
    parser.add_argument(
        "--lookahead",
        type=int,
        default=defaults.lookahead,
        help="days after now to mirror events",
    )
    parser.add_argument(
        "--cleanup",
        action=BooleanOptionalAction,
        default=defaults.cleanup,
        help="remove mirror blocks once their event is over, instead of keeping them through the lookback window",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=defaults.dry_run,
        help="report the plan without writing anything",
    )
    parser.add_argument(
        "--install",
        type=int,
        metavar="SECONDS",
        help="install a launchd agent that runs this same command every SECONDS seconds, then exit",
    )
    parser.add_argument("--uninstall", action="store_true", help="remove the installed launchd agent and exit")
    parser.add_argument("--logging", default="info", help="set the logging level")
    parser.add_argument(
        "--exclude-patterns",
        nargs="+",
        action=CompilePatterns,
        default=defaults.exclude_patterns,
        metavar="REGEX",
        help="exclude calendar events with titles that match any of these patterns",
    )
    parser.add_argument(
        "--calendar-include-patterns",
        nargs="+",
        action=CollectCompilePatterns,
        default=defaults.calendar_include_patterns,
        metavar=("CALENDAR", "REGEX"),
        help=(
            "mirror only events from CALENDAR whose title matches one of the given patterns, a per-calendar "
            "whitelist; repeatable to whitelist several calendars (default: None)"
        ),
    )
    parser.add_argument(
        "--statuses",
        nargs="+",
        type=Participation,
        action=CollectSet,
        default=defaults.statuses,
        metavar="STATUS",
        help=(
            f"participation responses that count as busy and get mirrored, from {{{values_string(Participation)}}} "
            f"(default: {values_string(defaults.statuses)})"
        ),
    )
    parser.add_argument(
        "--exclude-clashes",
        action=BooleanOptionalAction,
        default=defaults.exclude_clashes,
        help="skip a source event when the target is already busy over any part of its slot",
    )
    parser.add_argument(
        "--exclude-all-day",
        action=BooleanOptionalAction,
        default=defaults.exclude_all_day,
        help="skip all-day events",
    )
    parser.add_argument(
        "--exclude-out-of-hours",
        action=BooleanOptionalAction,
        default=defaults.exclude_out_of_hours,
        help="skip events that fall entirely outside working hours (Mon-Fri 08:00-18:00)",
    )
    parser.add_argument(
        "--mute",
        dest="muted",
        nargs="+",
        action=CollectSet,
        default=defaults.muted,
        metavar="CALENDAR",
        help="calendar names that should not be mirrored to; their viewers won't see the mirrored busy blocks (default: None)",
    )
    parser.add_argument(
        "calendars",
        nargs="*",
        help="calendars to mirror; the first is the primary calendar that every auxiliary is mirrored into and back out from",
    )
    options = parser.parse_args(arguments)
    # --list-calendars and --uninstall stand alone; a sync or an install needs a primary and at least one auxiliary.
    if len(options.calendars) <= 1 and not (options.list_calendars or options.uninstall):
        parser.error("at least two calendars are required: a primary and some auxiliary calendars to mirror with")
    return options


def to_config(options: Namespace) -> Config:
    """Project the parsed options onto the configuration fields they share a name with.

    The parser is responsible for giving every shared option its final type, so this mapping
    stays uniform: a new option needs only to match on name.
    """
    return Config(
        **{field.name: getattr(options, field.name) for field in fields(Config) if hasattr(options, field.name)}
    )


def main(arguments: list[str] | None = None) -> int:
    """Dispatch one calque invocation — list, install, uninstall, or sync — and return a process exit code."""
    arguments = sys.argv[1:] if arguments is None else arguments
    options = parse_arguments(arguments)
    logging.basicConfig(level=options.logging.upper(), format="%(asctime)s:%(levelname)s: %(message)s")

    try:
        if options.list_calendars:
            for name in CalendarStore().qualified_names():
                print(name)
        elif options.install is not None:
            install(arguments, options.install)
        elif options.uninstall:
            uninstall()
        else:
            synchronise(to_config(options), options.calendars)
    except CalqueError as exception:
        logging.error("calque failed: %s", exception)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
