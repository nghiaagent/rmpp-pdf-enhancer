"""
Unit tests for sheet layout, spread grouping and reading direction.
"""

import io
import os
import tempfile
import unittest
import zipfile
from PIL import Image

from rmpp_enhancer.layout import (
    FILL,
    FIT,
    LANDSCAPE,
    PORTRAIT,
    LayoutPlan,
    auto_per_row,
    cell_bounds,
    cell_waste,
    choose_layout,
    compose_sheet,
    pack_rows,
    place_in_cell,
)
from rmpp_enhancer.spreads import (
    classify_pages,
    double_pages_from_comicinfo,
    group_pages,
    is_wide,
    name_marks_joined_spread,
    read_comicinfo,
    reading_direction_from_comicinfo,
    resolve_reading_direction,
)

MANGA = (1500, 2100)
RED, BLUE, WHITE = (255, 0, 0), (0, 0, 255), (255, 255, 255)


class TestAutoPerRow(unittest.TestCase):

    def test_manga_gets_one_up_portrait_two_up_landscape(self):
        self.assertEqual(auto_per_row([MANGA], PORTRAIT), 1)
        self.assertEqual(auto_per_row([MANGA], LANDSCAPE), 2)

    def test_tall_strip_packs_three_across_portrait(self):
        # A 1:4 strip tiles a 3:4 sheet exactly three across
        self.assertEqual(auto_per_row([(525, 2100)], PORTRAIT), 3)
        self.assertAlmostEqual(cell_waste((525, 2100), PORTRAIT, 3), 0.0, places=6)

    def test_wide_page_never_packs_more_than_one(self):
        self.assertEqual(auto_per_row([(2100, 525)], PORTRAIT), 1)
        self.assertEqual(auto_per_row([(2100, 525)], LANDSCAPE), 1)

    def test_uses_median_so_one_odd_page_does_not_swing_it(self):
        sizes = [MANGA] * 9 + [(4000, 400)]
        self.assertEqual(auto_per_row(sizes, LANDSCAPE), 2)


class TestCells(unittest.TestCase):

    def test_cells_tile_the_sheet_exactly(self):
        for per_row in range(1, 9):
            with self.subTest(per_row=per_row):
                bounds = cell_bounds(2160, per_row)
                self.assertEqual(len(bounds), per_row)
                self.assertEqual(bounds[0][0], 0)
                self.assertEqual(bounds[-1][1], 2160)
                for (_, end), (start, _) in zip(bounds, bounds[1:]):
                    self.assertEqual(end, start)   # no gaps, no overlap

    def test_fit_letterboxes_and_fill_covers(self):
        img = Image.new("RGB", (600, 840), RED)
        fitted = place_in_cell(img, (1080, 1620), FIT)
        filled = place_in_cell(img, (1080, 1620), FILL)
        self.assertEqual(fitted.size, (1080, 1620))
        self.assertEqual(filled.size, (1080, 1620))
        # This page is narrower than the cell, so fit pads top and bottom
        self.assertEqual(fitted.getpixel((540, 5)), WHITE)
        self.assertEqual(fitted.getpixel((540, 810)), RED)
        # fill covers the whole cell, corners included
        self.assertEqual(filled.getpixel((540, 5)), RED)
        self.assertEqual(filled.getpixel((5, 810)), RED)


class TestComposeSheet(unittest.TestCase):

    def _pages(self, *colors):
        return [Image.new("RGB", (600, 840), c) for c in colors]

    def test_left_to_right_order(self):
        plan = LayoutPlan(per_row=2, sheet_size=LANDSCAPE)
        sheet = compose_sheet(self._pages(RED, BLUE), plan)
        self.assertEqual(sheet.size, LANDSCAPE)
        self.assertEqual(sheet.getpixel((540, 810)), RED)
        self.assertEqual(sheet.getpixel((1620, 810)), BLUE)

    def test_right_to_left_puts_first_page_on_the_right(self):
        plan = LayoutPlan(per_row=2, sheet_size=LANDSCAPE, rtl=True)
        sheet = compose_sheet(self._pages(RED, BLUE), plan)
        self.assertEqual(sheet.getpixel((1620, 810)), RED)
        self.assertEqual(sheet.getpixel((540, 810)), BLUE)

    def test_part_filled_rtl_row_leaves_blanks_on_the_left(self):
        plan = LayoutPlan(per_row=2, sheet_size=LANDSCAPE, rtl=True)
        sheet = compose_sheet(self._pages(RED), plan)
        self.assertEqual(sheet.getpixel((1620, 810)), RED)
        self.assertEqual(sheet.getpixel((540, 810)), WHITE)

    def test_spread_claims_both_cells(self):
        plan = LayoutPlan(per_row=2, sheet_size=LANDSCAPE)
        wide = Image.new("RGB", (1200, 840), RED)
        sheet = compose_sheet([wide], plan, spans=[2])
        self.assertEqual(sheet.getpixel((540, 810)), RED)
        self.assertEqual(sheet.getpixel((1620, 810)), RED)

    def test_rejects_a_row_that_cannot_hold_its_images(self):
        plan = LayoutPlan(per_row=2, sheet_size=LANDSCAPE)
        with self.assertRaises(ValueError):
            compose_sheet(self._pages(RED, BLUE, RED), plan)


