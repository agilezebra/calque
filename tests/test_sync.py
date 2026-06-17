"""Tests for the reconciliation core, a single mirror pass, and the both-ways synchronisation run."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, call

import pytest

from calque import sync
from calque.config import Config
from calque.model import Event, Mirror, Participation, Status, Window
from calque.sync import mirror, reconcile, synchronise, to_mirrors


@pytest.fixture
def start() -> datetime:
    return datetime(2026, 6, 5, 9, 0, tzinfo=UTC)


def event(identifier: str, start: datetime, participation: Participation = Participation.ACCEPTED) -> Event:
    return Event(
        identifier=identifier,
        title=identifier,
        account="Client",
        window=Window(start, start + timedelta(hours=1)),
        all_day=False,
        participation=participation,
        status=Status.CONFIRMED,
    )


def block(identifier: str, start: datetime, title: str = "Busy") -> Mirror:
    return Mirror(identifier, Window(start, start + timedelta(hours=1)), title)


def test_to_mirrors_keys_every_event_by_identifier(start: datetime) -> None:
    # No participation filtering here — that is now an exclusion rule applied before this step.
    events = [event("a", start), event("b", start, Participation.DECLINED)]
    assert set(to_mirrors(events, "Busy", "Client.Calendar")) == {"a", "b"}


def test_to_mirrors_anonymises_to_the_given_template(start: datetime) -> None:
    selected = to_mirrors([event("one", start)], "Unavailable", "Client.Calendar")
    assert selected["one"].title == "Unavailable"


def test_to_mirrors_records_the_origin_calendar(start: datetime) -> None:
    selected = to_mirrors([event("one", start)], "Busy", "Client.Calendar")
    assert selected["one"].origin == "Client.Calendar"


def test_to_mirrors_fills_template_placeholders_from_the_event(start: datetime) -> None:
    selected = to_mirrors([event("standup", start)], "{account}: {title}", "Client.Calendar")
    assert selected["standup"].title == "Client: standup"


def test_reconcile_creates_missing(start: datetime) -> None:
    plan = reconcile({"one": block("one", start)}, {})
    assert plan.create == (block("one", start),)
    assert not plan.update
    assert not plan.delete


def test_reconcile_deletes_orphans(start: datetime) -> None:
    plan = reconcile({}, {"gone": block("gone", start)})
    assert plan.delete == (block("gone", start),)


def test_reconcile_updates_when_times_move(start: datetime) -> None:
    desired = {"one": block("one", start + timedelta(hours=2))}
    existing = {"one": block("one", start)}
    plan = reconcile(desired, existing)
    assert plan.update == (block("one", start + timedelta(hours=2)),)


def test_reconcile_leaves_unchanged_alone(start: datetime) -> None:
    same = {"one": block("one", start)}
    assert reconcile(same, dict(same)).empty


def calendar(qualified: str) -> Mock:
    """A stand-in calendar reporting no events, no busy periods, and no existing mirrors."""
    return Mock(qualified=qualified, **{"events.return_value": [], "busy.return_value": [], "mirrors.return_value": {}})


def test_mirror_applies_the_plan_to_the_target(start: datetime) -> None:
    source, target = calendar("Personal.Home"), calendar("Work.Office")
    window = Window(start, start + timedelta(days=1))
    mirror(source, target, Config(), window)
    target.apply.assert_called_once()
    plan, applied_window = target.apply.call_args.args
    assert plan.empty
    assert applied_window is window


def test_mirror_reconciles_only_against_blocks_from_this_source(start: datetime) -> None:
    # The existing set must be scoped to the source's origin, so another source's blocks in the
    # target are never seen as orphans and deleted.
    source, target = calendar("Personal.Home"), calendar("Work.Office")
    window = Window(start, start + timedelta(days=1))
    mirror(source, target, Config(), window)
    target.mirrors.assert_called_once_with(window, "Personal.Home")


def test_mirror_writes_nothing_on_a_dry_run(start: datetime) -> None:
    source, target = calendar("Personal.Home"), calendar("Work.Office")
    mirror(source, target, Config(dry_run=True), Window(start, start + timedelta(days=1)))
    target.apply.assert_not_called()


def test_mirror_deletes_finished_blocks_when_cleanup_enabled() -> None:
    # With cleanup on, a source event that is already over drops out of the desired set, so
    # reconciliation deletes its stale mirror while an event still to come is left in place.
    # The cut-off is the wall clock, so the events are positioned relative to it.
    now = datetime.now(UTC)
    over = event("over", now - timedelta(hours=2))
    ahead = event("ahead", now + timedelta(hours=2))
    source = Mock(
        qualified="Personal.Home",
        **{"events.return_value": [over, ahead], "busy.return_value": [], "mirrors.return_value": {}},
    )
    target = Mock(
        qualified="Work.Office",
        **{
            "events.return_value": [],
            "busy.return_value": [],
            "mirrors.return_value": {
                "over": block("over", now - timedelta(hours=2)),
                "ahead": block("ahead", now + timedelta(hours=2)),
            },
        },
    )
    mirror(source, target, Config(cleanup=True, exclude_out_of_hours=False), Window(now - timedelta(days=1), now))
    plan = target.apply.call_args.args[0]
    assert [removed.source for removed in plan.delete] == ["over"]
    assert not plan.create


def test_synchronise_collects_each_auxiliary_into_the_primary_then_fans_out(monkeypatch: pytest.MonkeyPatch) -> None:
    resolved = {title: calendar(title) for title in ("Personal", "Work", "Side")}
    monkeypatch.setattr(sync, "CalendarStore", Mock(return_value=Mock(calendar=lambda title: resolved[title])))
    passes = Mock()
    monkeypatch.setattr(sync, "mirror", passes)
    config = Config()
    synchronise(config, ["Personal", "Work", "Side"])
    assert passes.call_count == 4  # two auxiliaries collected into the primary, then fanned back out
    primary, window = resolved["Personal"], passes.call_args.args[3]
    passes.assert_any_call(resolved["Work"], primary, config, window)
    passes.assert_any_call(resolved["Side"], primary, config, window)
    passes.assert_any_call(primary, resolved["Work"], config, window)
    passes.assert_any_call(primary, resolved["Side"], config, window)


def test_synchronise_does_not_fan_out_to_a_muted_calendar(monkeypatch: pytest.MonkeyPatch) -> None:
    resolved = {title: calendar(title) for title in ("Personal", "Work", "Side")}
    monkeypatch.setattr(sync, "CalendarStore", Mock(return_value=Mock(calendar=lambda title: resolved[title])))
    passes = Mock()
    monkeypatch.setattr(sync, "mirror", passes)
    config = Config(muted=frozenset({"Side"}))
    synchronise(config, ["Personal", "Work", "Side"])
    primary, window = resolved["Personal"], passes.call_args.args[3]
    # Side is still collected into the primary, but the primary is never mirrored back out to it.
    passes.assert_any_call(resolved["Side"], primary, config, window)
    assert call(primary, resolved["Side"], config, window) not in passes.call_args_list


def test_synchronise_muting_the_primary_skips_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    resolved = {title: calendar(title) for title in ("Personal", "Work")}
    monkeypatch.setattr(sync, "CalendarStore", Mock(return_value=Mock(calendar=lambda title: resolved[title])))
    passes = Mock()
    monkeypatch.setattr(sync, "mirror", passes)
    config = Config(muted=frozenset({"Personal"}))
    synchronise(config, ["Personal", "Work"])
    # Nothing is mirrored into the primary; it is only fanned out to the auxiliary.
    passes.assert_called_once_with(resolved["Personal"], resolved["Work"], config, passes.call_args.args[3])
