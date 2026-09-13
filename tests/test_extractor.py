"""
Unit tests for archive/directory page discovery and PDF page loading.
"""

import io
import os
import tempfile
import unittest
import zipfile
from PIL import Image
import pymupdf

from rmpp_enhancer.extractor import (
    extract_document,
    extract_from_directory,
    extract_from_zip,
    is_image_member,
)


def _png_bytes(color=(10, 20, 30), size=(40, 60)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


class TestImageMemberFilter(unittest.TestCase):

    def test_accepts_plain_images(self):
        self.assertTrue(is_image_member("001.jpg"))
        self.assertTrue(is_image_member("ch1/002.PNG"))

    def test_rejects_macos_sidecars_and_dotfiles(self):
        self.assertFalse(is_image_member("__MACOSX/ch1/._001.png"))
        self.assertFalse(is_image_member("ch1/._001.png"))
        self.assertFalse(is_image_member("ch1/.DS_Store.png"))

    def test_rejects_directories_and_non_images(self):
        self.assertFalse(is_image_member("ch1/"))
        self.assertFalse(is_image_member("notes.txt"))


class TestZipExtraction(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_macos_zip_artifacts_are_ignored(self):
        path = os.path.join(self.tmp.name, "comic.cbz")
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("ch1/001.png", _png_bytes())
            zf.writestr("ch1/002.png", _png_bytes())
            zf.writestr("__MACOSX/ch1/._001.png", b"\x00\x05\x16\x07not an image")
            zf.writestr("ch1/.DS_Store.png", b"junk")

        doc = extract_from_zip(path)
        self.assertEqual(len(doc.pages), 2)
        self.assertEqual(doc.chapters, [("ch1", 1)])
        # Every discovered page must actually decode
        for page in doc.pages:
            self.assertIsInstance(page.load_image(), Image.Image)

    def test_root_level_pages_clear_chapter_state(self):
        path = os.path.join(self.tmp.name, "mixed.cbz")
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("a_ch/001.png", _png_bytes())
            zf.writestr("zz_root.png", _png_bytes())

        doc = extract_from_zip(path)
        self.assertEqual([p.chapter_name for p in doc.pages], ["a_ch", None])


class TestDirectoryExtraction(unittest.TestCase):

    def test_dotfiles_in_directories_are_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            Image.new("RGB", (40, 60)).save(os.path.join(d, "001.png"))
            with open(os.path.join(d, "._001.png"), "wb") as f:
                f.write(b"resource fork")

            doc = extract_from_directory(d)
            self.assertEqual(len(doc.pages), 1)


class TestPdfExtraction(unittest.TestCase):

    def test_pages_load_in_order_across_repeated_access(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "doc.pdf")
            src = pymupdf.open()
            for i in range(3):
                page = src.new_page()
                page.insert_text((72, 200), f"Page {i}")
            src.save(path)
            src.close()

            doc = extract_document(path)
            self.assertEqual(len(doc.pages), 3)
            # Load twice to exercise the cached per-thread handle
            first = [p.load_image().size for p in doc.pages]
            second = [p.load_image().size for p in doc.pages]
            self.assertEqual(first, second)
            self.assertTrue(all(s[1] == 2160 for s in first))


if __name__ == "__main__":
    unittest.main()
