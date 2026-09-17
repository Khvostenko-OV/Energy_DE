"""Unit tests for the boundary GeoJSON asset seam (issue #19/#21).

`viz.data.load_level_geojson` locates the per-level boundary GeoJSON through
the `VIZ_BOUNDARY_ASSET_DIR` env seam (falling back to the repo's prep output
dir), parses it as a JSON dict, and fails loudly when the asset is missing — so
a mis-mount surfaces as a clear error instead of a silent choropleth.
"""

import json

import pytest

from viz import data as viz_data


@pytest.fixture
def _assets(tmp_path, monkeypatch):
    assets = tmp_path / "assets"
    assets.mkdir()
    bodies = {
        1: {"type": "FeatureCollection", "features": [], "level": 1},
        2: {"type": "FeatureCollection", "features": [], "level": 2},
        3: {"type": "FeatureCollection", "features": [], "level": 3},
    }
    for level, body in bodies.items():
        (assets / f"level_{level}.geojson").write_text(json.dumps(body))
    monkeypatch.setattr(viz_data, "VIZ_BOUNDARY_ASSET_DIR", str(assets))
    return assets


class TestLoadLevelGeojson:
    def test_loads_each_levels_geojson(self, _assets):
        assert viz_data.load_level_geojson(1)["level"] == 1
        assert viz_data.load_level_geojson(2)["level"] == 2
        assert viz_data.load_level_geojson(3)["level"] == 3

    def test_explicit_asset_dir_wins_over_env(self, tmp_path):
        custom = tmp_path / "custom"
        custom.mkdir()
        (custom / "level_1.geojson").write_text(
            json.dumps({"type": "FeatureCollection", "level": "custom"})
        )
        assert viz_data.load_level_geojson(1, custom)["level"] == "custom"

    def test_missing_asset_fails_loudly(self, _assets):
        with pytest.raises(FileNotFoundError, match="no boundary asset for level 9"):
            viz_data.load_level_geojson(9)