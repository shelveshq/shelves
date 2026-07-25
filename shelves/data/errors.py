"""
Data layer errors.
"""

from shelves.errors import ShelvesError


class NoDataSourceError(ShelvesError, ValueError):
    """Raised when resolve_data has no rows and the model has no supported source.

    Also a ValueError for backward compatibility with callers that predate the
    ShelvesError hierarchy.
    """


class ParameterDomainError(ShelvesError, ValueError):
    """Raised when a parameter's field-reference `values:` cannot be resolved
    to a domain, or when a value falls outside a resolved domain.

    Also a ValueError, matching NoDataSourceError, so surfaces that already
    catch ValueError around parameter loading keep working.
    """
