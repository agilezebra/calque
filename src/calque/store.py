"""EventKit boundary: read a calendar's events and write anonymised busy blocks, all locally.

Every impure interaction with macOS lives here so the reconciliation core stays pure. PyObjC
returns untyped objects, so this module is the one place the type checker is relaxed.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import EventKit
import Foundation

from calque.errors import AccessError, CalendarError, WriteError
from calque.model import Event, Mirror, Participation, Plan, Source, Status, Tag, Window, tag, untag


def to_nsdate(value: datetime) -> Any:
    """Convert a timezone-aware datetime to an ``NSDate``."""
    return Foundation.NSDate.dateWithTimeIntervalSince1970_(value.timestamp())


def to_datetime(value: Any) -> datetime:
    """Convert an ``NSDate`` to a UTC datetime."""
    return datetime.fromtimestamp(value.timeIntervalSince1970(), tz=UTC)


def to_window(event: Any) -> Window:
    """Convert an EventKit event to a Window."""
    return Window(to_datetime(event.startDate()), to_datetime(event.endDate()))


def to_event(item: Any, account: str) -> Event:
    """Convert an EventKit event to an Event for the given account.

    Every occurrence of a recurring event shares one ``eventIdentifier``, so the occurrence
    start is folded into the identifier to keep each instance a distinct mirror block.
    """
    return Event(
        identifier=f"{item.eventIdentifier()}@{int(item.startDate().timeIntervalSince1970())}",
        title=item.title() or "",
        account=account,
        window=to_window(item),
        all_day=bool(item.isAllDay()),
        participation=response(item),
        status=to_status(item.status()),
        notes=item.notes(),
    )


def to_participation(status: int) -> Participation:
    """Map an ``EKParticipantStatus`` code to a participation value."""
    match status:
        case EventKit.EKParticipantStatusAccepted:
            return Participation.ACCEPTED
        case EventKit.EKParticipantStatusTentative:
            return Participation.TENTATIVE
        case EventKit.EKParticipantStatusDeclined:
            return Participation.DECLINED
        case EventKit.EKParticipantStatusPending:
            return Participation.PENDING
        case _:
            return Participation.UNKNOWN


def to_status(status: int) -> Status:
    """Map an ``EKEventStatus`` code to a status value."""
    match status:
        case EventKit.EKEventStatusConfirmed:
            return Status.CONFIRMED
        case EventKit.EKEventStatusTentative:
            return Status.TENTATIVE
        case EventKit.EKEventStatusCanceled:
            return Status.CANCELLED
        case _:
            return Status.NONE


def response(item: Any) -> Participation:
    """Determine the current user's response to an event from their own attendee record."""
    attendee = item.selfAttendee()
    if attendee is not None:
        participation = to_participation(attendee.participantStatus())
        return Participation.PENDING if participation is Participation.UNKNOWN else participation
    return Participation.UNKNOWN if item.hasAttendees() else Participation.ACCEPTED


def qualify(calendar: Any) -> str:
    """The account-qualified name of a native calendar, e.g. ``Work.Calendar``."""
    return f"{calendar.source().title()}.{calendar.title()}"


def request_access(store: Any, *, timeout: float = 30.0) -> None:
    """Block until the user grants full calendar access, raising if denied or timed out."""
    status = EventKit.EKEventStore.authorizationStatusForEntityType_(EventKit.EKEntityTypeEvent)
    if status == EventKit.EKAuthorizationStatusFullAccess:
        return
    outcome: dict[str, object] = {}
    finished = threading.Event()

    def handler(granted: bool, error: Any) -> None:  # noqa: FBT001 - PyObjC callback signature
        """Record the access decision and release the wait."""
        outcome["granted"] = bool(granted)
        outcome["error"] = error
        finished.set()

    store.requestFullAccessToEventsWithCompletion_(handler)
    if not finished.wait(timeout) or not outcome.get("granted"):
        raise AccessError(outcome.get("error") or "timed out")


