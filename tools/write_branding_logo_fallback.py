"""Write a deterministic fallback branding logo PNG."""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path


WIDTH = 96
HEIGHT = 96
TRANSPARENT = (0, 0, 0, 0)
STROKE = (107, 121, 134, 255)
DETAIL = (107, 121, 134, 208)


def _point_in_rounded_rect(
    px: float,
    py: float,
    left: float,
    top: float,
    right: float,
    bottom: float,
    radius: float,
) -> bool:
    """Return True when the point lies inside the rounded rectangle."""
    clamp_x = min(max(px, left + radius), right - radius)
    clamp_y = min(max(py, top + radius), bottom - radius)
    dx = px - clamp_x
    dy = py - clamp_y
    return (dx * dx) + (dy * dy) <= radius * radius


def _point_on_rounded_rect_border(
    px: float,
    py: float,
    left: float,
    top: float,
    right: float,
    bottom: float,
    radius: float,
    stroke_width: float,
) -> bool:
    """Return True when the point lies on the rounded rectangle border."""
    if not _point_in_rounded_rect(px, py, left, top, right, bottom, radius):
        return False

    inner_radius = max(radius - stroke_width, 0.0)
    return not _point_in_rounded_rect(
        px,
        py,
        left + stroke_width,
        top + stroke_width,
        right - stroke_width,
        bottom - stroke_width,
        inner_radius,
    )


def _distance_to_segment(
    px: float,
    py: float,
    ax: float,
    ay: float,
    bx: float,
    by: float,
) -> float:
    """Return the Euclidean distance from a point to a line segment."""
    dx = bx - ax
    dy = by - ay
    if dx == 0.0 and dy == 0.0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5

    projection = ((px - ax) * dx + (py - ay) * dy) / ((dx * dx) + (dy * dy))
    projection = min(max(projection, 0.0), 1.0)
    nearest_x = ax + projection * dx
    nearest_y = ay + projection * dy
    return ((px - nearest_x) ** 2 + (py - nearest_y) ** 2) ** 0.5


def _pixel_rgba(x: int, y: int) -> tuple[int, int, int, int]:
    """Render a small neutral placeholder icon on a transparent canvas."""
    px = x + 0.5
    py = y + 0.5

    if _point_on_rounded_rect_border(
        px, py, left=22, top=24, right=74, bottom=70, radius=9, stroke_width=4
    ):
        return STROKE

    if ((px - 61.0) ** 2) + ((py - 38.0) ** 2) <= 5.0**2:
        return DETAIL

    mountain_segments = (
        (30.0, 60.0, 42.0, 48.0),
        (42.0, 48.0, 51.0, 56.0),
        (51.0, 56.0, 63.0, 45.0),
        (63.0, 45.0, 71.0, 53.0),
    )
    for ax, ay, bx, by in mountain_segments:
        if _distance_to_segment(px, py, ax, ay, bx, by) <= 2.1:
            return DETAIL

    if abs(py - 60.0) <= 1.2 and 30.0 <= px <= 71.0:
        return DETAIL

    return TRANSPARENT


def build_png_bytes() -> bytes:
    """Build the fallback PNG bytes."""
    rows = bytearray()
    for y in range(HEIGHT):
        rows.append(0)
        for x in range(WIDTH):
            rows.extend(_pixel_rgba(x, y))

    compressed = zlib.compress(bytes(rows), level=9)
    ihdr = struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 6, 0, 0, 0)

    def chunk(tag: bytes, payload: bytes) -> bytes:
        checksum = zlib.crc32(tag + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", checksum)

    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            chunk(b"IHDR", ihdr),
            chunk(b"IDAT", compressed),
            chunk(b"IEND", b""),
        )
    )


def main(argv: list[str]) -> int:
    """Write the fallback logo PNG to the requested path."""
    if len(argv) != 2:
        print(
            "usage: write_branding_logo_fallback.py <output-path>",
            file=sys.stderr,
        )
        return 1

    output_path = Path(argv[1]).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(build_png_bytes())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
