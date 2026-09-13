"""
End-to-end tests for sheet assembly: page grouping, bookmark remapping, output geometry.
"""

import io
import os
import sys
import tempfile
import unittest
import zipfile
import pymupdf
from PIL import Image

from rmpp_enhancer.cli import build_sheets, enhance_document, remap_chapters
from rmpp_enhancer.extractor import extract_document
from rmpp_enhancer.layout import choose_layout
from rmpp_enhancer.pipeline import EnhancerConfig

COMICINFO_RTL = (
    '<?xml version="1.0"?><ComicInfo><Manga>YesAndRightToLeft</Manga><Pages>'
    '<Page Image="0" DoublePage="false"/><Page Image="1" DoublePage="false"/>'
    '<Page Image="2" DoublePage="true"/><Page Image="3" DoublePage="false"/>'
    '<Page Image="4" DoublePage="false"/><Page Image="5" DoublePage="false"/>'
    "</Pages></ComicInfo>"
)


def _jpeg(width=1500, height=2100):
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (245, 244, 240)).save(buf, "JPEG", quality=85)
    return buf.getvalue()


class TestRemapChapters(unittest.TestCase):

    def test_bookmarks_follow_pages_onto_their_sheet(self):
        # Pages 1..6 paired two per sheet -> sheets 1,1,2,2,3,3
        page_to_sheet = {1: 1, 2: 1, 3: 2, 4: 2, 5: 3, 6: 3}
        chapters = [("One", 1), ("Two", 3), ("Three", 5)]
        self.assertEqual(
            remap_chapters(chapters, page_to_sheet),
            [("One", 1), ("Two", 2), ("Three", 3)],
        )

    def test_unknown_page_is_left_alone(self):
        self.assertEqual(remap_chapters([("X", 9)], {1: 1}), [("X", 9)])


class TestBuildSheets(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.archive = os.path.join(self.tmp.name, "Volume01.cbz")
        with zipfile.ZipFile(self.archive, "w") as zf:
            zf.writestr("ComicInfo.xml", COMICINFO_RTL)
            for i in range(6):
                wide = _jpeg(3000, 2100) if i == 2 else _jpeg()
                zf.writestr(f"{i + 1:03d}.jpg", wide)

    def tearDown(self):
        self.tmp.cleanup()

    def test_declared_spread_takes_a_sheet_of_its_own(self):
        doc = extract_document(self.archive)
        config = EnhancerConfig(per_row=2, orientation="landscape")
        plan = choose_layout([p.size() for p in doc.pages], per_row=2, orientation="landscape")
        tasks, page_to_sheet = build_sheets(doc, plan, config)

        # pages 1+2 | spread 3 alone | pages 4+5 | page 6
        self.assertEqual([len(t.pages) for t in tasks], [2, 1, 2, 1])
        self.assertEqual(tasks[1].spans, (2,))
        self.assertEqual(page_to_sheet[3], 2)
        # every source page lands on exactly one sheet
        self.assertEqual(sorted(page_to_sheet), list(range(1, 7)))

    def test_every_page_is_placed_exactly_once(self):
        doc = extract_document(self.archive)
        for per_row in (1, 2, 3):
            with self.subTest(per_row=per_row):
                config = EnhancerConfig(per_row=per_row, orientation="landscape")
                plan = choose_layout(
                    [p.size() for p in doc.pages], per_row=per_row, orientation="landscape"
                )
                tasks, _ = build_sheets(doc, plan, config)
                placed = [p for t in tasks for p in t.pages]
                self.assertEqual(len(placed), len(doc.pages))
                self.assertEqual(
                    [p.page_number for p in placed], [p.page_number for p in doc.pages]
                )


class TestEndToEnd(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.archive = os.path.join(self.tmp.name, "Volume01.cbz")
        with zipfile.ZipFile(self.archive, "w") as zf:
            zf.writestr("ComicInfo.xml", COMICINFO_RTL)
            for i in range(6):
                zf.writestr(f"{i + 1:03d}.jpg", _jpeg(3000, 2100) if i == 2 else _jpeg())

    def tearDown(self):
        self.tmp.cleanup()

    def _build(self, **kwargs):
        out = os.path.join(self.tmp.name, f"out_{len(kwargs)}_{id(kwargs)}.pdf")
        enhance_document(self.archive, output_path=out, config=EnhancerConfig(**kwargs), force=True)
        return out

    def test_default_is_one_sheet_per_page(self):
        doc = pymupdf.open(self._build())
        self.assertEqual(len(doc), 6)
        doc.close()

    def test_two_up_landscape_produces_landscape_sheets(self):
        doc = pymupdf.open(self._build(per_row=2, orientation="landscape"))
        self.assertEqual(len(doc), 4)   # 2 + spread + 2 + 1
        for page in doc:
            self.assertGreater(page.rect.width, page.rect.height)
        doc.close()

    def test_auto_landscape_matches_explicit_two_up(self):
        auto = pymupdf.open(self._build(per_row=None, orientation="landscape"))
        explicit = pymupdf.open(self._build(per_row=2, orientation="landscape"))
        self.assertEqual(len(auto), len(explicit))
        auto.close()
        explicit.close()

    def test_splitting_spreads_is_opt_out(self):
        together = pymupdf.open(self._build(per_row=2, orientation="landscape"))
        apart = pymupdf.open(
            self._build(per_row=2, orientation="landscape", keep_spreads_together=False)
        )
        # Letting the spread share a cell packs the volume more tightly
        self.assertLess(len(apart), len(together))
        together.close()
        apart.close()


class TestCliFlags(unittest.TestCase):
    """The layout flags must parse to the config values they advertise."""

    def _parse(self, *argv):
        import rmpp_enhancer.cli as cli

        captured = {}
        original = cli.enhance_document
        cli.enhance_document = lambda *a, **k: captured.update(k) or ""
        old_argv = sys.argv
        sys.argv = ["rmpp-pdf-enhancer", "dummy.cbz", *argv]
        try:
            cli.main()
        finally:
            cli.enhance_document = original
            sys.argv = old_argv
        return captured["config"]

    def test_defaults(self):
        cfg = self._parse()
        self.assertEqual(cfg.per_row, 1)
        self.assertEqual(cfg.orientation, "auto")
        self.assertEqual(cfg.fit_mode, "fit")
        self.assertEqual(cfg.reading_direction, "auto")
        self.assertTrue(cfg.keep_spreads_together)
        self.assertFalse(cfg.shift_pages)

    def test_keep_spreads_both_forms(self):
        self.assertTrue(self._parse("--keep-spreads").keep_spreads_together)
        self.assertFalse(self._parse("--no-keep-spreads").keep_spreads_together)

    def test_auto_per_row_becomes_none(self):
        self.assertIsNone(self._parse("--per-row", "auto").per_row)
        self.assertEqual(self._parse("--per-row", "3").per_row, 3)

    def test_orientation_aliases(self):
        self.assertEqual(self._parse("--orientation", "horizontal").orientation, "landscape")
        self.assertEqual(self._parse("--orientation", "vertical").orientation, "portrait")

    def test_rejects_out_of_range_per_row(self):
        with self.assertRaises(SystemExit):
            self._parse("--per-row", "99")
        with self.assertRaises(SystemExit):
            self._parse("--per-row", "banana")


if __name__ == "__main__":
    unittest.main()
