"""Tests for the exception hierarchy and the message each error composes from its value."""

from calque.errors import AccessError, CalendarError, CalqueError, WriteError


def test_access_error_reports_the_authorisation_status() -> None:
    exception = AccessError("denied")
    assert isinstance(exception, CalqueError)
    assert "denied" in str(exception)


def test_calendar_error_quotes_the_missing_title() -> None:
    exception = CalendarError("Work")
    assert isinstance(exception, CalqueError)
    assert "'Work'" in str(exception)


def test_write_error_includes_the_underlying_detail() -> None:
    exception = WriteError("disk full")
    assert isinstance(exception, CalqueError)
    assert "disk full" in str(exception)
