"""Tests for the domain model: marker encoding, time rendering, and plan reporting."""

import logging
import time as clock
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest

from calque.model import MARKER, Event, Mirror, Participation, Plan, Status, Tag, Window, tag, untag


@pytest.fixture(autouse=True)
def local_utc(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Pin the local timezone to UTC so local-time rendering is deterministic."""
    monkeypatch.setenv("TZ", "UTC")
    clock.tzset()
    yield
    clock.tzset()


@pytest.fixture
def start() -> datetime:
    return datetime(2026, 6, 5, 9, 0, tzinfo=UTC)


def window(start: datetime, hours: float = 1.0) -> Window:
    return Window(start, start + timedelta(hours=hours))


def test_tag_then_untag_roundtrips() -> None:
    assert untag(tag("Work.Office", "ABC-123")) == Tag(origin="Work.Office", identifier="ABC-123")


def test_tag_roundtrips_an_origin_containing_spaces() -> None:
    # The identifier has no spaces, so splitting on the first space keeps a spaced account name intact.
    assert untag(tag("Example Team.Calendar", "ABC-123")) == Tag(origin="Example Team.Calendar", identifier="ABC-123")


def test_untag_ignores_foreign_notes() -> None:
    assert untag("a normal meeting note") is None


def test_untag_handles_missing_notes() -> None:
    assert untag(None) is None


def test_untag_rejects_marker_with_no_identifier() -> None:
    assert untag(MARKER) is None


def test_window_renders_a_same_day_range_without_repeating_the_date(start: datetime) -> None:
    assert str(window(start)) == "Fri 2026-06-05 09:00 to 10:00"


def test_window_renders_a_cross_day_range_with_the_end_date(start: datetime) -> None:
    assert str(Window(start, start + timedelta(days=2))) == "Fri 2026-06-05 09:00 to Sun 2026-06-07 09:00"


def test_event_exposes_window_bounds_and_renders(start: datetime) -> None:
    event = Event(
        identifier="id",
        title="Standup",
        account="Client",
        window=window(start),
        all_day=False,
        participation=Participation.ACCEPTED,
        status=Status.CONFIRMED,
    )
    assert event.start == start
    assert event.end == start + timedelta(hours=1)
    assert str(event) == "title='Standup' window=Fri 2026-06-05 09:00 to 10:00 status=confirmed participation=accepted"


def test_mirror_exposes_window_bounds_and_renders(start: datetime) -> None:
    mirror = Mirror("id", window(start), "Busy", original="Standup")
    assert mirror.start == start
    assert mirror.end == start + timedelta(hours=1)
    assert str(mirror) == "title='Busy' original='Standup' window=Fri 2026-06-05 09:00 to 10:00 source='id'"


def test_plan_summary_counts_each_bucket(start: datetime) -> None:
    mirror = Mirror("id", window(start), "Busy")
    plan = Plan(create=(mirror,), update=(), delete=(mirror, mirror))
    assert not plan.empty
    assert str(plan) == "create=1 update=0 delete=2"


def test_plan_log_emits_every_block(start: datetime, caplog: pytest.LogCaptureFixture) -> None:
    plan = Plan(
        create=(Mirror("c", window(start), "Created"),),
        update=(Mirror("u", window(start), "Updated"),),
        delete=(Mirror("d", window(start), "Deleted"),),
    )
    with caplog.at_level(logging.INFO):
        plan.log()
    logged = caplog.text
    assert "Created" in logged
    assert "Updated" in logged
    assert "Deleted" in logged
