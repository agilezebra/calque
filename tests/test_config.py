"""Tests for configuration helpers — per-calendar title template selection."""

from typing import cast
from unittest.mock import Mock

from calque.config import Config
from calque.store import Calendar


def calendar(qualified: str) -> Calendar:
    """A stand-in calendar reporting the given fully-qualified name."""
    return cast("Calendar", Mock(qualified=qualified))


def test_title_for_calendar_returns_default_when_unconfigured() -> None:
    config = Config(title="Busy")
    assert config.title_for_calendar(calendar("iCloud.Home"), calendar("Work.MyCompany")) == "Busy"


def test_title_for_calendar_uses_the_target_override() -> None:
    config = Config(title="Busy", title_to={"Work.MyCompany": "{account}: {title}"})
    assert config.title_for_calendar(calendar("Client.Calendar"), calendar("Work.MyCompany")) == "{account}: {title}"
    assert config.title_for_calendar(calendar("Client.Calendar"), calendar("Client.Calendar")) == "Busy"


def test_source_override_wins_over_the_target_override() -> None:
    config = Config(
        title="Busy",
        title_to={"Work.MyCompany": "{account}: {title}"},
        title_from={"iCloud.Home": "Busy"},
    )
    # An event from Home into MyCompany keeps the opaque source title, not the target's detailed one...
    assert config.title_for_calendar(calendar("iCloud.Home"), calendar("Work.MyCompany")) == "Busy"
    # ...while an event from a client into MyCompany still gets the target's detailed title.
    assert config.title_for_calendar(calendar("Client.Calendar"), calendar("Work.MyCompany")) == "{account}: {title}"
