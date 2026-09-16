class ValidationError(ValueError):
    """A user-editable configuration or value is invalid."""


class CapabilityError(ValidationError):
    """A requested model combination has no verified adapter."""


class StaleVersionError(RuntimeError):
    """A calculation was based on an older project revision."""
