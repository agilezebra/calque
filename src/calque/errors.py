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


class ServiceError(CalqueError):
    """Installing or removing the launchd agent failed."""

    def __init__(self, detail: object) -> None:
        super().__init__(f"launchctl failed: {detail}")
