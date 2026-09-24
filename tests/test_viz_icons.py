"""Unit tests for the IconLayer sprite atlas (``viz/icons``).

The committed atlas and per-source PNGs are the artwork the map's
``IconLayer`` renders; ``scripts/build_icon_atlas.py`` regenerates them.
These tests read the committed files (``meta``/grep-only, no Pillow needed) so
every installed flavour of the viz tests runs them, and — when Pillow is
present — re-draw the atlas with the generator and assert byte-equality, so a
stale committed artifact fails loudly instead of shipping silently.
"""

from __future__ import annotations

import base64
import importlib.util
import json
from pathlib import Path

import pytest

from viz.icon_atlas import png_size
from viz.palette import SOURCE_LAYER_ORDER

ICONS_DIR = Path(__file__).resolve().parent.parent / "viz" / "icons"
ATLAS = ICONS_DIR / "source_icons.png"
MANIFEST = ICONS_DIR / "manifest.json"

# The generator's canonical set: palette paint order + the cogeneration slot.
SOURCE_ICONS = list(SOURCE_LAYER_ORDER) + ["diesel"]


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text())


class TestAtlasFiles:
    def test_manifest_matches_palette_and_diesel(self):
        manifest = load_manifest()
        assert list(manifest["icons"]) == SOURCE_ICONS
        assert manifest["cell"] > 0

    def test_atlas_dimensions_match_cell_and_icon_count(self):
        manifest = load_manifest()
        width, height = png_size(ATLAS)
        assert height == manifest["cell"]
        assert width == manifest["cell"] * len(manifest["icons"])

    def test_every_source_has_its_own_square_icon_png(self):
        manifest = load_manifest()
        for source, info in manifest["icons"].items():
            icon = ICONS_DIR / info["file"]
            assert icon.is_file(), f"missing {icon.name} for {source}"
            width, height = png_size(icon)
            assert (width, height) == (manifest["cell"], manifest["cell"])


@pytest.mark.skipif(importlib.util.find_spec("PIL") is None,
                    reason="Pillow not installed; cannot regenerate the atlas")
class TestAtlasDrift:
    def test_committed_atlas_matches_generator_output(self):
        script = Path(__file__).resolve().parent.parent / "scripts" / "build_icon_atlas.py"
        spec = importlib.util.spec_from_file_location("build_icon_atlas", script)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        cell = load_manifest()["cell"]
        assert module.SOURCE_ICONS == tuple(SOURCE_ICONS)
        from PIL import Image
        regenerated = module.build_atlas(module.SOURCE_ICONS, cell)
        committed = Image.open(ATLAS).convert("RGBA")
        assert regenerated.tobytes() == committed.tobytes()


class TestIconLoader:
    """`viz.icon_atlas`: the data-URI loader the IconLayers are built from."""

    def test_every_source_inlines_a_real_png(self):
        from viz.icon_atlas import icon_data_uri

        for source in SOURCE_ICONS:
            uri = icon_data_uri(source)
            assert uri.startswith("data:image/png;base64,"), uri[:40]
            payload = base64.b64decode(uri.split(",", 1)[1])
            assert payload[:8] == b"\x89PNG\r\n\x1a\n"

    def test_icon_size_matches_the_committed_cell(self):
        from viz.icon_atlas import icon_data_uri, icon_png_path, icon_size_px

        cell = load_manifest()["cell"]
        for source in SOURCE_ICONS:
            assert icon_size_px(source) == cell
            assert icon_data_uri(source).split(",", 1)[1] == base64.b64encode(
                icon_png_path(source).read_bytes()
            ).decode("ascii")
