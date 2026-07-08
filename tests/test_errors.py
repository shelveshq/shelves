"""
Shared exception hierarchy tests.

Every error Shelves raises on purpose derives from ShelvesError, so surfaces
can catch Shelves failures precisely instead of blanket `except Exception`.
"""

import pytest

from shelves.data.cube_client import (
    CubeAuthError,
    CubeConfigError,
    CubeError,
    CubeQueryError,
    CubeServerError,
    CubeTimeoutError,
)
from shelves.data.duckdb_adapter import DuckDBQueryError
from shelves.data.errors import NoDataSourceError
from shelves.errors import ShelvesError


class TestErrorHierarchy:
    @pytest.mark.parametrize(
        "error_cls",
        [
            CubeError,
            CubeConfigError,
            CubeQueryError,
            CubeAuthError,
            CubeServerError,
            CubeTimeoutError,
            DuckDBQueryError,
            NoDataSourceError,
        ],
    )
    def test_data_layer_errors_are_shelves_errors(self, error_cls):
        assert issubclass(error_cls, ShelvesError)

    def test_no_data_source_error_still_a_value_error(self):
        """Backward compatibility: callers that predate the hierarchy catch
        ValueError."""
        assert issubclass(NoDataSourceError, ValueError)
        with pytest.raises(ValueError):
            raise NoDataSourceError("no source")

    def test_shelves_error_is_public_api(self):
        import shelves

        assert shelves.ShelvesError is ShelvesError
        assert "ShelvesError" in shelves.__all__
