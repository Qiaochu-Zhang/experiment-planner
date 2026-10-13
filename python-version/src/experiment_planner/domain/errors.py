class ValidationError(ValueError):
    """A user-editable configuration or value is invalid."""


class CapabilityError(ValidationError):
    """A requested model combination has no verified adapter."""


class StaleVersionError(RuntimeError):
    """A calculation was based on an older project revision."""


class ModelTrainingError(RuntimeError):
    """A failed fit with context retained by traceback.format_exception."""

    def __init__(self, message, diagnostic):
        super().__init__(message)
        self.add_note(diagnostic)
