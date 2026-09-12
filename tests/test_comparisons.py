"""
Unit tests for side-by-side benchmark comparison generation.
"""

import os
import unittest
from PIL import Image
from rmpp_enhancer.pipeline import EnhancerConfig, load_3d_lut
from scripts.generate_illustration_comparisons import (
    create_comparison_page,
    prepare_original_panel,
    CANVAS_W,
    CANVAS_H,
    PANEL_W,
    PANEL_H,
)


class TestIllustrationComparisons(unittest.TestCase):

    def setUp(self):
        self.config = EnhancerConfig(quality=82, subsampling=0)
        self.pil_lut = load_3d_lut(self.config.lut_path)
        self.test_img_path = "/tmp/test_compare_dummy.png"

        # Create dummy test image (300 x 300)
        img = Image.new("RGB", (300, 300), (120, 180, 240))
        img.save(self.test_img_path)

    def tearDown(self):
        if os.path.exists(self.test_img_path):
            os.remove(self.test_img_path)

    def test_prepare_original_panel_cover(self):
        panel = prepare_original_panel(self.test_img_path, fit_mode="cover")
        self.assertEqual(panel.size, (PANEL_W, PANEL_H))

    def test_prepare_original_panel_fit_white(self):
        panel = prepare_original_panel(self.test_img_path, fit_mode="fit_white")
        self.assertEqual(panel.size, (PANEL_W, PANEL_H))
        # Top-left corner should be pure white background
        self.assertEqual(panel.getpixel((0, 0)), (255, 255, 255))

    def test_create_comparison_page(self):
        spec = {
            "num": 99,
            "title": "Dummy test comparison",
            "file": self.test_img_path,
            "fit_mode": "cover",
            "id": "dummy_test",
        }
        page = create_comparison_page(spec, self.config, self.pil_lut)
        self.assertEqual(page.size, (CANVAS_W, CANVAS_H))
        self.assertEqual(page.size, (2160, 1620))


if __name__ == "__main__":
    unittest.main()
