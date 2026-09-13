"""
Unit tests for output path derivation and the shared panel geometry rule.
"""

import os
import tempfile
import unittest

from rmpp_enhancer.cli import OPTIMIZED_SUFFIX, optimized_output_path
from rmpp_enhancer.pipeline import (
    RMPP_LONG_SIDE,
    RMPP_SHORT_SIDE,
    EnhancerConfig,
    rmpp_fit_scale,
    scale_to_rmpp_geometry,
)
from PIL import Image


class TestOptimizedOutputPath(unittest.TestCase):

    def test_trailing_separator_keeps_directory_name(self):
        # Shell tab-completion appends the separator; the stem must survive it
        with_sep = optimized_output_path("/tmp/scanned_pages/")
        without_sep = optimized_output_path("/tmp/scanned_pages")
        self.assertEqual(with_sep, without_sep)
        self.assertEqual(
            os.path.basename(with_sep), f"scanned_pages{OPTIMIZED_SUFFIX}.pdf"
        )

    def test_file_output_sits_next_to_input(self):
        out = optimized_output_path("/tmp/books/Textbook.pdf")
        self.assertEqual(
            out, os.path.join("/tmp/books", f"Textbook{OPTIMIZED_SUFFIX}.pdf")
        )

    def test_dest_dir_overrides_parent(self):
        out = optimized_output_path("/tmp/books/Textbook.pdf", dest_dir="/out")
        self.assertEqual(out, os.path.join("/out", f"Textbook{OPTIMIZED_SUFFIX}.pdf"))

    def test_relative_input_resolves_to_a_real_directory(self):
        out = optimized_output_path("Textbook.pdf")
        self.assertTrue(os.path.isabs(out))
        self.assertTrue(os.path.isdir(os.path.dirname(out)))


class TestRmppFitScale(unittest.TestCase):

    def test_portrait_fills_the_long_side(self):
        scale = rmpp_fit_scale(1080, 1920)
        self.assertAlmostEqual(round(1920 * scale), RMPP_LONG_SIDE)
        self.assertLessEqual(round(1080 * scale), RMPP_SHORT_SIDE)

    def test_landscape_uses_the_rotated_panel(self):
        scale = rmpp_fit_scale(1920, 1080)
        self.assertLessEqual(round(1920 * scale), RMPP_LONG_SIDE)
        self.assertLessEqual(round(1080 * scale), RMPP_SHORT_SIDE)

    def test_square_is_treated_as_portrait(self):
        self.assertEqual(rmpp_fit_scale(500, 500), RMPP_SHORT_SIDE / 500)

    def test_scaler_agrees_with_the_shared_rule(self):
        config = EnhancerConfig()
        for size in [(1080, 1920), (1920, 1080), (800, 800), (3000, 1000)]:
            with self.subTest(size=size):
                scaled = scale_to_rmpp_geometry(Image.new("RGB", size), config)
                expected = rmpp_fit_scale(*size)
                self.assertEqual(
                    scaled.size,
                    (
                        max(1, round(size[0] * expected)),
                        max(1, round(size[1] * expected)),
                    ),
                )


class TestPdfRenderMatchesScaler(unittest.TestCase):

    def test_rendered_pdf_page_needs_no_further_resize(self):
        import pymupdf

        from rmpp_enhancer.extractor import extract_document

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "doc.pdf")
            src = pymupdf.open()
            src.new_page(width=612, height=792)
            src.save(path)
            src.close()

            page = extract_document(path).pages[0].load_image()
            # The renderer and the scaler share one rule, so scaling is a no-op
            self.assertEqual(
                scale_to_rmpp_geometry(page, EnhancerConfig()).size, page.size
            )
            # US Letter is wider than the panel's aspect, so width is the limit
            self.assertEqual(page.size, (RMPP_SHORT_SIDE, 2097))


if __name__ == "__main__":
    unittest.main()
