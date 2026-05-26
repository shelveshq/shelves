"""
Data layer errors.
"""


class NoDataSourceError(ValueError):
    """Raised when resolve_data has no rows and the model has no supported source."""
