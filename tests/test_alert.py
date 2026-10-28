"""Tests for the failure alerts: the subprocess argv they build and their never-raise error handling."""

import subprocess
from unittest.mock import Mock

import pytest

from calque.alert import SCRIPT, TIMEOUT, hook, notify


@pytest.fixture
def run(monkeypatch: pytest.MonkeyPatch) -> Mock:
    """Stub ``subprocess.run`` in the alert module with a successful completion."""
    stub = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr("calque.alert.subprocess.run", stub)
    return stub


def test_notify_runs_osascript_with_the_message_as_an_argument(run: Mock) -> None:
    notify("sync failed")
    run.assert_called_once_with(
        ["osascript", "-e", SCRIPT, "sync failed"],
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
        timeout=TIMEOUT,
    )


def test_notify_passes_a_quoted_message_unchanged(run: Mock) -> None:
    message = "calendar \"Work\" said 'no' \\ done"
    notify(message)
    assert run.call_args.args[0] == ["osascript", "-e", SCRIPT, message]


def test_hook_appends_the_message_as_one_final_argument(run: Mock) -> None:
    message = 'calendar "Work" isn\'t reachable'
    hook("ntfy publish 'my topic'", message)
    assert run.call_args.args[0] == ["ntfy", "publish", "my topic", message]
    assert run.call_args.kwargs["timeout"] == TIMEOUT


def test_a_missing_command_logs_a_warning(run: Mock, caplog: pytest.LogCaptureFixture) -> None:
    run.side_effect = FileNotFoundError(2, "No such file or directory", "missing")
    hook("missing", "sync failed")
    assert "failure hook failed" in caplog.text
    assert caplog.records[-1].levelname == "WARNING"


def test_a_non_zero_exit_logs_a_warning(run: Mock, caplog: pytest.LogCaptureFixture) -> None:
    run.return_value = subprocess.CompletedProcess([], 3, "", "boom\n")
    notify("sync failed")
    assert "failure notification exited with 3: boom" in caplog.text
    assert caplog.records[-1].levelname == "WARNING"


def test_a_timeout_logs_a_warning(run: Mock, caplog: pytest.LogCaptureFixture) -> None:
    run.side_effect = subprocess.TimeoutExpired("slow", TIMEOUT)
    hook("slow", "sync failed")
    assert "failure hook failed" in caplog.text
    assert caplog.records[-1].levelname == "WARNING"


@pytest.mark.usefixtures("run")
def test_success_logs_nothing(caplog: pytest.LogCaptureFixture) -> None:
    notify("sync failed")
    hook("logger -t calque", "sync failed")
    assert not caplog.records
