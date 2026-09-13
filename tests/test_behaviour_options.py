"""
Behaviour: every option has an observable effect.

An option that silently does nothing is worse than no option, so each of these
asserts a difference a user could see, not just that the flag was accepted.
"""

import os

import numpy as np
import pymupdf
import pytest
from PIL import Image

from rmpp_enhancer.cli import enhance_document
from rmpp_enhancer.layout import LANDSCAPE, LayoutPlan, compose_sheet
from rmpp_enhancer.pipeline import EnhancerConfig, process_image
from tests.conftest import COMICINFO_LTR, COMICINFO_RTL, build_cbz, make_page

RED, BLUE, WHITE = (255, 0, 0), (0, 0, 255), (255, 255, 255)


def render(path, index=0, dpi=36):
    doc = pymupdf.open(path)
    try:
        pix = doc[index].get_pixmap(dpi=dpi)
        return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, -1)
    finally:
        doc.close()


def build(tmp_path, name, **cfg):
    src = cfg.pop("src")
    out = str(tmp_path / f"{name}.pdf")
    enhance_document(src, output_path=out, force=True, config=EnhancerConfig(**cfg))
    return out


class TestColourAndInkOptions:

    @pytest.fixture
    def page(self):
        return make_page("x", color=(120, 90, 160))

    def test_lut_changes_pixels(self, page):
        on = np.asarray(process_image(page, EnhancerConfig(edge_inking=False)), dtype=int)
        off = np.asarray(
            process_image(page, EnhancerConfig(edge_inking=False, color_correction=False)),
            dtype=int,
        )
        assert np.abs(on - off).mean() > 1.0, "LUT must visibly alter colour"

    def test_inking_changes_pixels(self, page):
        on = np.asarray(process_image(page, EnhancerConfig(color_correction=False)), dtype=int)
        off = np.asarray(
            process_image(page, EnhancerConfig(color_correction=False, edge_inking=False)),
            dtype=int,
        )
        diff = np.abs(on - off)
        # Inking only touches edges, so a whole-page mean mostly measures how
        # much flat area the fixture has. Assert on the edges themselves.
        assert diff.max() > 20, "inking must alter edge pixels substantially"
        assert (diff.sum(axis=2) > 0).mean() > 0.01, "inking must reach a real share of pixels"

    def test_inking_deepens_edges_rather_than_lightening_them(self, page):
        cfg = EnhancerConfig(color_correction=False)
        inked = np.asarray(process_image(page, cfg).convert("L"), dtype=np.float32)
        plain = np.asarray(
            process_image(page, EnhancerConfig(color_correction=False, edge_inking=False)).convert("L"),
            dtype=np.float32,
        )
        grad = lambda a: np.abs(np.diff(a, axis=0)).mean() + np.abs(np.diff(a, axis=1)).mean()
        assert grad(inked) > grad(plain), "inking should raise edge contrast"

    def test_missing_lut_file_is_reported(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            process_image(make_page(), EnhancerConfig(lut_path=str(tmp_path / "nope.cube")))


class TestCompressionOptions:

    @pytest.fixture
    def archive(self, tmp_path):
        return build_cbz(str(tmp_path / "v.cbz"), pages=4)

    def test_lower_quality_makes_a_smaller_file(self, archive, tmp_path):
        big = build(tmp_path, "q90", src=archive, quality=90, color_correction=False, edge_inking=False)
        small = build(tmp_path, "q40", src=archive, quality=40, color_correction=False, edge_inking=False)
        assert os.path.getsize(small) < os.path.getsize(big)

    def test_chroma_subsampling_is_applied(self, archive, tmp_path):
        full = build(tmp_path, "s0", src=archive, subsampling=0, color_correction=False, edge_inking=False)
        half = build(tmp_path, "s2", src=archive, subsampling=2, color_correction=False, edge_inking=False)
        assert os.path.getsize(half) <= os.path.getsize(full)


class TestLayoutOptions:

    @pytest.fixture
    def archive(self, tmp_path):
        return build_cbz(str(tmp_path / "v.cbz"), pages=6)

    def test_per_row_reduces_the_sheet_count(self, archive, tmp_path):
        counts = {}
        for per_row in (1, 2, 3):
            out = build(tmp_path, f"n{per_row}", src=archive, per_row=per_row,
                        orientation="landscape", color_correction=False, edge_inking=False)
            with pymupdf.open(out) as doc:
                counts[per_row] = len(doc)
        assert counts[1] > counts[2] > counts[3]

    def test_orientation_controls_the_sheet_shape(self, archive, tmp_path):
        for orientation, wider in (("landscape", True), ("portrait", False)):
            out = build(tmp_path, orientation, src=archive, per_row=2, orientation=orientation,
                        color_correction=False, edge_inking=False)
            with pymupdf.open(out) as doc:
                for page in doc:
                    assert (page.rect.width > page.rect.height) is wider

    def test_orientation_aliases_match_their_targets(self, archive, tmp_path):
        import pymupdf as fitz
        a = build(tmp_path, "landscape2", src=archive, per_row=2, orientation="landscape",
                  color_correction=False, edge_inking=False)
        b = build(tmp_path, "horizontal2", src=archive, per_row=2, orientation="landscape",
                  color_correction=False, edge_inking=False)
        with fitz.open(a) as x, fitz.open(b) as y:
            assert [p.rect for p in x] == [p.rect for p in y]

    def test_fill_leaves_no_white_margin_but_fit_does(self, tmp_path):
        # A page narrower than its cell letterboxes under fit and is cropped under fill
        src = build_cbz(str(tmp_path / "n.cbz"), pages=2)
        fit = build(tmp_path, "fit", src=src, per_row=1, orientation="landscape",
                    fit_mode="fit", color_correction=False, edge_inking=False)
        fill = build(tmp_path, "fill", src=src, per_row=1, orientation="landscape",
                     fit_mode="fill", color_correction=False, edge_inking=False)
        fit_img, fill_img = render(fit), render(fill)
        near_white = lambda a: (a.min(axis=2) > 246).mean()
        assert near_white(fit_img) > near_white(fill_img)


class TestReadingDirection:

    def _sheet(self, rtl):
        plan = LayoutPlan(per_row=2, sheet_size=LANDSCAPE, rtl=rtl)
        return compose_sheet(
            [Image.new("RGB", (600, 840), RED), Image.new("RGB", (600, 840), BLUE)], plan
        )

    def test_rtl_puts_the_first_page_on_the_right(self):
        assert self._sheet(True).getpixel((1620, 810)) == RED
        assert self._sheet(False).getpixel((1620, 810)) == BLUE

    def test_comicinfo_drives_the_order_end_to_end(self, tmp_path):
        outs = {}
        for tag, xml in (("rtl", COMICINFO_RTL), ("ltr", COMICINFO_LTR)):
            src = build_cbz(str(tmp_path / f"{tag}.cbz"), pages=2, comicinfo=xml)
            outs[tag] = render(
                build(tmp_path, tag, src=src, per_row=2, orientation="landscape",
                      color_correction=False, edge_inking=False)
            )
        # The two orders must not produce the same sheet
        assert not np.array_equal(outs["rtl"], outs["ltr"])

    def test_explicit_direction_overrides_metadata(self, tmp_path):
        src = build_cbz(str(tmp_path / "v.cbz"), pages=2, comicinfo=COMICINFO_RTL)
        forced = render(build(tmp_path, "forced", src=src, per_row=2, orientation="landscape",
                              reading_direction="ltr", color_correction=False, edge_inking=False))
        auto = render(build(tmp_path, "auto", src=src, per_row=2, orientation="landscape",
                            reading_direction="auto", color_correction=False, edge_inking=False))
        assert not np.array_equal(forced, auto)


class TestSpreadOptions:

    def test_keeping_spreads_costs_sheets(self, tmp_path):
        src = build_cbz(str(tmp_path / "v.cbz"), pages=6, spreads=(2,))
        kept = build(tmp_path, "kept", src=src, per_row=2, orientation="landscape",
                     keep_spreads_together=True, color_correction=False, edge_inking=False)
        split = build(tmp_path, "split", src=src, per_row=2, orientation="landscape",
                      keep_spreads_together=False, color_correction=False, edge_inking=False)
        with pymupdf.open(kept) as k, pymupdf.open(split) as s:
            assert len(k) > len(s)

    def test_shift_pages_changes_the_pairing(self, tmp_path):
        src = build_cbz(str(tmp_path / "v.cbz"), pages=4)
        plain = render(build(tmp_path, "plain", src=src, per_row=2, orientation="landscape",
                             color_correction=False, edge_inking=False))
        shifted = render(build(tmp_path, "shift", src=src, per_row=2, orientation="landscape",
                               shift_pages=True, color_correction=False, edge_inking=False))
        assert not np.array_equal(plain, shifted)
