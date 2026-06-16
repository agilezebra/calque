"""Author and install a launchd agent that runs calque on a schedule.

The plist construction is a pure function, so the generated property list can be verified
without touching the filesystem or launchd; :func:`install` and :func:`uninstall` wrap it with
the filesystem writes and ``launchctl`` calls that belong at the process boundary.
"""

import logging
import os
import plistlib
import subprocess
import sys
from pathlib import Path

from calque.errors import ServiceError

LABEL = "com.agilezebra.calque"


def location(label: str = LABEL) -> Path:
    """The user's LaunchAgents plist path for the given label."""
    return Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"


def properties(program: list[str], interval: int, log: Path, *, label: str = LABEL) -> dict[str, object]:
    """Build the launchd property-list mapping for an agent running ``program`` every ``interval`` seconds."""
    return {
        "Label": label,
        "ProgramArguments": program,
        "StartInterval": interval,
        "RunAtLoad": True,
        "StandardOutPath": str(log),
        "StandardErrorPath": str(log),
    }


def domain() -> str:
    """The per-user launchd domain target for the current user."""
    return f"gui/{os.getuid()}"


def launchctl(*arguments: str, ignore_errors: bool = False) -> None:
    """Run a ``launchctl`` subcommand, raising on failure unless a missing target is tolerated."""
    # launchctl is a fixed system tool resolved from PATH and invoked only with our own arguments.
    result = subprocess.run(["launchctl", *arguments], capture_output=True, text=True, check=False)  # noqa: S603, S607
    if result.returncode and not ignore_errors:
        raise ServiceError(result.stderr.strip() or result.returncode)


def install(arguments: list[str], interval: int, *, label: str = LABEL) -> None:
    """Author the agent plist for the sync command in ``arguments`` and load it into launchd.

    The ``--install`` flag and the interval value following it are sliced out so the agent re-runs the plain
    sync, and the program is this executable resolved to an absolute path, since launchd does not search PATH.
    """
    index = arguments.index("--install")
    program = [os.path.realpath(sys.argv[0]), *arguments[:index], *arguments[index + 2 :]]
    target = location(label)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as file:
        plistlib.dump(properties(program, interval, Path.home() / "Library" / "Logs" / "calque.log", label=label), file)
    launchctl("bootout", f"{domain()}/{label}", ignore_errors=True)
    launchctl("bootstrap", domain(), str(target))
    logging.info("installed launchd agent at %s", target)


def uninstall(*, label: str = LABEL) -> None:
    """Unload the agent from launchd and remove its plist."""
    target = location(label)
    launchctl("bootout", f"{domain()}/{label}", ignore_errors=True)
    target.unlink(missing_ok=True)
    logging.info("removed launchd agent at %s", target)
