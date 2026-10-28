# Plan: Make failed runs visible with a notification or hook

## Overview
Add two optional ways to surface a failed run instead of leaving it only in the log: `--notify-on-failure` posts a
macOS notification, and `--on-failure COMMAND` runs a user command with the failure message appended as its last
argument, so tools like `terminal-notifier -message`, `ntfy publish <topic>` or `logger -t calque` work directly.
Both fire for any failed sync run: a `CalqueError` and any unexpected exception. Because `--install` already copies
the command's arguments into the launchd agent, the options carry through to scheduled runs with no service changes.

## Context
- Files involved: `src/calque/cli.py`, new `src/calque/alert.py`, new `tests/test_alert.py`, `tests/test_cli.py`,
  `tests/test_service.py`, `README.md`
- Related patterns:
  - `service.launchctl` shows how to run a fixed external tool with `subprocess.run(..., check=False)` and the
    `# noqa: S603, S607` justification comment; follow it for `osascript`
  - `main` in `cli.py` is the process boundary that already catches `CalqueError` and returns an exit code; hook the
    alerting in there, not in `sync.py`
  - tests stub subprocess with `monkeypatch.setattr("calque.<module>.subprocess.run", Mock(...))`
- Behaviour notes:
  - only a sync run alerts; `--list-calendars`, `--install` and `--uninstall` failures are interactive and already visible
  - `--on-failure` is split with `shlex.split`, the failure message is appended as one final argument, and it is run
    without a shell
  - the notification uses `osascript -e 'display notification ... with title "calque"'`; pass the message as an
    `argv` item to an `on run argv` script rather than interpolating it, so quotes in the message can't break the script
  - an alert that itself fails (missing command, non-zero exit, timeout) is logged as a warning and never masks the
    original failure or changes the exit code; give each subprocess a short timeout (e.g. 30s)
  - an unexpected exception is logged with its traceback, alerted, and the run returns 1 rather than crashing
- Dependencies: none (`osascript` ships with macOS)

## Development Approach
- Code first, then tests, task by task
- Complete each task fully before moving to the next

## Validation Commands
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy .`
- `uv run pytest`

## Implementation Steps

### Task 1: Add the alert module
- [x] create `src/calque/alert.py` with a module docstring in the style of the others, `notify(message)` that runs
  `osascript` with the message passed as an argument, and `hook(command, message)` that runs
  `[*shlex.split(command), message]`
- [x] make both catch `OSError` and `subprocess.TimeoutExpired`, and log a warning on those or on a non-zero exit,
  never raising
- [x] write `tests/test_alert.py` covering: the exact `osascript` argv; a message containing quotes is passed
  unchanged as an argument; the hook argv is the split command plus the message as one final item, even when the
  message contains spaces and quotes; a missing command, a non-zero exit, and a timeout each
  log a warning and do not raise
- [x] run the project test suite - must pass before task 2 (run with .venv.sbx and /tmp/objc-stubs, tests/test_store.py excluded; uv run cannot build pyobjc on Linux - confirm with uv run pytest on a Mac)

### Task 2: Wire alerts into the command line
- [x] add `--notify-on-failure` (store_true) and `--on-failure COMMAND` (string) to `parse_arguments` in
  `src/calque/cli.py`, with help text in the existing style
- [x] in `main`, on a sync run, catch `CalqueError` as now and also catch any other `Exception` (log it with
  `logging.exception`, add a `# noqa: BLE001` with a reason), then call the configured alerts with the message and
  return 1 (no noqa needed: ruff does not flag BLE001 when the handler calls logging.exception, and RUF100 rejects an unused one)
- [x] write tests in `tests/test_cli.py`: both options parse; a `CalqueError` from `synchronise` triggers
  `notify` and `hook` when configured and returns 1; an unexpected `RuntimeError` is caught, alerted and returns 1;
  no alert fires on success or when neither option is set; an `--uninstall` failure does not alert
- [x] run the project test suite - must pass before task 3 (run with .venv.sbx and /tmp/objc-stubs, tests/test_store.py excluded; confirm with uv run pytest on a Mac)

### Task 3: Confirm the options survive install
- [x] add a test in `tests/test_service.py` that `install` with `--on-failure "cmd arg"` and `--notify-on-failure`
  keeps both in the plist's `ProgramArguments`
- [x] run the project test suite - must pass before task 4 (run with .venv.sbx and /tmp/objc-stubs, tests/test_store.py excluded; confirm with uv run pytest on a Mac)

### Task 4: Verify acceptance criteria
- [x] run the full test suite (run with .venv.sbx and /tmp/objc-stubs, tests/test_store.py excluded; confirm with uv run pytest on a Mac)
- [x] run the linter, formatter check and mypy
- [x] update `README.md`: document both options under Options, and add a short "Failure alerts" section with a
  `--notify-on-failure` example on `--install`, `--on-failure` examples using `terminal-notifier`, `ntfy` and a
  custom script reading `$1`, a note that the message is appended as the last argument and the command runs
  without a shell, and a note that the notification appears under the Python interpreter in System Settings →
  Notifications on first use
