"""
Unit tests for rmpp-pdf-enhancer.
"""

import os
import tempfile
import unittest
from PIL import Image

from rmpp_enhancer.pdf_builder import compile_pdf
from rmpp_enhancer.pipeline import EnhancerConfig, prepare_rgb, process_and_save_page


class TestRmppPipeline(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.test_dir.cleanup()

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
        dst_path = os.path.join(self.test_dir.name, "portrait.jpg")
        process_and_save_page(im, dst_path, config)

        self.assertTrue(os.path.exists(dst_path))
        with Image.open(dst_path) as out_im:
            # Height must be 2160, width 1215
            self.assertEqual(out_im.size, (1215, 2160))
            self.assertEqual(out_im.info.get("dpi"), (229, 229))

    def test_option_a_scaling_landscape(self):
        config = EnhancerConfig()
        # 1920x1080 landscape
        im = Image.new("RGB", (1920, 1080), (128, 128, 128))
        dst_path = os.path.join(self.test_dir.name, "landscape.jpg")
        process_and_save_page(im, dst_path, config)

        self.assertTrue(os.path.exists(dst_path))
        with Image.open(dst_path) as out_im:
            # Width must fit within 2160x1620 (scaled to 2160x1215)
            self.assertTrue(out_im.size[0] <= 2160 and out_im.size[1] <= 1620)
            self.assertEqual(out_im.size, (2160, 1215))
            self.assertEqual(out_im.info.get("dpi"), (229, 229))

    def test_enhancement_options_toggle(self):
        im = Image.new("RGB", (400, 600), (200, 100, 50))
        dst_plain = os.path.join(self.test_dir.name, "plain.jpg")
        config_plain = EnhancerConfig(color_correction=False, edge_inking=False)
        process_and_save_page(im, dst_plain, config_plain)
        self.assertTrue(os.path.exists(dst_plain))

    def test_full_pipeline_and_pdf_generation(self):
        config = EnhancerConfig(quality=82)
        im = Image.new("RGB", (800, 1200), (100, 150, 200))
        test_jpg = os.path.join(self.test_dir.name, "page.jpg")
        process_and_save_page(im, test_jpg, config)
        self.assertTrue(os.path.exists(test_jpg))

        test_pdf = os.path.join(self.test_dir.name, "output.pdf")
        compile_pdf([test_jpg], test_pdf, chapters=[("Chapter 1", 1)])
        self.assertTrue(os.path.exists(test_pdf))
        self.assertTrue(os.path.getsize(test_pdf) > 0)


if __name__ == "__main__":
    unittest.main()

