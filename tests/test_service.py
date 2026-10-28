"""Tests for the launchd agent authoring: the pure plist builder and the install/uninstall boundary."""

import os
import plistlib
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from calque import service
from calque.errors import ServiceError
from calque.service import install, location, properties, uninstall


@pytest.fixture(autouse=True)
def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect ``Path.home()`` at a temporary directory so installs touch no real LaunchAgents."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


def test_properties_builds_the_expected_plist_mapping() -> None:
    log = Path("/Users/me/Library/Logs/calque.log")
    plist = properties(["/bin/calque", "Personal", "Work"], 900, log, label="com.example.calque")
    assert plist == {
        "Label": "com.example.calque",
        "ProgramArguments": ["/bin/calque", "Personal", "Work"],
        "StartInterval": 900,
        "RunAtLoad": True,
        "StandardOutPath": str(log),
        "StandardErrorPath": str(log),
    }


def test_properties_sets_the_agent_path_when_given() -> None:
    plist = properties(
        ["/bin/calque"], 900, Path("/Users/me/Library/Logs/calque.log"), path="/opt/homebrew/bin:/usr/bin"
    )
    assert plist["EnvironmentVariables"] == {"PATH": "/opt/homebrew/bin:/usr/bin"}


def test_install_passes_the_installing_shell_path_to_the_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "/opt/homebrew/bin:/usr/bin:/bin")
    monkeypatch.setattr(sys, "argv", ["/opt/calque/bin/calque", "--install", "900", "Personal", "Work"])
    monkeypatch.setattr(service, "launchctl", Mock())
    install(["--install", "900", "Personal", "Work"], 900)

    loaded = plistlib.loads(location().read_bytes())
    assert loaded["EnvironmentVariables"] == {"PATH": "/opt/homebrew/bin:/usr/bin:/bin"}


def test_location_sits_under_launch_agents(home: Path) -> None:
    assert location("com.example.calque") == home / "Library" / "LaunchAgents" / "com.example.calque.plist"


def test_install_embeds_the_executable_strips_the_flag_then_replaces_and_bootstraps(
    home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["/opt/calque/bin/calque", "--install", "900", "Personal", "Work"])
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(service, "launchctl", lambda *arguments, **_: calls.append(arguments))
    install(["--install", "900", "Personal", "Work"], 900)

    target = home / "Library" / "LaunchAgents" / "com.agilezebra.calque.plist"
    loaded = plistlib.loads(target.read_bytes())
    assert loaded["ProgramArguments"] == [os.path.realpath("/opt/calque/bin/calque"), "Personal", "Work"]
    assert loaded["StartInterval"] == 900
    assert [arguments[0] for arguments in calls] == ["bootout", "bootstrap"]


def test_install_keeps_the_failure_alert_options_in_the_program_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    arguments = ["--notify-on-failure", "--on-failure", "cmd arg", "--install", "900", "Personal", "Work"]
    monkeypatch.setattr(sys, "argv", ["/opt/calque/bin/calque", *arguments])
    monkeypatch.setattr(service, "launchctl", Mock())
    install(arguments, 900)

    loaded = plistlib.loads(location().read_bytes())
    assert loaded["ProgramArguments"] == [
        os.path.realpath("/opt/calque/bin/calque"),
        "--notify-on-failure",
        "--on-failure",
        "cmd arg",
        "Personal",
        "Work",
    ]


def test_uninstall_boots_out_and_removes_the_plist(monkeypatch: pytest.MonkeyPatch) -> None:
    target = location()
    target.parent.mkdir(parents=True)
    target.write_bytes(b"placeholder")
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(service, "launchctl", lambda *arguments, **_: calls.append(arguments))

    uninstall()
    assert not target.exists()
    assert [arguments[0] for arguments in calls] == ["bootout"]


def test_uninstall_is_quiet_when_no_plist_is_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "launchctl", Mock())
    uninstall()  # missing_ok keeps removal from raising
    assert not location().exists()


def test_launchctl_raises_service_error_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("calque.service.subprocess.run", Mock(return_value=Mock(returncode=1, stderr="boom")))
    with pytest.raises(ServiceError, match="boom"):
        service.launchctl("bootstrap", "gui/0", "/x")


def test_launchctl_tolerates_an_absent_target(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("calque.service.subprocess.run", Mock(return_value=Mock(returncode=1, stderr="")))
    service.launchctl("bootout", "gui/0/label", ignore_errors=True)  # must not raise
