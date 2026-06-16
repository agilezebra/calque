"""Tests for the EventKit boundary: conversions, access, and calendar read/write operations.

PyObjC objects are stand-in mocks; the few operations that reach for an EventKit class method or
constructor get a minimal namespace swapped in for that call, leaving the real participation
constants intact for the pure conversion tests.
"""

import types
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import EventKit
import pytest

from calque import store
from calque.errors import AccessError, CalendarError, WriteError
from calque.model import Mirror, Participation, Plan, Tag, Window, tag


@pytest.fixture
def start() -> datetime:
    return datetime(2026, 6, 5, 9, 0, tzinfo=UTC)


def window(start: datetime, hours: float = 1.0) -> Window:
    return Window(start, start + timedelta(hours=hours))


def stub_event(window: Window, **fields: object) -> Mock:
    """A mock EventKit event whose accessors return the given fields with sensible defaults."""
    item = Mock()
    item.startDate.return_value = store.to_nsdate(window.start)
    item.endDate.return_value = store.to_nsdate(window.end)
    item.eventIdentifier.return_value = fields.get("identifier", "event-1")
    item.title.return_value = fields.get("title", "Meeting")
    item.attendees.return_value = fields.get("attendees")
    item.isAllDay.return_value = fields.get("all_day", False)
    item.notes.return_value = fields.get("notes")
    return item


def attendee(*, current: bool, status: int = EventKit.EKParticipantStatusAccepted) -> Mock:
    """A mock attendee reporting whether it is the current user and its participation status."""
    return Mock(**{"isCurrentUser.return_value": current, "participantStatus.return_value": status})


def detached_store(native: object) -> store.CalendarStore:
    """A CalendarStore bound to a mock native store, bypassing the access-gated constructor."""
    instance = store.CalendarStore.__new__(store.CalendarStore)
    instance.store = native
    return instance


def test_nsdate_roundtrips_through_a_utc_datetime(start: datetime) -> None:
    assert store.to_datetime(store.to_nsdate(start)) == start


def test_to_window_spans_the_events_start_and_end(start: datetime) -> None:
    assert store.to_window(stub_event(window(start))) == window(start)


def test_to_event_folds_the_occurrence_start_into_the_identifier(start: datetime) -> None:
    event = store.to_event(stub_event(window(start), identifier="abc", title="Standup"), "Client")
    assert event.identifier.startswith("abc@")
    assert event.title == "Standup"
    assert event.account == "Client"
    assert event.window == window(start)


def test_to_event_substitutes_an_empty_title_when_absent(start: datetime) -> None:
    assert store.to_event(stub_event(window(start), title=None), "Client").title == ""


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (EventKit.EKParticipantStatusAccepted, Participation.ACCEPTED),
        (EventKit.EKParticipantStatusTentative, Participation.TENTATIVE),
        (EventKit.EKParticipantStatusDeclined, Participation.DECLINED),
        (EventKit.EKParticipantStatusPending, Participation.PENDING),
        (EventKit.EKParticipantStatusUnknown, Participation.UNKNOWN),
    ],
)
def test_to_participation_maps_each_status(status: int, expected: Participation) -> None:
    assert store.to_participation(status) == expected


def test_response_treats_an_empty_attendee_list_as_accepted(start: datetime) -> None:
    assert store.response(stub_event(window(start), attendees=None)) == Participation.ACCEPTED


def test_response_reads_the_current_users_status(start: datetime) -> None:
    item = stub_event(window(start), attendees=[attendee(current=False), attendee(current=True)])
    assert store.response(item) == Participation.ACCEPTED


def test_response_is_unknown_when_the_user_is_not_an_attendee(start: datetime) -> None:
    assert store.response(stub_event(window(start), attendees=[attendee(current=False)])) == Participation.UNKNOWN


def fake_eventkit(monkeypatch: pytest.MonkeyPatch, **attributes: object) -> None:
    """Swap a minimal EventKit namespace into the store module for one test."""
    monkeypatch.setattr(store, "EventKit", types.SimpleNamespace(**attributes))


