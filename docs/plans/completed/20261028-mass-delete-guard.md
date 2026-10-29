# Plan: Opt-in limit on deletes per mirror pass

## Overview
Add `--max-deletes N`, an opt-in safety limit: a mirror pass that would delete more than N blocks is skipped
entirely, since a source that suddenly loses that many events can't be trusted for creates or updates either. The
other passes still run, then the run fails with a non-zero exit so the problem shows up. With no limit set (the
default) behaviour is unchanged. A deliberate large clean-up is done by running once by hand without the option.

## Context
- Files involved: `src/calque/sync.py`, `src/calque/config.py`, `src/calque/errors.py`, `src/calque/cli.py`,
  `tests/test_sync.py`, `tests/test_cli.py`, `tests/test_config.py`, `tests/test_errors.py`, `README.md`
- Related patterns:
  - `reconcile` and `to_mirrors` are pure; keep the limit check pure too and leave the impure edges in `mirror`
    and `synchronise`
  - errors in `errors.py` build their own message from the failing value (see `CalendarError`)
  - new CLI options take their defaults from `Config()` and reach `Config` through `to_config` by sharing a field name
  - `mirror` tests use `Mock` calendars with `events.return_value`, `busy.return_value`, `mirrors.return_value`;
    `synchronise` tests replace `sync.mirror` with a `Mock`
- Behaviour notes:
  - `max_deletes` defaults to `None`, meaning no limit
  - deletes from `--cleanup` count towards the limit
  - a dry run logs the same warning and the plan that would be skipped, but does not raise
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

### Task 1: Add the configuration and error type
- [x] add `max_deletes: int | None = None` to `Config` in `src/calque/config.py`, with a docstring entry in the
  existing `:param` style
- [x] add `DeleteLimitError(CalqueError)` to `src/calque/errors.py`, built from the list of skipped
  `source -> target` pass descriptions and the limit, and saying a one-off run without `--max-deletes` applies them
- [x] add tests in `tests/test_config.py` for the `None` default and in `tests/test_errors.py` for the message
- [x] run the project test suite - must pass before task 2

### Task 2: Add the pure limit check
- [x] add a pure function in `src/calque/sync.py`, e.g. `exceeds(plan, limit) -> bool`, true only when `limit` is
  not `None` and `len(plan.delete) > limit`
- [x] write tests in `tests/test_sync.py`: a `None` limit never trips; a delete count at the limit passes; one over
  trips; a limit of 0 trips on any delete
- [x] run the project test suite - must pass before task 3

### Task 3: Skip an over-limit pass and fail the run
- [x] in `mirror`, when `exceeds(plan, config.max_deletes)`, log a warning naming the pass, the delete count and the
  limit, do not call `target.apply`, and report the pass as skipped (e.g. `mirror` returns `bool`)
- [x] in `synchronise`, run every pass as now, collect the skipped passes, and raise `DeleteLimitError` after all
  passes finish when any were skipped and `config.dry_run` is false
- [x] write tests in `tests/test_sync.py`: an over-limit pass never calls `target.apply`; an under-limit pass
  applies as before; a skip in one pass does not stop later passes; `synchronise` raises `DeleteLimitError` only
  after all passes ran; a dry run logs the warning but does not raise
- [x] update the existing `synchronise` tests whose `mirror` mock now needs a return value
- [x] run the project test suite - must pass before task 4

### Task 4: Expose the option on the command line
- [x] add `--max-deletes N` (int, default `None` from `Config`, meaning no limit) to `parse_arguments` in
  `src/calque/cli.py`, with help text in the existing style
- [x] write tests in `tests/test_cli.py` that the option parses and projects onto `Config` through `to_config`, that
  it defaults to `None`, and that `main` returns 1 when `synchronise` raises `DeleteLimitError`
- [x] run the project test suite - must pass before task 5

### Task 5: Verify acceptance criteria
- [x] run the full test suite (Linux sandbox: .venv.sbx with EventKit stubs, tests/test_store.py excluded; confirm with `uv run pytest` on macOS)
- [x] run the linter, formatter check and mypy
- [x] update `README.md`: document `--max-deletes` under Options, explaining that an over-limit pass is skipped
  whole, the run exits non-zero, and a deliberate large clean-up is applied by running once without the option
