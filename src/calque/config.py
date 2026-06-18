"""Runtime configuration shared across every mirror direction."""

import re
from dataclasses import dataclass, field
from datetime import time

from calque.model import Participation
from calque.store import Calendar

# Titles that signal availability rather than a genuine commitment: a bare "Working"
# status block, and any annual-leave marker (the "A/L" shorthand).
DEFAULT_EXCLUDES = [r"^Working$", r"\bA/L\b"]


@dataclass(frozen=True, slots=True)
class Config:
    """Settings governing how events are mirrored, independent of direction.

    :param title: The default title template for mirror blocks; ``{field}`` placeholders are
        filled from the source event (e.g. ``{account}``, ``{title}``).
    :param title_to: Title templates keyed by the fully-qualified name of the
        calendar being written into, overriding ``title`` for that target.
    :param title_from: Title templates keyed by the fully-qualified name of the calendar an event was
        read from, overriding ``title`` and any ``title_to`` entry for that source.
    :param lookback: Days before now to keep mirrored, so recently-passed events stay tidy. When
        ``cleanup`` is set, this instead bounds the window within which finished events are removed.
    :param lookahead: Days after now to mirror.
    :param statuses: The participation responses that count as "busy" and get mirrored.
    :param exclude_patterns: Patterns whose match against a source title drops that event from the mirror.
    :param exclude_clashes: Whether to drop a source event that overlaps an existing target event.
    :param exclude_all_day: Whether to drop all-day events.
    :param exclude_out_of_hours: Whether to drop events that fall entirely outside working hours.
    :param work_days: Weekdays (Monday is 0) whose working hours are mirrored.
    :param work_start: Start of the daily working-hours window, in local time.
    :param work_end: End of the daily working-hours window, in local time.
    :param muted: Names of calendars that should not be mirrored to, so their viewers never see the
        mirrored busy blocks; the calendar is still read as a source and mirrored into the others.
    :param cleanup: Whether to remove a mirror block once its event is over (end time has passed),
        rather than keeping it for the ``lookback`` window.
    :param dry_run: Whether to report the plan without writing any changes.
    """

    title: str = "Busy ({account} calendar)"
    title_to: dict[str, str] = field(default_factory=dict)
    title_from: dict[str, str] = field(default_factory=dict)
    lookback: int = 1
    lookahead: int = 60
    statuses: frozenset[Participation] = field(
        default_factory=lambda: frozenset({Participation.ACCEPTED, Participation.UNKNOWN}),
    )
    exclude_patterns: tuple[re.Pattern[str], ...] = field(
        default_factory=lambda: tuple(re.compile(pattern) for pattern in DEFAULT_EXCLUDES),
    )
    exclude_clashes: bool = True
    exclude_all_day: bool = True
    exclude_out_of_hours: bool = True
    work_days: frozenset[int] = frozenset({0, 1, 2, 3, 4})
    work_start: time = time(8)
    work_end: time = time(18)
    muted: frozenset[str] = frozenset()
    cleanup: bool = False
    dry_run: bool = False

    def title_for_calendar(self, source: Calendar, target: Calendar) -> str:
        """Return the title template for mirroring from ``source`` into ``target``, or the default.

        A source override (``title_from``) wins over a target override (``title_to``), so a calendar
        whose events should always be opaque can be pinned once wherever they land. Both are keyed on the
        fully-qualified name (e.g. ``ClientCompany.Calendar``, as shown by ``--list-calendars``).
        """
        return self.title_from.get(source.qualified, self.title_to.get(target.qualified, self.title))
