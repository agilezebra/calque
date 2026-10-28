"""Surface a failed run through a macOS notification or a user-supplied command.

Alerting is best effort: each helper runs its subprocess with a short timeout and logs a warning when it cannot
be started, times out or exits non-zero, so an alert that itself fails never masks the failure it reports.
"""

import logging
import shlex
import subprocess

TIMEOUT = 30

# The message arrives as an argv item rather than being interpolated, so quotes in it cannot break the script.
SCRIPT = 'on run argv\ndisplay notification (item 1 of argv) with title "calque"\nend run'


def run(arguments: list[str], description: str) -> None:
    """Run ``arguments`` without a shell, logging a warning instead of raising if it fails."""
    try:
        # The arguments are either the fixed osascript invocation or a command the user configured explicitly.
        result = subprocess.run(  # noqa: S603
            arguments, capture_output=True, text=True, errors="replace", check=False, timeout=TIMEOUT
        )
    except (OSError, subprocess.TimeoutExpired) as exception:
        logging.warning("%s failed: %s", description, exception)
        return
    if result.returncode:
        logging.warning("%s exited with %s: %s", description, result.returncode, result.stderr.strip())


def notify(message: str) -> None:
    """Post a macOS notification titled calque carrying ``message``."""
    run(["osascript", "-e", SCRIPT, message], "failure notification")


def hook(command: str, message: str) -> None:
    """Run the user's failure ``command`` with ``message`` appended as its final argument."""
    run([*shlex.split(command), message], "failure hook")
