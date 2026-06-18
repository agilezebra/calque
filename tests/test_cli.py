"""Tests for the command-line boundary: argument parsing, the options-to-config projection, and exit codes."""

import sys
from unittest.mock import Mock

import pytest

from calque import cli
from calque.config import Config
from calque.errors import CalendarError, ServiceError
from calque.model import Participation


def test_parse_arguments_collects_the_calendars_in_order() -> None:
    assert cli.parse_arguments(["Personal", "Work"]).calendars == ["Personal", "Work"]


def test_parse_arguments_rejects_a_lone_calendar() -> None:
    with pytest.raises(SystemExit):
        cli.parse_arguments(["Personal"])


def test_parse_arguments_collects_target_title_overrides() -> None:
    parsed = cli.parse_arguments(["--title-to", "Work", "{title}", "Personal", "Work"])
    assert parsed.title_to == {"Work": "{title}"}


def test_parse_arguments_collects_source_title_overrides() -> None:
    parsed = cli.parse_arguments(["--title-from", "Home", "Busy", "Personal", "Work"])
    assert parsed.title_from == {"Home": "Busy"}


def test_parse_arguments_merges_repeated_title_overrides() -> None:
    parsed = cli.parse_arguments(["--title-to", "Work", "A", "--title-to", "Home", "B", "Personal", "Work"])
    assert parsed.title_to == {"Work": "A", "Home": "B"}


def test_parse_arguments_compiles_exclude_patterns() -> None:
    # The variadic --exclude-pattern must follow the positionals, or it swallows them.
    parsed = cli.parse_arguments(["Personal", "Work", "--exclude-pattern", r"^Lunch$"])
    assert [pattern.pattern for pattern in parsed.exclude_patterns] == [r"^Lunch$"]


def test_parse_arguments_reads_boolean_toggles() -> None:
    parsed = cli.parse_arguments(["--no-exclude-clashes", "--dry-run", "Personal", "Work"])
    assert parsed.exclude_clashes is False
    assert parsed.dry_run is True


def test_parse_arguments_defaults_cleanup_off_and_toggles_on() -> None:
    assert cli.parse_arguments(["Personal", "Work"]).cleanup is False
    assert cli.parse_arguments(["--cleanup", "Personal", "Work"]).cleanup is True


def test_to_config_projects_cleanup() -> None:
    assert cli.to_config(cli.parse_arguments(["--cleanup", "Personal", "Work"])).cleanup is True


def test_parse_arguments_collects_muted_calendars_into_a_set() -> None:
    # The variadic --mute must follow the positionals, or it swallows them.
    parsed = cli.parse_arguments(["Personal", "Work", "Side", "--mute", "Work", "Side"])
    assert parsed.muted == frozenset({"Work", "Side"})


def test_parse_arguments_defaults_muted_to_empty() -> None:
    assert cli.parse_arguments(["Personal", "Work"]).muted == frozenset()


def test_parse_arguments_defaults_statuses_to_accepted_and_unknown() -> None:
    assert cli.parse_arguments(["Personal", "Work"]).statuses == frozenset(
        {Participation.ACCEPTED, Participation.UNKNOWN},
    )


def test_parse_arguments_collects_statuses_into_participation_members() -> None:
    # The variadic --statuses must follow the positionals, or it swallows them.
    parsed = cli.parse_arguments(["Personal", "Work", "--statuses", "accepted", "tentative"])
    assert parsed.statuses == frozenset({Participation.ACCEPTED, Participation.TENTATIVE})


def test_parse_arguments_rejects_an_unknown_status() -> None:
    with pytest.raises(SystemExit):
        cli.parse_arguments(["Personal", "Work", "--statuses", "maybe"])


def test_to_config_projects_statuses() -> None:
    config = cli.to_config(cli.parse_arguments(["Personal", "Work", "--statuses", "declined"]))
    assert config.statuses == frozenset({Participation.DECLINED})


def test_to_config_projects_shared_options_and_keeps_defaults_for_the_rest() -> None:
    options = cli.parse_arguments(
        [
            "--title",
            "Out",
            "--title-to",
            "Work",
            "{title}",
            "--lookback",
            "3",
            "--no-exclude-all-day",
            "Personal",
            "Work",
        ],
    )
    config = cli.to_config(options)
    assert config.title == "Out"
    assert config.title_to == {"Work": "{title}"}
    assert config.lookback == 3
    assert config.exclude_all_day is False
    assert config.work_start == Config().work_start  # a field with no CLI option falls back to its default


def test_main_lists_calendars_and_exits(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    listed = ["Home.Personal", "Work.Office"]
    monkeypatch.setattr(cli, "CalendarStore", Mock(return_value=Mock(qualified_names=lambda: listed)))
    assert cli.main(["--list-calendars", "Personal", "Work"]) == 0
    assert capsys.readouterr().out.splitlines() == listed


def test_main_returns_zero_on_a_successful_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "synchronise", Mock())
    assert cli.main(["Personal", "Work"]) == 0


def test_main_reads_sys_argv_when_called_without_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    # The installed console script calls main() with no arguments, so it must fall back to sys.argv.
    monkeypatch.setattr(sys, "argv", ["calque", "--uninstall"])
    spy = Mock()
    monkeypatch.setattr(cli, "uninstall", spy)
    assert cli.main() == 0
    spy.assert_called_once_with()


def test_main_forwards_muted_calendars_to_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    run = Mock()
    monkeypatch.setattr(cli, "synchronise", run)
    cli.main(["Personal", "Work", "Side", "--mute", "Side"])
    assert run.call_args.args[0].muted == frozenset({"Side"})


def test_main_reports_a_sync_error_with_a_nonzero_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "synchronise", Mock(side_effect=CalendarError("Work")))
    assert cli.main(["Personal", "Work"]) == 1


def test_parse_arguments_reads_the_install_interval() -> None:
    assert cli.parse_arguments(["--install", "900", "Personal", "Work"]).install == 900


def test_parse_arguments_allows_uninstall_without_calendars() -> None:
    assert cli.parse_arguments(["--uninstall"]).uninstall is True


def test_parse_arguments_rejects_a_sync_without_calendars() -> None:
    with pytest.raises(SystemExit):
        cli.parse_arguments([])


def test_main_installs_an_agent_from_the_whole_command(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = Mock(return_value="/agent.plist")
    monkeypatch.setattr(cli, "install", spy)
    command = ["--install", "900", "--no-exclude-clashes", "Personal", "Work"]
    assert cli.main(command) == 0
    spy.assert_called_once_with(command, 900)


def test_main_uninstalls_the_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = Mock(return_value="/agent.plist")
    monkeypatch.setattr(cli, "uninstall", spy)
    assert cli.main(["--uninstall"]) == 0
    spy.assert_called_once_with()


def test_main_reports_a_service_error_with_a_nonzero_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "uninstall", Mock(side_effect=ServiceError("boom")))
    assert cli.main(["--uninstall"]) == 1
