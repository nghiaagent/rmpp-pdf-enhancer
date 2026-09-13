"""
End-to-end parity tests between the Python reference pipeline and the Rust implementation.
"""

import os
import subprocess
import tempfile
import unittest
import numpy as np
from PIL import Image
import pymupdf

from rmpp_enhancer.pipeline import EnhancerConfig, process_image, save_page_jpeg
from rmpp_enhancer.pdf_builder import compile_pdf


class TestRustParity(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Locate release binary or build debug binary if release doesn't exist
        cls.rust_bin = os.path.abspath("target/release/rmpp-pdf-enhancer")
        if not os.path.exists(cls.rust_bin):
            cls.rust_bin = os.path.abspath("target/debug/rmpp-pdf-enhancer")
            if not os.path.exists(cls.rust_bin):
                subprocess.run(["cargo", "build", "--release"], check=True)
                cls.rust_bin = os.path.abspath("target/release/rmpp-pdf-enhancer")

    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.test_dir.cleanup()

    def test_single_image_parity(self):
        # Input test image: 1200 x 1600 color gradient
        input_img_path = os.path.join(self.test_dir.name, "input.png")
        arr = np.zeros((1600, 1200, 3), dtype=np.uint8)
        arr[:, :, 0] = np.linspace(0, 255, 1200, dtype=np.uint8)
        arr[:, :, 1] = np.linspace(0, 255, 1600, dtype=np.uint8)[:, None]
        arr[:, :, 2] = 128
        Image.fromarray(arr).save(input_img_path)

        # 1. Run Python pipeline
        config = EnhancerConfig(quality=82, subsampling=0)
        im = Image.open(input_img_path)
        py_page = process_image(im, config)
        py_jpg = os.path.join(self.test_dir.name, "py_page.jpg")
        save_page_jpeg(py_page, py_jpg, config)
        py_pdf = os.path.join(self.test_dir.name, "py_out.pdf")
        compile_pdf([py_jpg], py_pdf)

        # 2. Run Rust CLI
        rs_pdf = os.path.join(self.test_dir.name, "rs_out.pdf")
        res = subprocess.run(
            [self.rust_bin, input_img_path, "-o", rs_pdf, "-f"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, f"Rust CLI failed: {res.stderr}")
        self.assertTrue(os.path.exists(rs_pdf))

        # 3. Compare PDFs
        doc_py = pymupdf.open(py_pdf)
        doc_rs = pymupdf.open(rs_pdf)

        self.assertEqual(len(doc_py), len(doc_rs))

        rect_py = doc_py[0].rect
        rect_rs = doc_rs[0].rect
        self.assertAlmostEqual(rect_py.width, rect_rs.width, places=2)
        self.assertAlmostEqual(rect_py.height, rect_rs.height, places=2)

        # Compare pixel samples rendered at native 229 DPI
        pix_py = doc_py[0].get_pixmap(dpi=229)
        pix_rs = doc_rs[0].get_pixmap(dpi=229)
        self.assertEqual(pix_py.width, pix_rs.width)
        self.assertEqual(pix_py.height, pix_rs.height)

        samples_py = np.frombuffer(pix_py.samples, dtype=np.uint8).astype(np.int32)
        samples_rs = np.frombuffer(pix_rs.samples, dtype=np.uint8).astype(np.int32)
        mean_diff = np.mean(np.abs(samples_py - samples_rs))

        # Mean pixel diff must be < 1.0 (out of 255)
        self.assertLess(mean_diff, 1.0)

    def test_chapter_bookmarks_parity(self):
        # Create multi-chapter directory structure
        ch1_dir = os.path.join(self.test_dir.name, "Chapter 1")
        ch2_dir = os.path.join(self.test_dir.name, "Chapter 2")
        os.makedirs(ch1_dir)
        os.makedirs(ch2_dir)

        img1 = Image.new("RGB", (200, 300), (200, 100, 50))
        img2 = Image.new("RGB", (200, 300), (50, 100, 200))
        img1.save(os.path.join(ch1_dir, "01.png"))
        img2.save(os.path.join(ch2_dir, "01.png"))

        rs_pdf = os.path.join(self.test_dir.name, "rs_chapters.pdf")
        res = subprocess.run(
            [self.rust_bin, self.test_dir.name, "-o", rs_pdf, "-f"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, f"Rust CLI failed: {res.stderr}")

        doc = pymupdf.open(rs_pdf)
        self.assertEqual(len(doc), 2)
        toc = doc.get_toc()
        # Should have 2 chapter bookmarks
        self.assertEqual(len(toc), 2)
        self.assertEqual(toc[0][1], "Chapter 1")
        self.assertEqual(toc[0][2], 1)
        self.assertEqual(toc[1][1], "Chapter 2")
        self.assertEqual(toc[1][2], 2)

    def test_cli_skip_idempotence(self):
        img_path = os.path.join(self.test_dir.name, "dummy.png")
        Image.new("RGB", (100, 100), (128, 128, 128)).save(img_path)

        out_pdf = os.path.join(self.test_dir.name, "dummy_out.pdf")

        # First run: generates PDF
        res1 = subprocess.run(
            [self.rust_bin, img_path, "-o", out_pdf],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res1.returncode, 0)
        self.assertTrue(os.path.exists(out_pdf))
        mtime1 = os.path.getmtime(out_pdf)

        # Second run without force: should skip
        res2 = subprocess.run(
            [self.rust_bin, img_path, "-o", out_pdf],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res2.returncode, 0)
        self.assertIn("Skipping", res2.stdout)
        self.assertEqual(os.path.getmtime(out_pdf), mtime1)

        # Third run with force: should overwrite
        res3 = subprocess.run(
            [self.rust_bin, img_path, "-o", out_pdf, "-f"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res3.returncode, 0)
        self.assertIn("Generated", res3.stdout)


if __name__ == "__main__":
    unittest.main()
