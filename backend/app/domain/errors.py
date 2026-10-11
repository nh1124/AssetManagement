class DomainError(Exception):
    """Something the domain refuses, independent of how it is being asked."""

    # Routers already catch ValueError as 400; inheriting it would swallow
    # NotFound and Conflict before the domain handler can preserve their codes.
    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        # A one-off compatibility code (currently 422) needs no fifth category.
        self.status_code = status_code


class NotFound(DomainError):
    pass


class Invalid(DomainError):
    pass


class Conflict(DomainError):
    pass


class Refused(DomainError):
    pass
