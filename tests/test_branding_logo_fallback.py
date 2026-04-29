from __future__ import annotations

import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class BrandingLogoFallbackTests(unittest.TestCase):
    """Test cases for branding logo fallback tests."""

    @classmethod
    def setUpClass(cls) -> None:
        """Store set up class."""
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.writer_script = cls.repo_root / "tools" / "write_branding_logo_fallback.py"

    def test_fallback_writer_creates_deterministic_png(self) -> None:
        """Verify test fallback writer creates deterministic png."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            first_path = Path(tmp_dir) / "first.png"
            second_path = Path(tmp_dir) / "second.png"

            subprocess.run(
                [sys.executable, str(self.writer_script), str(first_path)],
                check=True,
            )
            subprocess.run(
                [sys.executable, str(self.writer_script), str(second_path)],
                check=True,
            )

            first_bytes = first_path.read_bytes()
            second_bytes = second_path.read_bytes()

            self.assertEqual(first_bytes, second_bytes)
            self.assertTrue(first_bytes.startswith(PNG_SIGNATURE))

    def test_fallback_writer_png_dimensions_and_content(self) -> None:
        """Verify test fallback writer png dimensions and content."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "fallback.png"

            subprocess.run(
                [sys.executable, str(self.writer_script), str(output_path)],
                check=True,
            )

            png_bytes = output_path.read_bytes()
            self.assertTrue(png_bytes.startswith(PNG_SIGNATURE))

            ihdr_length = struct.unpack(">I", png_bytes[8:12])[0]
            self.assertEqual(ihdr_length, 13)
            self.assertEqual(png_bytes[12:16], b"IHDR")
            (
                width,
                height,
                bit_depth,
                color_type,
                compression,
                filter_method,
                interlace,
            ) = struct.unpack(">IIBBBBB", png_bytes[16:29])
            self.assertEqual((width, height), (96, 96))
            self.assertEqual(
                (bit_depth, color_type, compression, filter_method, interlace),
                (8, 6, 0, 0, 0),
            )

            compressed_payload_length = struct.unpack(">I", png_bytes[33:37])[0]
            self.assertEqual(png_bytes[37:41], b"IDAT")
            compressed_payload = png_bytes[41 : 41 + compressed_payload_length]
            raw_rows = zlib.decompress(compressed_payload)
            self.assertEqual(len(raw_rows), 96 * (1 + (96 * 4)))

            def pixel_rgba(x: int, y: int) -> tuple[int, int, int, int]:
                """Handle pixel rgba."""
                row_start = y * (1 + (96 * 4))
                row_bytes = raw_rows[row_start + 1 : row_start + 1 + (96 * 4)]
                pixel_start = x * 4
                return tuple(row_bytes[pixel_start : pixel_start + 4])

            opaque_pixels = 0
            for row_index in range(96):
                row_start = row_index * (1 + (96 * 4))
                self.assertEqual(raw_rows[row_start], 0)
                row_bytes = raw_rows[row_start + 1 : row_start + 1 + (96 * 4)]
                for pixel_offset in range(0, len(row_bytes), 4):
                    if row_bytes[pixel_offset + 3] != 0:
                        opaque_pixels += 1

            self.assertGreater(opaque_pixels, 250)
            self.assertEqual(pixel_rgba(24, 30), (107, 121, 134, 255))
            self.assertEqual(pixel_rgba(48, 35), (107, 121, 134, 208))
            self.assertEqual(pixel_rgba(48, 42), (0, 0, 0, 0))
            self.assertEqual(pixel_rgba(48, 47), (107, 121, 134, 208))
            self.assertEqual(pixel_rgba(54, 47), (0, 0, 0, 0))
            self.assertEqual(pixel_rgba(70, 68), (0, 0, 0, 0))


if __name__ == "__main__":
    unittest.main()
