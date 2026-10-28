"""Exception hierarchy for the mirror. Each composes its own message from the failing value."""


class CalqueError(Exception):
    """Base for every error raised by calque."""


class AccessError(CalqueError):
    """Calendar access was denied or could not be resolved in time."""

    def __init__(self, status: object) -> None:
        super().__init__(f"calendar access not granted (authorisation status {status})")


class CalendarError(CalqueError):
    """No calendar with the requested title exists in the local store."""

    def __init__(self, title: str) -> None:
        super().__init__(f"no calendar titled {title!r} found in the local store")


class WriteError(CalqueError):
    """EventKit refused to save or remove a mirror block."""

    def __init__(self, detail: object) -> None:
        super().__init__(f"EventKit write failed: {detail}")


class DeleteLimitError(CalqueError):
    """One or more mirror passes were skipped for planning more deletes than the limit allows."""

    def __init__(self, limit: int | None) -> None:
        super().__init__(
            f"skipped mirror passes that would delete more than {limit} mirror blocks; "
            "run once without --max-deletes to apply them",
        )


class ServiceError(CalqueError):
    """Installing or removing the launchd agent failed."""

    def __init__(self, detail: object) -> None:
        super().__init__(f"launchctl failed: {detail}")
