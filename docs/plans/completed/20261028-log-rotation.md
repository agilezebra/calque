# Plan: Rotate the agent log and cut per-run noise

## Overview
Stop `~/Library/Logs/calque.log` growing without bound. calque writes its own log through a size-capped
`RotatingFileHandler` when given `--log-file`, and `--install` passes `--log-file` to the agent; launchd's own
stdout/stderr capture moves to a separate file that only catches output from before logging starts. Passes that
change nothing log at debug level instead of info, so an idle run adds almost nothing.

## Context
- Files involved: `src/calque/cli.py`, `src/calque/service.py`, `src/calque/sync.py`, `tests/test_cli.py`,
  `tests/test_service.py`, `tests/test_sync.py`, `README.md`
- Related patterns:
  - `service.properties` is a pure plist builder tested by exact mapping equality; `install` adds the side effects
  - `install` builds `program` by slicing `--install SECONDS` out of `arguments`; append the `--log-file` pair there
  - `main` calls `logging.basicConfig(level=..., format=...)`; keep the same format for the file handler
  - `Plan.empty` already exists for the quiet-pass check
- Behaviour notes:
  - launchd holds `StandardOutPath` open for the life of each run, so calque can't rotate that file itself; giving
    calque its own handler is what makes rotation work
  - rotation: 1 MB per file, 3 backups (`calque.log.1` … `.3`), so the log tops out around 4 MB
  - `StandardOutPath` and `StandardErrorPath` move to `~/Library/Logs/calque.launchd.log`, which catches only
    tracebacks or messages from before logging is configured, so it stays tiny
  - if the user already passed `--log-file` to `--install`, keep theirs and don't add the default
  - `--log-file` is created with `mkdir(parents=True, exist_ok=True)` on its parent
  - an empty plan in a real run logs at debug; a non-empty plan, or any plan in a dry run, still logs at info
- Dependencies: none

## Development Approach
- Code first, then tests, task by task
- Complete each task fully before moving to the next

## Validation Commands
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy .`
- `uv run pytest`

## Implementation Steps

### Task 1: Log to a rotating file when asked
- [x] add `--log-file PATH` (type `Path`, default `None`) to `parse_arguments` in `src/calque/cli.py`
- [x] in `main`, when `--log-file` is given, create its parent directory and pass a
  `logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3)` to `logging.basicConfig` via
  `handlers=[...]`; otherwise keep the current stderr logging; name the size and backup count as module constants
- [x] write tests in `tests/test_cli.py` (using `tmp_path`, and resetting root logger handlers after each test):
  `--log-file` parses; a run with `--log-file` writes its log lines to that file; the handler has the expected
  `maxBytes` and `backupCount`
- [x] run the project test suite - must pass before task 2 (on Linux with stub EventKit/Foundation, test_store.py excluded; full suite needs macOS)

### Task 2: Point the installed agent at the rotating log
- [x] in `src/calque/service.py`, add the default `--log-file ~/Library/Logs/calque.log` to `program` in `install`
  unless `--log-file` is already in `arguments`
- [x] point the plist's `StandardOutPath`/`StandardErrorPath` at `~/Library/Logs/calque.launchd.log`
- [x] update the existing tests in `tests/test_service.py` (`test_properties_builds_the_expected_plist_mapping`,
  the install test's expected `ProgramArguments`) and add a test that a user-supplied `--log-file` is kept and no
  second one is appended
- [x] run the project test suite - must pass before task 3 (on Linux with stub EventKit/Foundation, test_store.py excluded; full suite needs macOS)

### Task 3: Quiet empty passes
- [x] in `mirror` in `src/calque/sync.py`, log the `source -> target: plan` line at debug when the plan is empty and
  this is not a dry run, and at info otherwise
- [x] write tests in `tests/test_sync.py` with `caplog`: an empty real pass logs nothing at info; a non-empty pass
  and an empty dry-run pass both log at info
- [x] run the project test suite - must pass before task 4 (on Linux with stub EventKit/Foundation, test_store.py excluded; full suite needs macOS)

### Task 4: Verify acceptance criteria
- [x] run the full test suite (on Linux with stub EventKit/Foundation, test_store.py excluded; full suite needs macOS)
- [x] run the linter, formatter check and mypy
- [x] update `README.md`: document `--log-file` under Options, and in "Install Agent" say where the agent logs
  (`~/Library/Logs/calque.log`, rotated at 1 MB with 3 backups, plus `calque.launchd.log` for startup errors) and
  that an existing agent must be re-installed with `--install` to pick this up