class Calendar:
    """A calendar in the local store, bound to the store that created it.

    Wraps the untyped PyObjC ``EKCalendar`` (``native``) and exposes the calendar-scoped
    operations the mirror needs, delegating the low-level EventKit work back to the store.
    """

    __slots__ = ("native", "qualified", "store")

    def __init__(self, store: CalendarStore, native: Any, qualified: str) -> None:
        """Bind a native ``EKCalendar`` to the store that produced it."""
        self.store = store
        self.native = native
        self.qualified = qualified

    def title(self) -> str:
        """The calendar's own display title."""
        return self.native.title()

    def source(self) -> Source:
        """The account this calendar belongs to."""
        return self.native.source()

    def events(self, window: Window) -> Iterator[Event]:
        """Yield this calendar's events in the window, reduced to the fields the mirror needs."""
        account = self.source().title()
        return (to_event(item, account) for item in self.store.fetch(self, window))

    def busy(self, window: Window) -> Iterator[Event]:
        """Yield the genuine events here (excluding our own mirror blocks) as candidate busy periods."""
        return (event for event in self.events(window) if untag(event.notes) is None)

    def tagged(self, window: Window) -> Iterator[tuple[Tag, Any]]:
        """Yield our own mirror blocks in the window, paired with their decoded tag."""
        for item in self.store.fetch(self, window):
            marker = untag(item.notes())
            if marker is not None:
                yield marker, item

    def mirrors(self, window: Window, origin: str) -> dict[str, Mirror]:
        """Read back the mirror blocks we wrote here from ``origin``, keyed by source identifier.

        Scoping to one origin keeps reconciliation from treating another source's blocks in this
        calendar as orphans: each source only reconciles against its own blocks.
        """
        return {
            marker.identifier: Mirror(marker.identifier, to_window(item), item.title())
            for marker, item in self.tagged(window)
            if marker.origin == origin
        }

    def apply(self, plan: Plan, window: Window) -> None:
        """Carry out a reconciliation plan against this calendar."""
        handles = {marker.identifier: item for marker, item in self.tagged(window)}
        for mirror in plan.create:
            self.store.save(self.store.build_event(mirror, self))
        for mirror in plan.update:
            self.store.save(self.store.set_times(handles[mirror.source], mirror))
        for mirror in plan.delete:
            self.store.remove(handles[mirror.source])


class CalendarStore:
    """A thin wrapper over an authorised ``EKEventStore`` — the program's one external resource."""

    def __init__(self) -> None:
        """Create the underlying event store and block until the user grants full calendar access."""
        self.store = EventKit.EKEventStore.alloc().init()
        request_access(self.store)

    def qualified_names(self) -> list[str]:
        """Return the account-qualified names of all calendars in the local store, sorted alphabetically."""
        return sorted(qualify(calendar) for calendar in self.store.calendarsForEntityType_(EventKit.EKEntityTypeEvent))

    def calendar(self, name: str) -> Calendar:
        """Return the calendar whose account-qualified name matches exactly, or raise if none does."""
        for calendar in self.store.calendarsForEntityType_(EventKit.EKEntityTypeEvent):
            qualified = qualify(calendar)
            if qualified == name:
                return Calendar(store=self, native=calendar, qualified=qualified)
        raise CalendarError(name)

    def fetch(self, calendar: Calendar, window: Window) -> Iterator[Any]:
        """Yield the raw EventKit events in the given calendar and window."""
        predicate = self.store.predicateForEventsWithStartDate_endDate_calendars_(
            to_nsdate(window.start),
            to_nsdate(window.end),
            [calendar.native],
        )
        yield from self.store.eventsMatchingPredicate_(predicate)

    def build_event(self, mirror: Mirror, calendar: Calendar) -> Any:
        """Create a new anonymised busy event in the calendar, tagged with its origin and source identifier."""
        event = EventKit.EKEvent.eventWithEventStore_(self.store)
        event.setCalendar_(calendar.native)
        event.setTitle_(mirror.title)
        event.setNotes_(tag(mirror.origin, mirror.source))
        return self.set_times(event, mirror)

    def set_times(self, event: Any, mirror: Mirror) -> Any:
        """Set an event's start and end to match the mirror, returning the event."""
        event.setStartDate_(to_nsdate(mirror.start))
        event.setEndDate_(to_nsdate(mirror.end))
        return event

    def save(self, event: Any) -> None:
        """Persist an event to the store, raising on failure."""
        succeeded, error = self.store.saveEvent_span_error_(event, EventKit.EKSpanThisEvent, None)
        if not succeeded:
            raise WriteError(error)

    def remove(self, event: Any) -> None:
        """Delete an event from the store, raising on failure."""
        succeeded, error = self.store.removeEvent_span_error_(event, EventKit.EKSpanThisEvent, None)
        if not succeeded:
            raise WriteError(error)
