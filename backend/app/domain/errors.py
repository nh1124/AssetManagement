class DomainError(Exception):
    """Something the domain refuses, independent of how it is being asked."""

    # Routers already catch ValueError as 400; inheriting it would swallow
    # NotFound and Conflict before the domain handler can preserve their codes.
    def __init__(self, message: str, *, status_code: int | None = None, payload=None):
        super().__init__(message)
        # A one-off compatibility code (currently 422) needs no fifth category.
        self.status_code = status_code
        self.payload = payload


class NotFound(DomainError):
    pass


class Invalid(DomainError):
    pass


class Conflict(DomainError):
    pass


class Refused(DomainError):
    pass

# The status each category answers with. It lives here, beside the categories,
# because the number is part of what the category means: the HTTP handler and
# the AI audit log both have to agree on it, and two copies would drift.
_STATUS_BY_CATEGORY: tuple[tuple[type["DomainError"], int], ...] = (
    (NotFound, 404),
    (Invalid, 400),
    (Conflict, 409),
    (Refused, 403),
)


def status_for(error: "DomainError") -> int:
    """The status this error answers with, honouring an explicit override."""
    if error.status_code is not None:
        return error.status_code
    for category, status in _STATUS_BY_CATEGORY:
        if isinstance(error, category):
            return status
    return 400


def detail_for(error: "DomainError"):
    """What goes in the response body: the structured payload, else the message."""
    return error.payload if error.payload is not None else str(error)
