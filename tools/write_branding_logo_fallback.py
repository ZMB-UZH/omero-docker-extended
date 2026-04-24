"""Write a deterministic fallback branding logo PNG."""

from __future__ import annotations

import argparse
import struct
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


def _point_on_circle_border(
    px: float,
    py: float,
    cx: float,
    cy: float,
    radius: float,
    stroke_width: float,
) -> bool:
    """Return True when the point lies on a circle outline."""
    distance = ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5
    half_stroke = stroke_width / 2.0
    return (radius - half_stroke) <= distance <= (radius + half_stroke)


def _pixel_rgba(x: int, y: int) -> tuple[int, int, int, int]:
    """Render a small neutral placeholder icon on a transparent canvas."""
    px = x + 0.5
    py = y + 0.5

    if _point_on_rounded_rect_border(
        px, py, left=22, top=24, right=74, bottom=70, radius=9, stroke_width=4
    ):
        return STROKE

    if _point_on_circle_border(px, py, cx=48.0, cy=47.0, radius=12.0, stroke_width=3.2):
        return DETAIL

    if _distance_to_segment(px, py, 39.0, 56.0, 57.0, 38.0) <= 2.3:
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
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", checksum)
        )

    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            chunk(b"IHDR", ihdr),
            chunk(b"IDAT", compressed),
            chunk(b"IEND", b""),
        )
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write the deterministic fallback branding logo PNG."
    )
    parser.add_argument("output_path", type=Path, help="PNG output path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Write the fallback logo PNG to the requested path."""
    args = parse_args(argv)
    output_path = args.output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(build_png_bytes())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
