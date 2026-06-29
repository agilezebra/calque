"""Tests for the composable exclusion rules and their assembly into a chain."""

import re
import time as clock
from collections.abc import Iterator
from datetime import UTC, datetime, time, timedelta

import pytest

from calque.config import Config
from calque.exclusions import (
    by_clash,
    by_hours,
    by_origin,
    by_participation,
    by_passed,
    by_title,
    excluded,
    included,
    is_all_day,
    is_cancelled,
    rules,
    unlisted,
)
from calque.model import Event, Participation, Status, Window, tag

WORK_DAYS = frozenset({0, 1, 2, 3, 4})
SOURCE = "Source.Calendar"
TARGET = "Target.Calendar"


@pytest.fixture(autouse=True)
def local_utc(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Pin the local timezone to UTC so working-hours rules are deterministic."""
    monkeypatch.setenv("TZ", "UTC")
    clock.tzset()
    yield
    clock.tzset()


@pytest.fixture
def start() -> datetime:
    return datetime(2026, 6, 5, 9, 0, tzinfo=UTC)


def event(
    title: str,
    start: datetime,
    hours: float = 1.0,
    *,
    all_day: bool = False,
    participation: Participation = Participation.ACCEPTED,
    status: Status = Status.CONFIRMED,
    notes: str | None = None,
) -> Event:
    window = Window(start, start + timedelta(hours=hours))
    return Event(
        identifier="id",
        title=title,
        account="Client",
        window=window,
        all_day=all_day,
        participation=participation,
        status=status,
        notes=notes,
    )


def test_by_title_matches_any_pattern(start: datetime) -> None:
    rule = by_title((re.compile(r"^Working$"), re.compile(r"\bA/L\b")))
    assert rule(event("Working", start))
    assert rule(event("Booked A/L", start))
    assert not rule(event("Working lunch", start))
    assert not rule(event("Standup", start))


def test_unlisted_excludes_titles_matching_no_pattern(start: datetime) -> None:
    rule = unlisted((re.compile(r"graham busy"), re.compile(r"\bGJ\b")))
    assert rule(event("Lunch", start))
    assert rule(event("Dentist", start))
    assert not rule(event("House Viewing (graham busy)", start))
    assert not rule(event("School run GJ", start))


def test_rules_whitelists_only_listed_events_from_the_source(start: datetime) -> None:
    config = Config(calendar_include_patterns={"Home.Shared": (re.compile(r"graham busy"),)}, exclude_clashes=False)
    exclusions = rules(config, (), "Home.Shared", TARGET)
    assert excluded(event("Swimming lesson", start), exclusions)
    assert not excluded(event("House Viewing (graham busy)", start), exclusions)


def test_rules_leaves_a_source_without_include_patterns_unfiltered(start: datetime) -> None:
    config = Config(calendar_include_patterns={"Home.Shared": (re.compile(r"graham busy"),)}, exclude_clashes=False)
    exclusions = rules(config, (), "Work.Office", TARGET)
    assert not excluded(event("Swimming lesson", start), exclusions)


def test_rules_whitelist_does_not_filter_target_busy_periods(start: datetime) -> None:
    # The whitelist is keyed on the source, so a target busy period that the source would not list
    # still counts as busy and blocks an overlapping listed source event from being mirrored in.
    config = Config(calendar_include_patterns={"Home.Shared": (re.compile(r"graham busy"),)})
    exclusions = rules(config, (event("Team meeting", start),), "Home.Shared", TARGET)
    assert excluded(event("Viewing (graham busy)", start), exclusions)


def test_by_clash_excludes_any_overlap(start: datetime) -> None:
    rule = by_clash((event("busy", start),))
    assert rule(event("exact", start))
    assert rule(event("starts inside", start + timedelta(minutes=30)))
    assert rule(event("ends inside", start - timedelta(minutes=30)))
    assert rule(event("envelops", start - timedelta(hours=1), hours=3))


def test_by_clash_allows_adjacent_and_free(start: datetime) -> None:
    rule = by_clash((event("busy", start),))
    assert not rule(event("touches end", start + timedelta(hours=1)))
    assert not rule(event("touches start", start - timedelta(hours=1)))
    assert not rule(event("elsewhere", start + timedelta(hours=5)))


def test_chain_adds_clash_rule_when_enabled(start: datetime) -> None:
    exclusions = rules(Config(exclude_patterns=(), exclude_clashes=True), (event("meeting", start),), SOURCE, TARGET)
    assert excluded(event("meeting", start), exclusions)


def test_chain_omits_clash_rule_when_disabled(start: datetime) -> None:
    exclusions = rules(Config(exclude_patterns=(), exclude_clashes=False), (event("meeting", start),), SOURCE, TARGET)
    assert not excluded(event("meeting", start), exclusions)


def test_chain_always_applies_title_rules(start: datetime) -> None:
    exclusions = rules(Config(exclude_clashes=False), (), SOURCE, TARGET)
    assert excluded(event("Working", start), exclusions)
    assert not excluded(event("Standup", start), exclusions)


def test_rules_ignores_busy_periods_that_are_themselves_excluded(start: datetime) -> None:
    # A "Working" focus block in the target matches the title patterns, so it is not treated as
    # busy and does not block an overlapping source event from being mirrored in.
    exclusions = rules(Config(), (event("Working", start),), SOURCE, TARGET)
    assert not excluded(event("Standup", start), exclusions)


def test_excluded_is_false_for_empty_chain(start: datetime) -> None:
    assert not excluded(event("anything", start), [])


def test_included_keeps_only_events_no_rule_rejects(start: datetime) -> None:
    exclusions = rules(Config(exclude_clashes=False), (), SOURCE, TARGET)
    events = [event("Working", start), event("Sprint planning", start)]
    assert [kept.title for kept in included(events, exclusions)] == ["Sprint planning"]


def test_by_hours_keeps_events_inside_the_window(start: datetime) -> None:
    rule = by_hours(WORK_DAYS, time(8), time(18))
    assert not rule(event("standup", start))  # Friday 09:00-10:00


def test_by_hours_excludes_events_before_and_after_the_window() -> None:
    rule = by_hours(WORK_DAYS, time(8), time(18))
    assert rule(event("early", datetime(2026, 6, 5, 6, 0, tzinfo=UTC)))  # 06:00-07:00 Fri
    assert rule(event("late", datetime(2026, 6, 5, 18, 0, tzinfo=UTC)))  # 18:00-19:00 Fri


def test_by_hours_keeps_events_straddling_the_edge() -> None:
    rule = by_hours(WORK_DAYS, time(8), time(18))
    assert not rule(event("overrun", datetime(2026, 6, 5, 17, 0, tzinfo=UTC), hours=2))  # 17:00-19:00 Fri


def test_by_hours_excludes_events_on_non_working_days() -> None:
    rule = by_hours(WORK_DAYS, time(8), time(18))
    assert rule(event("weekend", datetime(2026, 6, 6, 9, 0, tzinfo=UTC)))  # Saturday 09:00


def test_is_cancelled_excludes_only_cancelled_events(start: datetime) -> None:
    assert is_cancelled(event("called off", start, status=Status.CANCELLED))
    assert not is_cancelled(event("on", start, status=Status.CONFIRMED))


def test_rules_excludes_cancelled_source_events(start: datetime) -> None:
    exclusions = rules(Config(exclude_clashes=False), (), SOURCE, TARGET)
    assert excluded(event("Canceled: Standup", start, status=Status.CANCELLED), exclusions)
    assert not excluded(event("Standup", start, status=Status.CONFIRMED), exclusions)


def test_rules_ignores_cancelled_busy_periods(start: datetime) -> None:
    # A cancelled event in the target is not genuine busy, so it does not block a source event.
    cancelled = event("Canceled: Workshop", start, status=Status.CANCELLED)
    exclusions = rules(Config(), (cancelled,), SOURCE, TARGET)
    assert not excluded(event("Standup", start), exclusions)


def test_by_passed_excludes_only_finished_events() -> None:
    # The rule reads the wall clock when it is built, so events are positioned relative to it.
    now = datetime.now(UTC)
    rule = by_passed()
    assert rule(event("over", now - timedelta(hours=2)))  # ended an hour ago
    assert not rule(event("ongoing", now - timedelta(minutes=30), hours=2))  # ends in the future
    assert not rule(event("ahead", now + timedelta(hours=2)))


def test_rules_drops_finished_events_when_cleanup_enabled() -> None:
    now = datetime.now(UTC)
    exclusions = rules(Config(cleanup=True, exclude_clashes=False, exclude_out_of_hours=False), (), SOURCE, TARGET)
    assert excluded(event("over", now - timedelta(hours=2)), exclusions)
    assert not excluded(event("ahead", now + timedelta(hours=2)), exclusions)


def test_rules_keeps_finished_events_without_cleanup() -> None:
    now = datetime.now(UTC)
    exclusions = rules(Config(exclude_clashes=False, exclude_out_of_hours=False), (), SOURCE, TARGET)
    assert not excluded(event("over", now - timedelta(hours=2)), exclusions)


def test_by_origin_excludes_only_mirrors_returning_to_the_target(start: datetime) -> None:
    rule = by_origin("ClientA.Calendar")
    assert rule(event("bounce", start, notes=tag("ClientA.Calendar", "id")))
    assert not rule(event("onward", start, notes=tag("ClientB.Calendar", "id")))
    assert not rule(event("genuine", start, notes="just some notes"))
    assert not rule(event("blank", start))


def test_rules_excludes_a_mirror_only_when_it_would_return_to_its_origin(start: datetime) -> None:
    # A block this sync wrote into ClientA from ClientA must never be mirrored back (a mirror of a mirror)...
    exclusions = rules(Config(exclude_clashes=False), (), SOURCE, "ClientA.Calendar")
    assert excluded(event("ClientA: Follow Up", start, notes=tag("ClientA.Calendar", "id")), exclusions)
    # ...but a block sourced from another client still propagates onward to ClientA.
    assert not excluded(event("ClientB busy", start, notes=tag("ClientB.Calendar", "id")), exclusions)


def test_is_all_day_excludes_only_all_day_events(start: datetime) -> None:
    assert is_all_day(event("holiday", start, all_day=True))
    assert not is_all_day(event("meeting", start))


def test_by_participation_excludes_unmirrored_statuses(start: datetime) -> None:
    rule = by_participation(frozenset({Participation.ACCEPTED}))
    assert not rule(event("accepted", start, participation=Participation.ACCEPTED))
    assert rule(event("tentative", start, participation=Participation.TENTATIVE))


def test_rules_excludes_source_events_by_participation(start: datetime) -> None:
    exclusions = rules(Config(statuses=frozenset({Participation.ACCEPTED, Participation.UNKNOWN})), (), SOURCE, TARGET)
    assert excluded(event("tentative", start, participation=Participation.TENTATIVE), exclusions)
    assert not excluded(event("accepted", start), exclusions)
    assert not excluded(event("unknown", start, participation=Participation.UNKNOWN), exclusions)


def test_rules_ignores_busy_periods_with_unmirrored_participation(start: datetime) -> None:
    # A declined block in the target is not genuine busy, so it does not block a source event.
    declined = event("declined block", start, participation=Participation.DECLINED)
    exclusions = rules(
        Config(statuses=frozenset({Participation.ACCEPTED, Participation.UNKNOWN})), (declined,), SOURCE, TARGET
    )
    assert not excluded(event("Standup", start), exclusions)


def test_rules_gates_all_day_and_out_of_hours(start: datetime) -> None:
    enabled = rules(Config(exclude_patterns=(), exclude_clashes=False), (), SOURCE, TARGET)
    assert excluded(event("holiday", start, all_day=True), enabled)
    assert excluded(event("weekend", datetime(2026, 6, 6, 9, 0, tzinfo=UTC)), enabled)

    disabled = rules(
        Config(exclude_patterns=(), exclude_clashes=False, exclude_all_day=False, exclude_out_of_hours=False),
        (),
        SOURCE,
        TARGET,
    )
    assert not excluded(event("weekend holiday", datetime(2026, 6, 6, 9, 0, tzinfo=UTC), all_day=True), disabled)
