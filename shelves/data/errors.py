"""
Data layer errors.
"""

from shelves.errors import ShelvesError


class NoDataSourceError(ShelvesError, ValueError):
    """Raised when resolve_data has no rows and the model has no supported source.

    Also a ValueError for backward compatibility with callers that predate the
    ShelvesError hierarchy.
    """
