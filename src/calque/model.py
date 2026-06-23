"""Domain model for the mirror: events, anonymised busy blocks, and the reconciliation plan."""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Protocol

MARKER = "⟦calque⟧"


@dataclass(frozen=True, slots=True)
class Window:
    """A half-open time range in UTC — a query range or an interval occupied by an event."""

    start: datetime
    end: datetime

    def __str__(self) -> str:
        """A readable local-time rendering of the range, dropping seconds and the timezone."""
        start = self.start.astimezone()
        end = self.end.astimezone()
        until = f"{end:%H:%M}" if start.date() == end.date() else f"{end:%a %Y-%m-%d %H:%M}"
        return f"{start:%a %Y-%m-%d %H:%M} to {until}"


class Participation(Enum):
    """The current user's response to an event invitation."""

    ACCEPTED = "accepted"
    TENTATIVE = "tentative"
    DECLINED = "declined"
    PENDING = "pending"
    UNKNOWN = "unknown"


class Status(Enum):
    """The lifecycle status of an event itself (its iCalendar ``STATUS``), independent of participation."""

    NONE = "none"
    CONFIRMED = "confirmed"
    TENTATIVE = "tentative"
    CANCELLED = "cancelled"


class Source(Protocol):
    """The slice of an EventKit ``EKSource`` we read: the account a calendar belongs to.

    A narrowing of PyObjC's untyped objects; ``store.Calendar.source`` returns one.
    """

    def title(self) -> str:
        """The account name (e.g. the Google or Exchange account behind the calendar)."""
        ...


@dataclass(frozen=True, slots=True)
class Event:
    """A source-calendar event reduced to the fields the mirror cares about."""

    identifier: str
    title: str
    account: str
    window: Window
    all_day: bool
    participation: Participation
    status: Status
    notes: str | None = None

    @property
    def start(self) -> datetime:
        """The event's start, in UTC."""
        return self.window.start

    @property
    def end(self) -> datetime:
        """The event's end, in UTC."""
        return self.window.end

    def __str__(self) -> str:
        """A human-readable representation of the event for logging and diagnostics."""
        return f"title={self.title!r} window={self.window} account={self.account!r} status={self.status.value} participation={self.participation.value} identifier={self.identifier!r} notes={self.notes!r}"


@dataclass(frozen=True, slots=True)
class Mirror:
    """An anonymised busy block in the target calendar, linked to its source by identifier."""

    source: str
    window: Window
    title: str
    # Excluded from equality:
    original: str | None = field(default=None, compare=False)
    # The calendar this block was copied from, stored in the tag so a mirror is never returned to its
    # source. Excluded from equality: it is fixed per direction and absent on blocks read back for diffing.
    origin: str = field(default="", compare=False)

    @property
    def start(self) -> datetime:
        """The block's start, in UTC."""
        return self.window.start

    @property
    def end(self) -> datetime:
        """The block's end, in UTC."""
        return self.window.end

    def __str__(self) -> str:
        """A human-readable representation of the mirror, in local time, for diagnostics."""
        return f"title={self.title!r} original={self.original!r} window={self.window} source={self.source!r}"


@dataclass(frozen=True, slots=True)
class Plan:
    """The reconciliation outcome: blocks to create, retime, and remove in the target."""

    create: tuple[Mirror, ...]
    update: tuple[Mirror, ...]
    delete: tuple[Mirror, ...]

    @property
    def empty(self) -> bool:
        """Whether the plan would change nothing."""
        return not (self.create or self.update or self.delete)

    def __str__(self) -> str:
        """A human-readable summary of the plan's contents for logging and diagnostics."""
        return f"create={len(self.create)} update={len(self.update)} delete={len(self.delete)}"

    def log(self) -> None:
        """Log the plan's contents in a human-readable form."""
        logging.info("create:")
        for event in self.create:
            logging.info("  %s", event)
        logging.info("update:")
        for event in self.update:
            logging.info("  %s", event)
        logging.info("delete:")
        for event in self.delete:
            logging.info("  %s", event)


@dataclass(frozen=True, slots=True)
class Tag:
    """The provenance encoded on a mirror block: the calendar it was copied from and that source's event id."""

    origin: str
    identifier: str


def tag(origin: str, identifier: str) -> str:
    """Encode a mirror block's origin calendar and source event id into the marker stored on its notes.

    The fields are space-separated: the identifier never contains a space, so it is the first token,
    and the origin (which may) is the remainder. A space survives any normalisation that some
    calendar backends apply, where a tab or newline does not.
    """
    return f"{MARKER} {identifier} {origin}"


def untag(notes: str | None) -> Tag | None:
    """Recover the origin and source id from a mirror block's notes, or ``None`` if not one of ours."""
    if not notes or not notes.startswith(MARKER):
        return None
    identifier, _, origin = notes.removeprefix(MARKER).strip().partition(" ")
    if not identifier:
        return None
    return Tag(origin=origin, identifier=identifier)
