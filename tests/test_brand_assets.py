"""Verify the local Home Assistant branding assets and their PNG dimensions."""
from pathlib import Path
import struct
import unittest


BRAND = Path(__file__).parents[1] / "custom_components/mcp_domora/brand"


class BrandAssetsTests(unittest.TestCase):
    def test_png_dimensions_and_alpha(self):
        for filename, size in (
            ("icon.png", 256),
            ("icon@2x.png", 512),
            ("dark_icon.png", 256),
            ("dark_icon@2x.png", 512),
        ):
            with self.subTest(filename=filename):
                data = (BRAND / filename).read_bytes()
                self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
                self.assertEqual(data[12:16], b"IHDR")
                self.assertEqual(struct.unpack(">II", data[16:24]), (size, size))
                self.assertEqual(data[25], 6, "Expected RGBA PNG")


if __name__ == "__main__":
    unittest.main()