def test_request_access_returns_when_full_access_is_already_granted(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_eventkit(
        monkeypatch,
        EKEntityTypeEvent=0,
        EKAuthorizationStatusFullAccess=3,
        EKEventStore=types.SimpleNamespace(authorizationStatusForEntityType_=lambda _entity: 3),
    )
    native = Mock()
    store.request_access(native)
    native.requestFullAccessToEventsWithCompletion_.assert_not_called()


def test_request_access_returns_when_the_user_grants_access(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_eventkit(
        monkeypatch,
        EKEntityTypeEvent=0,
        EKAuthorizationStatusFullAccess=3,
        EKEventStore=types.SimpleNamespace(authorizationStatusForEntityType_=lambda _entity: 0),
    )
    native = Mock(requestFullAccessToEventsWithCompletion_=lambda handler: handler(True, None))  # noqa: FBT003
    store.request_access(native)


def test_request_access_raises_when_the_user_denies(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_eventkit(
        monkeypatch,
        EKEntityTypeEvent=0,
        EKAuthorizationStatusFullAccess=3,
        EKEventStore=types.SimpleNamespace(authorizationStatusForEntityType_=lambda _entity: 0),
    )
    native = Mock(requestFullAccessToEventsWithCompletion_=lambda handler: handler(False, "refused"))  # noqa: FBT003
    with pytest.raises(AccessError):
        store.request_access(native)


def test_request_access_raises_when_the_decision_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_eventkit(
        monkeypatch,
        EKEntityTypeEvent=0,
        EKAuthorizationStatusFullAccess=3,
        EKEventStore=types.SimpleNamespace(authorizationStatusForEntityType_=lambda _entity: 0),
    )
    native = Mock(requestFullAccessToEventsWithCompletion_=lambda _handler: None)
    with pytest.raises(AccessError):
        store.request_access(native, timeout=0.01)


def test_calendar_store_creates_the_event_store_and_requests_access(monkeypatch: pytest.MonkeyPatch) -> None:
    native = Mock()
    fake_eventkit(
        monkeypatch,
        EKEventStore=types.SimpleNamespace(alloc=lambda: types.SimpleNamespace(init=lambda: native)),
    )
    granted = Mock()
    monkeypatch.setattr(store, "request_access", granted)
    instance = store.CalendarStore()
    assert instance.store is native
    granted.assert_called_once_with(native)


def calendar_named(account: str, title: str) -> Mock:
    """A mock native EKCalendar reporting the given account and own title."""
    return Mock(**{"source.return_value.title.return_value": account, "title.return_value": title})


def test_qualified_names_are_sorted() -> None:
    native = Mock()
    native.calendarsForEntityType_.return_value = [calendar_named("Work", "Office"), calendar_named("Home", "Personal")]
    assert detached_store(native).qualified_names() == ["Home.Personal", "Work.Office"]


def test_calendar_matches_a_qualified_title() -> None:
    native = Mock()
    native.calendarsForEntityType_.return_value = [calendar_named("Work", "Office")]
    found = detached_store(native).calendar("Work.Office")
    assert found.qualified == "Work.Office"


def test_calendar_raises_when_no_title_matches() -> None:
    native = Mock()
    native.calendarsForEntityType_.return_value = [calendar_named("Work", "Office")]
    with pytest.raises(CalendarError):
        detached_store(native).calendar("Missing")


def test_fetch_yields_events_matching_the_window_predicate(start: datetime) -> None:
    native = Mock()
    matched = [stub_event(window(start))]
    native.eventsMatchingPredicate_.return_value = matched
    calendar = store.Calendar(detached_store(native), Mock(), "Work.Office")
    assert list(calendar.store.fetch(calendar, window(start))) == matched


def test_build_event_tags_an_anonymised_block(monkeypatch: pytest.MonkeyPatch, start: datetime) -> None:
    created = Mock()
    fake_eventkit(
        monkeypatch,
        EKEvent=types.SimpleNamespace(eventWithEventStore_=lambda _store: created),
    )
    calendar = store.Calendar(detached_store(Mock()), Mock(), "Work.Office")
    mirror = Mirror("source-1", window(start), "Busy", origin="Personal.Home")
    built = calendar.store.build_event(mirror, calendar)
    assert built is created
    created.setTitle_.assert_called_once_with("Busy")
    created.setNotes_.assert_called_once_with(tag("Personal.Home", "source-1"))


def test_set_times_writes_the_mirror_bounds(start: datetime) -> None:
    event = Mock()
    mirror = Mirror("source-1", window(start), "Busy")
    assert detached_store(Mock()).set_times(event, mirror) is event
    event.setStartDate_.assert_called_once()
    event.setEndDate_.assert_called_once()


def test_save_persists_a_successful_write() -> None:
    native = Mock()
    native.saveEvent_span_error_.return_value = (True, None)
    detached_store(native).save(Mock())
    native.saveEvent_span_error_.assert_called_once()


def test_save_raises_when_the_write_fails() -> None:
    native = Mock()
    native.saveEvent_span_error_.return_value = (False, "rejected")
    with pytest.raises(WriteError):
        detached_store(native).save(Mock())


def test_remove_deletes_a_successful_block() -> None:
    native = Mock()
    native.removeEvent_span_error_.return_value = (True, None)
    detached_store(native).remove(Mock())
    native.removeEvent_span_error_.assert_called_once()


def test_remove_raises_when_the_delete_fails() -> None:
    native = Mock()
    native.removeEvent_span_error_.return_value = (False, "rejected")
    with pytest.raises(WriteError):
        detached_store(native).remove(Mock())


def calendar_with(native_store: Mock, account: str = "Client") -> store.Calendar:
    """A Calendar over a mock native store whose source reports the given account."""
    native = Mock(**{"source.return_value.title.return_value": account})
    return store.Calendar(detached_store(native_store), native, "Work.Office")


def test_calendar_title_and_source_delegate_to_the_native_object() -> None:
    native = Mock(**{"title.return_value": "Office"})
    calendar = store.Calendar(detached_store(Mock()), native, "Work.Office")
    assert calendar.title() == "Office"
    assert calendar.source() is native.source.return_value


def test_events_converts_every_fetched_item(start: datetime) -> None:
    native_store = Mock()
    native_store.eventsMatchingPredicate_.return_value = [stub_event(window(start), identifier="a")]
    calendar = calendar_with(native_store)
    events = list(calendar.events(window(start)))
    assert [event.account for event in events] == ["Client"]
    assert events[0].identifier.startswith("a@")


def test_busy_excludes_our_own_mirror_blocks(start: datetime) -> None:
    native_store = Mock()
    native_store.eventsMatchingPredicate_.return_value = [
        stub_event(window(start), identifier="genuine", notes="lunch with team"),
        stub_event(window(start), identifier="ours", notes=tag("Personal.Home", "source-1")),
    ]
    calendar = calendar_with(native_store)
    assert [event.identifier.split("@")[0] for event in calendar.busy(window(start))] == ["genuine"]


def test_tagged_pairs_our_blocks_with_their_tag(start: datetime) -> None:
    ours = stub_event(window(start), notes=tag("Personal.Home", "source-1"))
    native_store = Mock()
    native_store.eventsMatchingPredicate_.return_value = [stub_event(window(start), notes="foreign"), ours]
    calendar = calendar_with(native_store)
    assert list(calendar.tagged(window(start))) == [(Tag(origin="Personal.Home", identifier="source-1"), ours)]


def test_mirrors_reads_back_blocks_keyed_by_source(start: datetime) -> None:
    native_store = Mock()
    native_store.eventsMatchingPredicate_.return_value = [
        stub_event(window(start), title="Busy", notes=tag("Personal.Home", "source-1")),
    ]
    mirrors = calendar_with(native_store).mirrors(window(start), "Personal.Home")
    assert mirrors == {"source-1": Mirror("source-1", window(start), "Busy")}


def test_mirrors_excludes_blocks_from_a_different_origin(start: datetime) -> None:
    # A block another source wrote into this calendar must not appear when reconciling our own origin,
    # or it would be treated as an orphan and deleted.
    native_store = Mock()
    native_store.eventsMatchingPredicate_.return_value = [
        stub_event(window(start), title="Busy", notes=tag("Other.Calendar", "theirs")),
    ]
    assert calendar_with(native_store).mirrors(window(start), "Personal.Home") == {}


def test_apply_creates_updates_and_deletes_against_the_store(monkeypatch: pytest.MonkeyPatch, start: datetime) -> None:
    fake_eventkit(
        monkeypatch,
        EKEvent=types.SimpleNamespace(eventWithEventStore_=lambda _store: Mock()),
        EKSpanThisEvent=EventKit.EKSpanThisEvent,
    )
    existing = stub_event(window(start), notes=tag("Personal.Home", "stays"))
    going = stub_event(window(start), notes=tag("Personal.Home", "gone"))
    native_store = Mock()
    native_store.saveEvent_span_error_.return_value = (True, None)
    native_store.removeEvent_span_error_.return_value = (True, None)
    native_store.eventsMatchingPredicate_.return_value = [existing, going]
    calendar = calendar_with(native_store)
    plan = Plan(
        create=(Mirror("new", window(start), "Busy"),),
        update=(Mirror("stays", window(start, hours=2), "Busy"),),
        delete=(Mirror("gone", window(start), "Busy"),),
    )
    calendar.apply(plan, window(start))
    assert native_store.saveEvent_span_error_.call_count == 2  # one create, one update
    native_store.removeEvent_span_error_.assert_called_once_with(going, EventKit.EKSpanThisEvent, None)
