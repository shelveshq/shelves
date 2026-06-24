"""CLI asset-path helpers — KAN-308.

Unit tests for the render CLI's relative-prefix computation and the dev
server's traversal-safe asset file resolution.
"""

from __future__ import annotations

from shelves.cli.dev import _resolve_asset_file
from shelves.cli.render import _asset_url_prefix


class TestRenderAssetPrefix:
    def test_output_subdir_to_sibling_assets(self, tmp_path):
        """output/ beside assets/ → ../assets/."""
        assert _asset_url_prefix(tmp_path / "assets", tmp_path / "output") == "../assets/"

    def test_output_same_dir_as_assets_parent(self, tmp_path):
        """HTML written next to assets/ → assets/."""
        assert _asset_url_prefix(tmp_path / "assets", tmp_path) == "assets/"

    def test_custom_assets_dir_name(self, tmp_path):
        """A renamed assets dir is reflected in the prefix."""
        assert _asset_url_prefix(tmp_path / "brand", tmp_path / "output") == "../brand/"


class TestDevAssetResolve:
    def test_serves_existing_file(self, tmp_path):
        (tmp_path / "png").mkdir()
        f = tmp_path / "png" / "logo.png"
        f.write_bytes(b"PNG")
        assert _resolve_asset_file(tmp_path, "/assets/png/logo.png") == f.resolve()

    def test_missing_file_returns_none(self, tmp_path):
        assert _resolve_asset_file(tmp_path, "/assets/nope.png") is None

    def test_percent_encoded_filename_is_decoded(self, tmp_path):
        (tmp_path / "png").mkdir()
        f = tmp_path / "png" / "my logo.png"
        f.write_bytes(b"PNG")
        assert _resolve_asset_file(tmp_path, "/assets/png/my%20logo.png") == f.resolve()

    def test_directory_returns_none(self, tmp_path):
        (tmp_path / "png").mkdir()
        assert _resolve_asset_file(tmp_path, "/assets/png") is None

    def test_path_traversal_rejected(self, tmp_path):
        assets = tmp_path / "assets"
        assets.mkdir()
        (tmp_path / "secret.txt").write_text("secret")
        assert _resolve_asset_file(assets, "/assets/../secret.txt") is None
