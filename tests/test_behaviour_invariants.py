"""
Behaviour: properties that must hold for every output, whatever the options.

These are the guarantees a user relies on without thinking about them: no page
is dropped, nothing exceeds the panel, the density is right, and the same input
twice gives the same bytes.
"""

import hashlib
import itertools
import random

import pymupdf
import pytest

from rmpp_enhancer.cli import build_sheets, enhance_document
from rmpp_enhancer.extractor import extract_document
from rmpp_enhancer.layout import MAX_PER_ROW, choose_layout, pack_rows
from rmpp_enhancer.pipeline import RMPP_DPI, RMPP_LONG_SIDE, RMPP_SHORT_SIDE
from rmpp_enhancer.spreads import group_pages
from tests.conftest import build_cbz, fast_config

# Every layout the CLI can be asked for, as (per_row, orientation, fit_mode)
CONFIGS = [
    (per_row, orientation, fit)
    for per_row, orientation, fit in itertools.product(
        (1, 2, 3, None), ("auto", "portrait", "landscape"), ("fit", "fill")
    )
]


def image_streams(path):
    doc = pymupdf.open(path)
    out = []
    for page in doc:
        for xref, *_ in page.get_images():
            out.append(hashlib.sha256(doc.extract_image(xref)["image"]).hexdigest())
    doc.close()
    return out


@pytest.fixture(scope="module")
def archive(tmp_path_factory):
    d = tmp_path_factory.mktemp("inv")
    return build_cbz(str(d / "v.cbz"), pages=7, spreads=(3,))


class TestOutputInvariants:

    @pytest.mark.parametrize("per_row,orientation,fit", CONFIGS)
    def test_sheets_never_exceed_the_panel(self, archive, tmp_path, per_row, orientation, fit):
        out = str(tmp_path / "o.pdf")
        enhance_document(
            archive, output_path=out, force=True,
            config=fast_config(per_row=per_row, orientation=orientation, fit_mode=fit),
        )
        doc = pymupdf.open(out)
        try:
            for page in doc:
                # Page boxes are in points at 72/inch; convert back to pixels
                w = round(page.rect.width / 72 * RMPP_DPI)
                h = round(page.rect.height / 72 * RMPP_DPI)
                assert max(w, h) <= RMPP_LONG_SIDE + 1, f"{w}x{h} exceeds panel"
                assert min(w, h) <= RMPP_SHORT_SIDE + 1, f"{w}x{h} exceeds panel"
        finally:
            doc.close()

    @pytest.mark.parametrize("per_row,orientation,fit", CONFIGS)
    def test_no_source_page_is_dropped_or_duplicated(self, archive, per_row, orientation, fit):
        doc = extract_document(archive)
        cfg = fast_config(per_row=per_row, orientation=orientation, fit_mode=fit)
        plan = choose_layout(
            [p.size() for p in doc.pages], per_row=per_row,
            orientation=orientation, fit_mode=fit,
        )
        tasks, page_to_sheet = build_sheets(doc, plan, cfg)
        placed = [p.page_number for t in tasks for p in t.pages]
        assert sorted(placed) == list(range(1, len(doc.pages) + 1))
        assert placed == sorted(placed), "pages must stay in reading order"
        assert sorted(page_to_sheet) == list(range(1, len(doc.pages) + 1))

    @pytest.mark.parametrize("per_row,orientation,fit", CONFIGS)
    def test_sheet_count_never_exceeds_page_count(self, archive, per_row, orientation, fit):
        doc = extract_document(archive)
        cfg = fast_config(per_row=per_row, orientation=orientation, fit_mode=fit)
        plan = choose_layout(
            [p.size() for p in doc.pages], per_row=per_row,
            orientation=orientation, fit_mode=fit,
        )
        tasks, _ = build_sheets(doc, plan, cfg)
        assert 0 < len(tasks) <= len(doc.pages)

    def test_density_is_stamped_at_229_dpi(self, archive, tmp_path):
        out = str(tmp_path / "o.pdf")
        enhance_document(archive, output_path=out, force=True, config=fast_config())
        doc = pymupdf.open(out)
        try:
            page = doc[0]
            xref = page.get_images()[0][0]
            info = doc.extract_image(xref)
            px_w = info["width"]
            in_w = page.rect.width / 72
            assert abs(px_w / in_w - RMPP_DPI) < 1.0
        finally:
            doc.close()

    def test_output_is_a_readable_pdf_with_jpeg_streams(self, archive, tmp_path):
        out = str(tmp_path / "o.pdf")
        enhance_document(archive, output_path=out, force=True, config=fast_config())
        doc = pymupdf.open(out)
        try:
            assert len(doc) > 0
            for page in doc:
                images = page.get_images()
                assert len(images) == 1, "one composed image per sheet"
                assert doc.extract_image(images[0][0])["ext"] == "jpeg"
        finally:
            doc.close()


class TestDeterminism:

    def test_same_input_gives_identical_image_streams(self, archive, tmp_path):
        outs = []
        for i in range(2):
            out = str(tmp_path / f"run{i}.pdf")
            enhance_document(
                archive, output_path=out, force=True,
                config=fast_config(per_row=2, orientation="landscape"),
            )
            outs.append(image_streams(out))
        assert outs[0] == outs[1]

    def test_auto_matches_the_equivalent_explicit_layout(self, archive, tmp_path):
        a = str(tmp_path / "auto.pdf")
        b = str(tmp_path / "explicit.pdf")
        enhance_document(archive, output_path=a, force=True,
                         config=fast_config(per_row=None, orientation="landscape"))
        enhance_document(archive, output_path=b, force=True,
                         config=fast_config(per_row=2, orientation="landscape"))
        assert image_streams(a) == image_streams(b)


class TestPackingProperties:
    """Randomised: packing must hold for any page mix, not just the ones I picked."""

    @pytest.mark.parametrize("seed", range(25))
    def test_packing_holds_for_random_documents(self, seed):
        rng = random.Random(seed)
        count = rng.randint(1, 40)
        per_row = rng.randint(1, MAX_PER_ROW)
        sizes = [
            (1200, 840) if rng.random() < 0.15 else (600, 840)
            for _ in range(count)
        ]
        names = [f"{i:03d}.jpg" for i in range(count)]
        groups = group_pages(names, sizes, per_row=per_row, shift=rng.random() < 0.3)
        spans = [g.span for g in groups]
        rows = pack_rows(spans, per_row)

        flat = [i for row in rows for i in row]
        assert flat == list(range(len(groups))), "every group once, in order"
        for row in rows:
            width = sum(spans[i] for i in row)
            # A row may only overflow when a single item is wider than the row
            assert width <= per_row or len(row) == 1

    @pytest.mark.parametrize("seed", range(25))
    def test_a_spread_is_never_split_across_rows(self, seed):
        rng = random.Random(seed)
        count = rng.randint(2, 30)
        per_row = rng.randint(2, MAX_PER_ROW)
        sizes = [(1200, 840) if rng.random() < 0.25 else (600, 840) for _ in range(count)]
        groups = group_pages([f"{i}.jpg" for i in range(count)], sizes, per_row=per_row)
        spans = [g.span for g in groups]
        for row in pack_rows(spans, per_row):
            assert sum(spans[i] for i in row) <= per_row