class TestPackRows(unittest.TestCase):

    def test_spread_is_never_split_across_rows(self):
        # spans: three singles, then a spread -> the spread must start a new row
        rows = pack_rows([1, 1, 2, 1], per_row=2)
        self.assertEqual(rows, [[0, 1], [2], [3]])

    def test_oversized_item_gets_its_own_row(self):
        self.assertEqual(pack_rows([2, 1], per_row=1), [[0], [1]])

    def test_every_item_appears_exactly_once(self):
        spans = [1, 2, 1, 1, 2, 1, 1]
        flat = [i for row in pack_rows(spans, per_row=3) for i in row]
        self.assertEqual(sorted(flat), list(range(len(spans))))

    def test_rows_never_exceed_capacity(self):
        spans = [1, 2, 1, 1, 2, 1, 1]
        for row in pack_rows(spans, per_row=3):
            self.assertLessEqual(sum(spans[i] for i in row), 3)


class TestSpreadSignals(unittest.TestCase):

    def test_wide_image_is_a_spread(self):
        self.assertTrue(is_wide((3000, 2100)))
        self.assertFalse(is_wide(MANGA))
        self.assertFalse(is_wide((2100, 2100)))   # square is not wider than tall

    def test_filename_naming_two_consecutive_pages(self):
        self.assertTrue(name_marks_joined_spread("012-013.jpg"))
        self.assertTrue(name_marks_joined_spread("ch1/p012_013.png"))
        self.assertFalse(name_marks_joined_spread("012-015.jpg"))   # not consecutive
        self.assertFalse(name_marks_joined_spread("012.jpg"))

    def test_comicinfo_overrides_aspect(self):
        # Declared false wins even though the image is wide
        flags = classify_pages(["a.jpg"], [(3000, 2100)], declared={0: False})
        self.assertEqual(flags[0], (False, "comicinfo"))

    def test_spread_spans_two_cells_and_one_when_alone_per_row(self):
        names, sizes = ["1.jpg", "2.jpg"], [MANGA, (3000, 2100)]
        self.assertEqual([g.span for g in group_pages(names, sizes, per_row=2)], [1, 2])
        self.assertEqual([g.span for g in group_pages(names, sizes, per_row=1)], [1, 1])

    def test_shift_offsets_pairing_by_one(self):
        names = [f"{i}.jpg" for i in range(4)]
        sizes = [MANGA] * 4
        shifted = group_pages(names, sizes, per_row=2, shift=True)
        self.assertEqual(shifted[0].reason, "shift")
        # The first page must take the whole row, or parity does not move
        self.assertEqual(shifted[0].span, 2)
        rows = pack_rows([g.span for g in shifted], per_row=2)
        self.assertEqual(rows, [[0], [1, 2], [3]])
        # Without the shift the same pages pair 0+1, 2+3
        plain = group_pages(names, sizes, per_row=2, shift=False)
        self.assertEqual(pack_rows([g.span for g in plain], per_row=2), [[0, 1], [2, 3]])


class TestComicInfo(unittest.TestCase):

    def _archive(self, xml):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "v.cbz")
        buf = io.BytesIO()
        Image.new("RGB", (60, 80)).save(buf, "PNG")
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("ComicInfo.xml", xml)
            zf.writestr("001.png", buf.getvalue())
        return path

    def test_reads_right_to_left_manga_flag(self):
        path = self._archive("<ComicInfo><Manga>YesAndRightToLeft</Manga></ComicInfo>")
        self.assertEqual(reading_direction_from_comicinfo(read_comicinfo(path)), "rtl")
        self.assertEqual(resolve_reading_direction("auto", path), ("rtl", "comicinfo"))

    def test_plain_manga_flag_is_left_to_right(self):
        path = self._archive("<ComicInfo><Manga>Yes</Manga></ComicInfo>")
        self.assertEqual(reading_direction_from_comicinfo(read_comicinfo(path)), "ltr")

    def test_explicit_flag_beats_metadata(self):
        path = self._archive("<ComicInfo><Manga>YesAndRightToLeft</Manga></ComicInfo>")
        self.assertEqual(resolve_reading_direction("ltr", path), ("ltr", "requested"))

    def test_double_page_flags(self):
        path = self._archive(
            '<ComicInfo><Pages><Page Image="0" DoublePage="false"/>'
            '<Page Image="1" DoublePage="true"/></Pages></ComicInfo>'
        )
        self.assertEqual(double_pages_from_comicinfo(read_comicinfo(path)), {0: False, 1: True})

    def test_missing_or_corrupt_metadata_is_not_fatal(self):
        self.assertIsNone(read_comicinfo("/nonexistent/x.cbz"))
        self.assertIsNone(reading_direction_from_comicinfo(None))
        self.assertEqual(double_pages_from_comicinfo(None), {})
        bad = self._archive("<ComicInfo><unclosed>")
        self.assertIsNone(read_comicinfo(bad))
        self.assertEqual(resolve_reading_direction("auto", bad), ("ltr", "default"))


class TestChooseLayout(unittest.TestCase):

    def test_default_one_up_keeps_native_page_size(self):
        plan = choose_layout([MANGA], per_row=1, orientation="auto", fit_mode=FIT)
        self.assertIsNone(plan.sheet_size)
        self.assertFalse(plan.composes)

    def test_explicit_orientation_forces_a_sheet(self):
        plan = choose_layout([MANGA], per_row=1, orientation="portrait")
        self.assertEqual(plan.sheet_size, PORTRAIT)

    def test_fill_forces_a_sheet_even_at_one_up(self):
        plan = choose_layout([MANGA], per_row=1, orientation="auto", fit_mode=FILL)
        self.assertIsNotNone(plan.sheet_size)

    def test_auto_picks_two_up_on_a_landscape_sheet(self):
        plan = choose_layout([MANGA], per_row=None, orientation="landscape")
        self.assertEqual((plan.per_row, plan.sheet_size), (2, LANDSCAPE))


if __name__ == "__main__":
    unittest.main()
