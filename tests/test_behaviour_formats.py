"""
Behaviour: every documented input format produces a usable PDF.

These go through enhance_document the way the CLI does, rather than poking at
the extractor, so they fail if any stage between reading and writing breaks.
"""

import os
import zipfile

import pymupdf
import pytest

from rmpp_enhancer.cli import enhance_document
from tests.conftest import (
    COMICINFO_RTL,
    build_cbz,
    build_image_dir,
    build_pdf,
    fast_config,
    make_page,
    page_bytes,
)


def run(inp, out_dir, **cfg):
    out = os.path.join(out_dir, "out.pdf")
    result = enhance_document(inp, output_path=out, config=fast_config(**cfg), force=True)
    assert result == out
    assert os.path.getsize(out) > 0
    return pymupdf.open(out)


class TestInputFormats:

    def test_cbz_archive(self, workdir):
        src = build_cbz(os.path.join(workdir, "v.cbz"), pages=6)
        with run(src, workdir) as doc:
            assert len(doc) == 6

    def test_plain_zip_is_treated_like_a_cbz(self, workdir):
        src = build_cbz(os.path.join(workdir, "v.zip"), pages=3)
        with run(src, workdir) as doc:
            assert len(doc) == 3

    def test_flat_image_directory(self, workdir):
        src = build_image_dir(os.path.join(workdir, "scans"), pages=4)
        with run(src, workdir) as doc:
            assert len(doc) == 4

    def test_directory_with_trailing_separator(self, workdir):
        build_image_dir(os.path.join(workdir, "scans"), pages=3)
        with run(os.path.join(workdir, "scans") + os.sep, workdir) as doc:
            assert len(doc) == 3

    def test_single_image_file(self, workdir):
        path = os.path.join(workdir, "one.png")
        make_page("solo").save(path)
        with run(path, workdir) as doc:
            assert len(doc) == 1

    def test_existing_pdf(self, workdir):
        src = build_pdf(os.path.join(workdir, "doc.pdf"), pages=5)
        with run(src, workdir) as doc:
            assert len(doc) == 5

    @pytest.mark.parametrize("fmt,ext", [("PNG", "png"), ("JPEG", "jpg"), ("WEBP", "webp")])
    def test_each_supported_image_encoding(self, workdir, fmt, ext):
        path = os.path.join(workdir, f"archive_{ext}.cbz")
        with zipfile.ZipFile(path, "w") as zf:
            for i in range(2):
                zf.writestr(f"{i:03d}.{ext}", page_bytes(i, fmt=fmt))
        with run(path, workdir) as doc:
            assert len(doc) == 2


class TestChaptersAndBookmarks:

    def test_subfolders_become_bookmarks(self, workdir):
        src = build_image_dir(
            os.path.join(workdir, "book"), chapters={"01 Start": 2, "02 Middle": 3}
        )
        with run(src, workdir) as doc:
            titles = [entry[1] for entry in doc.get_toc()]
            assert titles == ["01 Start", "02 Middle"]
            assert len(doc) == 5

    def test_source_pdf_outline_survives(self, workdir):
        src = build_pdf(
            os.path.join(workdir, "doc.pdf"), pages=6,
            toc=[("Intro", 1), ("Body", 3), ("End", 5)],
        )
        with run(src, workdir) as doc:
            assert [e[1] for e in doc.get_toc()] == ["Intro", "Body", "End"]

    def test_bookmarks_retarget_when_pages_share_a_sheet(self, workdir):
        src = build_pdf(
            os.path.join(workdir, "doc.pdf"), pages=6,
            toc=[("Intro", 1), ("Body", 3), ("End", 5)],
        )
        with run(src, workdir, per_row=2, orientation="landscape") as doc:
            pages = [e[2] for e in doc.get_toc()]
            # Six pages paired two per sheet: sources 1,3,5 land on sheets 1,2,3
            assert pages == [1, 2, 3]
            assert all(1 <= p <= len(doc) for p in pages)

    def test_bookmarks_never_point_outside_the_document(self, workdir):
        src = build_pdf(
            os.path.join(workdir, "doc.pdf"), pages=4,
            toc=[("A", 1), ("B", 4)],
        )
        for per_row in (1, 2, 3):
            with run(src, workdir, per_row=per_row, orientation="landscape") as doc:
                for _, _, page_num in doc.get_toc():
                    assert 1 <= page_num <= len(doc)


class TestArchiveQuirks:

    def test_macos_sidecars_are_not_pages(self, workdir):
        src = build_cbz(
            os.path.join(workdir, "mac.cbz"), pages=3,
            extra={"__MACOSX/._001.jpg": b"\x00\x05\x16\x07", ".DS_Store.jpg": b"junk"},
        )
        with run(src, workdir) as doc:
            assert len(doc) == 3

    def test_comicinfo_is_not_mistaken_for_a_page(self, workdir):
        src = build_cbz(os.path.join(workdir, "v.cbz"), pages=3, comicinfo=COMICINFO_RTL)
        with run(src, workdir) as doc:
            assert len(doc) == 3

    def test_natural_page_order(self, workdir):
        path = os.path.join(workdir, "order.cbz")
        with zipfile.ZipFile(path, "w") as zf:
            for i in (1, 2, 10, 11):     # lexical order would put 10 before 2
                zf.writestr(f"{i}.jpg", page_bytes(i))
        from rmpp_enhancer.extractor import extract_document
        names = [os.path.basename(p.name) for p in extract_document(path).pages]
        assert names == ["1.jpg", "2.jpg", "10.jpg", "11.jpg"]
