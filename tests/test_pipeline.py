"""
Unit tests for rmpp-pdf-enhancer.
"""

import os
import unittest
from PIL import Image
from rmpp_enhancer.pipeline import (
    EnhancerConfig,
    load_3d_lut,
    prepare_rgb,
    scale_to_rmpp_geometry,
    apply_edge_directed_inking,
    process_image,
)
from rmpp_enhancer.pdf_builder import compile_pdf


class TestRmppPipeline(unittest.TestCase):

    def test_load_default_lut(self):
        lut = load_3d_lut()
        self.assertIsNotNone(lut)

    def test_prepare_rgb_alpha(self):
        # Create image with transparent alpha
        rgba = Image.new("RGBA", (100, 100), (255, 0, 0, 0))
        rgb = prepare_rgb(rgba)
        self.assertEqual(rgb.mode, "RGB")
        # Fully transparent pixel should become pure white (255, 255, 255)
        self.assertEqual(rgb.getpixel((50, 50)), (255, 255, 255))

    def test_option_a_scaling_portrait(self):
        config = EnhancerConfig()
        # 1080x1920 portrait
        im = Image.new("RGB", (1080, 1920), (128, 128, 128))
        scaled = scale_to_rmpp_geometry(im, config)
        # Height must be 2160
        self.assertEqual(scaled.size[1], 2160)
        self.assertEqual(scaled.size[0], 1215)

    def test_option_a_scaling_landscape(self):
        config = EnhancerConfig()
        # 1920x1080 landscape
        im = Image.new("RGB", (1920, 1080), (128, 128, 128))
        scaled = scale_to_rmpp_geometry(im, config)
        # Width must fit within 2160x1620
        self.assertTrue(scaled.size[0] <= 2160 and scaled.size[1] <= 1620)

    def test_spread_splitting_rtl(self):
        config = EnhancerConfig(split_spreads=True, spread_direction="rtl")
        # Double spread 3000 x 1500 (2:1 aspect ratio)
        im = Image.new("RGB", (3000, 1500), (200, 200, 200))
        pages = process_image(im, config)
        self.assertEqual(len(pages), 2)
        # Both pages should be portrait
        self.assertTrue(pages[0].size[1] >= pages[0].size[0])
        self.assertTrue(pages[1].size[1] >= pages[1].size[0])

    def test_full_pipeline_and_pdf_generation(self):
        config = EnhancerConfig(quality=82)
        im = Image.new("RGB", (800, 1200), (100, 150, 200))
        pages = process_image(im, config)
        self.assertEqual(len(pages), 1)

        test_jpg = "/tmp/rmpp_unit_test.jpg"
        pages[0].save(test_jpg, "JPEG", quality=config.quality, dpi=(config.dpi, config.dpi))
        self.assertTrue(os.path.exists(test_jpg))

        test_pdf = "/tmp/rmpp_unit_test.pdf"
        compile_pdf([test_jpg], test_pdf, chapters=[("Chapter 1", 1)])
        self.assertTrue(os.path.exists(test_pdf))
        self.assertTrue(os.path.getsize(test_pdf) > 0)

        # Cleanup
        os.remove(test_jpg)
        os.remove(test_pdf)


if __name__ == "__main__":
    unittest.main()
