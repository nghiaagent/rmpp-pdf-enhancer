"""
Unit tests for CLI skip behavior and idempotence.
"""

import os
import tempfile
import unittest
from PIL import Image
from rmpp_enhancer.cli import enhance_document


class TestCliSkipBehavior(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        # Create a sample test image
        self.img_path = os.path.join(self.test_dir.name, "sample_document.png")
        img = Image.new("RGB", (200, 300), (255, 255, 255))
        img.save(self.img_path)

    def tearDown(self):
        self.test_dir.cleanup()

    def test_skip_existing_output_without_force(self):
        # 1. Process document first time
        out_pdf = enhance_document(self.img_path)
        self.assertTrue(os.path.exists(out_pdf))
        mtime_initial = os.path.getmtime(out_pdf)

        # 2. Process again without force: should skip and not overwrite
        out_pdf_2 = enhance_document(self.img_path, force=False)
        self.assertEqual(out_pdf, out_pdf_2)
        self.assertEqual(os.path.getmtime(out_pdf), mtime_initial)

    def test_force_overwrites_existing_output(self):
        out_pdf = enhance_document(self.img_path)
        self.assertTrue(os.path.exists(out_pdf))

        # Re-run with force=True
        out_pdf_forced = enhance_document(self.img_path, force=True)
        self.assertEqual(out_pdf, out_pdf_forced)
        self.assertTrue(os.path.exists(out_pdf_forced))


if __name__ == "__main__":
    unittest.main()
