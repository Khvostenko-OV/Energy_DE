"""Icon sprite loader for the viz map's IconLayer (issues #23, #28).

The map renders unit points with deck.gl's ``IconLayer``, whose icon texture
must reach the browser as a URL.  The runtime is a web-free (distroless,
issue #34) Streamlit app, so instead of serving the sprite over HTTP the icon
is **inlined as a base64 ``data:`` URI** at build time — no network fetch, so
no caching staleness and no static-file plumbing: deck.gl loads the texture
straight from the payload it already has.

Each source layer uses *its own* per-source sprite (`viz/icons/<source>.png`,
white glyph on transparency, drawn by `scripts/build_icon_atlas.py`) as a
single-icon atlas, and tints it via ``IconLayer(mask=True)`` +
``get_color`` — so one small image serves any palette colour and ``IconManager``
has exactly one cell to map.  `icon_size_px` reads the PNG's IHDR (stdlib
``struct``, no Pillow runtime dependency) so the layer's ``get_icon``
``width``/``height`` always match the shipped sprite.
"""

from __future__ import annotations

import base64
import functools
import struct
from pathlib import Path

# The committed sprite sheet lives beside this module (copied into the runtime
# image by Dockerfile.viz's `COPY viz/ ./viz/`).
ICONS_DIR = Path(__file__).resolve().parent / "icons"


def icon_png_path(source: str) -> Path:
    """Filesystem path of the per-source sprite PNG for ``source``."""
    return ICONS_DIR / f"{source}.png"


def _sprite_path(source: str) -> Path:
    """The source's sprite, falling back to any shipped one when it's absent.

    An unexpected ``energy_source`` has no sprite of its own; like the
    palette's ``DEFAULT_COLOR`` it must still render rather than crash the map
    builder, so the first alphabetically shipped glyph stands in (the layer's
    tint carries the meaning, not the glyph).
    """
    path = icon_png_path(source)
    if path.is_file():
        return path
    candidates = sorted(ICONS_DIR.glob("*.png"))
    if not candidates:
        raise FileNotFoundError(f"No icon sprites found in {ICONS_DIR}")
    return candidates[0]


def png_size(path: Path) -> tuple[int, int]:
    """(width, height) of a PNG from its IHDR header, without Pillow."""
    with path.open("rb") as fh:
        assert fh.read(8) == b"\x89PNG\r\n\x1a\n", f"not a PNG: {path}"
        fh.read(4)  # IHDR chunk length
        assert fh.read(4) == b"IHDR"
        width, height = struct.unpack(">II", fh.read(8))
    return width, height


@functools.lru_cache(maxsize=None)
def icon_size_px(source: str) -> int:
    """Edge length (px) of the per-source sprite — its IHDR width."""
    width, height = png_size(_sprite_path(source))
    assert width == height, f"icon must be square: {source}"
    return width


@functools.lru_cache(maxsize=None)
def icon_data_uri(source: str) -> str:
    """Base64 ``data:image/png;base64,...`` URI of the source's sprite.

    Inlined into the layer via ``iconAtlas``/``get_icon.url`` so the browser
    never issues a separate request (and therefore never serves a stale cached
    copy after the artwork is regenerated).
    """
    encoded = base64.b64encode(_sprite_path(source).read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"
