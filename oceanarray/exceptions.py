"""Exception types for oceanarray."""

from oceanarray.config.validation import ValidationIssue


class MooringError(ValueError):
    """Raised when a mooring description fails validation.

    Carries the full list of validation issues so a caller can inspect every
    finding, not only the summary message.

    Parameters
    ----------
    message : str
        A human-readable summary of why the description was rejected.
    issues : list of ValidationIssue, optional
        The individual validation findings (errors and warnings) that led to
        the failure. Defaults to an empty list.
    """

    def __init__(
        self, message: str, issues: list[ValidationIssue] | None = None
    ) -> None:
        super().__init__(message)
        self.issues: list[ValidationIssue] = list(issues) if issues else []
