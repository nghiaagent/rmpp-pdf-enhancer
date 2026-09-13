"""
Unit and parity tests for the Rust PyO3 accelerator module.
Verifies exact parity between Python and Rust image processing pipelines.
"""

import os
import tempfile
import unittest
import numpy as np
from PIL import Image

from rmpp_enhancer.pipeline import (
    EnhancerConfig,
    HAS_ACCELERATOR,
    process_and_save_page,
    process_image,
    save_page_jpeg,
)


class TestAcceleratorParity(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.test_dir.cleanup()

    def test_accelerator_is_available(self):
        self.assertTrue(HAS_ACCELERATOR, "Rust PyO3 accelerator should be compiled and importable")

    def test_portrait_image_parity(self):
        # 1200 x 1600 gradient image
        arr = np.zeros((1600, 1200, 3), dtype=np.uint8)
        arr[:, :, 0] = np.linspace(0, 255, 1200, dtype=np.uint8)
        arr[:, :, 1] = np.linspace(0, 255, 1600, dtype=np.uint8)[:, None]
        arr[:, :, 2] = 128
        img = Image.fromarray(arr)

        config = EnhancerConfig(quality=82, subsampling=0)

        # 1. Pure Python output
        py_img = process_image(img, config)
        py_jpg = os.path.join(self.test_dir.name, "py_portrait.jpg")
        save_page_jpeg(py_img, py_jpg, config)

        # 2. Rust Accelerator output
        rs_jpg = os.path.join(self.test_dir.name, "rs_portrait.jpg")
        process_and_save_page(img, rs_jpg, config)

        with Image.open(py_jpg) as im_py, Image.open(rs_jpg) as im_rs:
            self.assertEqual(im_py.size, (1620, 2160))
            self.assertEqual(im_rs.size, (1620, 2160))
            self.assertEqual(im_rs.info.get("dpi"), (229, 229))

            arr_py = np.array(im_py, dtype=np.float32)
            arr_rs = np.array(im_rs, dtype=np.float32)
            mean_diff = np.mean(np.abs(arr_py - arr_rs))
            self.assertLess(mean_diff, 2.0, f"Mean pixel difference too high: {mean_diff}")

    def test_landscape_spread_parity(self):
        # 2400 x 1500 landscape image
        arr = np.zeros((1500, 2400, 3), dtype=np.uint8)
        arr[200:1300, 300:2100] = [180, 50, 120]
        img = Image.fromarray(arr)

        config = EnhancerConfig(quality=82, subsampling=0)

        py_img = process_image(img, config)
        py_jpg = os.path.join(self.test_dir.name, "py_landscape.jpg")
        save_page_jpeg(py_img, py_jpg, config)

        rs_jpg = os.path.join(self.test_dir.name, "rs_landscape.jpg")
        process_and_save_page(img, rs_jpg, config)

        with Image.open(py_jpg) as im_py, Image.open(rs_jpg) as im_rs:
            self.assertEqual(im_py.size, (2160, 1350))
            self.assertEqual(im_rs.size, (2160, 1350))

            arr_py = np.array(im_py, dtype=np.float32)
            arr_rs = np.array(im_rs, dtype=np.float32)
            mean_diff = np.mean(np.abs(arr_py - arr_rs))
            self.assertLess(mean_diff, 1.0, f"Mean pixel difference too high: {mean_diff}")


if __name__ == "__main__":
    unittest.main()
