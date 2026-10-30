# Project Guidelines

## Environment

- Target Python >=3.13 only (development and CI use 3.14) and manage the project exclusively with uv.
- calque is macOS-only: it reads and writes the local calendar store through EventKit (PyObjC), so installing the
  package and running the tests need macOS.
- Keep EventKit and PyObjC inside `src/calque/store.py`; everything else works with calque's own types, and tests
  replace the store with mocks.
- Declare dependencies in `pyproject.toml`; update and commit `uv.lock` through uv.
- Keep source under `src/calque/` and mirror it under `tests/` (`src/calque/sync.py` → `tests/test_sync.py`).

## Required Checks

Run `uv run poe check` before considering work complete. It runs Ruff linting, Ruff format checking, strict mypy and
pytest under coverage, and must pass without weakening their configuration. Coverage is part of the gate: it fails
below 100% **branch** coverage, so every new line and branch needs a test.

Suppress a single finding (`noqa`, `NOSONAR`) only when the rule is wrong for that line, with a comment giving the
reason.

Run `uv run poe sonar` (needs Docker) to apply SonarCloud's Python rules locally. No issues should be reported.

## Coding Standards

- Write production-quality PEP 8 code with complete English identifiers; do not abbreviate or use single-letter names.
- Prefer pure functions, immutable data, explicit state, comprehensions, generators, and narrow scopes.
- Keep substantive state out of module scope. Isolate I/O and other side effects at application boundaries.
- Use absolute imports, `pathlib`, timezone-aware UTC datetimes, context managers, and specific exceptions.
- Use root `logging` calls with lazy formatting for diagnostics. Reserve `print` for intended process output.
- Fully type-hint every function; Ruff's annotation rules and strict mypy both enforce it.
- Give every module, class, function and method a concise Google-style docstring; test functions are exempt and
  document themselves through their names. Comments explain only non-obvious reasons or constraints.
- Test with pytest using fixtures and meaningful edge cases. Keep tests mirrored to the source layout.
- Follow DRY and SOLID without introducing abstractions that do not remove real complexity.

## Git

- Commit each completed slice with a focused, intentional message; keep reformatting, refactoring, and logic
  changes in separate commits. Do not push or open pull requests; the user reviews and pushes.
