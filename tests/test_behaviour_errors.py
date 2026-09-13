"""
Behaviour: bad input fails clearly, and never silently produces a wrong PDF.

The distinction these encode: a malformed *optional* extra (metadata, a stray
file) is tolerated, while a genuinely unusable input raises rather than writing
a plausible-looking but wrong document.
"""

import os
import zipfile

import pytest
from PIL import UnidentifiedImageError

from rmpp_enhancer.cli import enhance_document, main
from rmpp_enhancer.extractor import extract_document
from tests.conftest import build_cbz, build_image_dir, fast_config, page_bytes


class TestUnusableInput:

    def test_missing_path_raises_file_not_found(self, workdir):
        with pytest.raises(FileNotFoundError):
            extract_document(os.path.join(workdir, "nope.cbz"))

    def test_unsupported_extension_names_the_format(self, workdir):
        path = os.path.join(workdir, "notes.txt")
        with open(path, "w") as f:
            f.write("hello")
        with pytest.raises(ValueError, match=r"\.txt"):
            extract_document(path)

    def test_corrupt_archive_raises(self, workdir):
        path = os.path.join(workdir, "broken.cbz")
        with open(path, "wb") as f:
            f.write(b"this is not a zip file")
        with pytest.raises(zipfile.BadZipFile):
            extract_document(path)

    def test_corrupt_page_inside_an_archive_is_not_silently_dropped(self, workdir):
        path = os.path.join(workdir, "v.cbz")
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("001.jpg", page_bytes(1))
            zf.writestr("002.jpg", b"\xff\xd8 not really a jpeg")
        # The page is still listed, and processing surfaces the failure
        assert len(extract_document(path).pages) == 2
        with pytest.raises(UnidentifiedImageError):
            enhance_document(path, output_path=os.path.join(workdir, "o.pdf"),
                             config=fast_config(), force=True)


class TestEmptyInput:

    def test_empty_directory_reports_and_writes_nothing(self, workdir):
        empty = os.path.join(workdir, "empty")
        os.makedirs(empty)
        out = os.path.join(workdir, "o.pdf")
        assert enhance_document(empty, output_path=out, config=fast_config()) == ""
        assert not os.path.exists(out)

    def test_archive_with_no_images_writes_nothing(self, workdir):
        path = os.path.join(workdir, "v.cbz")
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("readme.txt", "no pictures here")
        out = os.path.join(workdir, "o.pdf")
        assert enhance_document(path, output_path=out, config=fast_config()) == ""
        assert not os.path.exists(out)


class TestTolerated:
    """Optional extras may be malformed without taking the run down."""

    def test_malformed_comicinfo_is_ignored(self, workdir):
        src = build_cbz(os.path.join(workdir, "v.cbz"), pages=3, comicinfo="<ComicInfo><oops>")
        out = os.path.join(workdir, "o.pdf")
        enhance_document(src, output_path=out, config=fast_config(), force=True)
        assert os.path.getsize(out) > 0

    def test_non_image_members_are_skipped(self, workdir):
        src = build_cbz(os.path.join(workdir, "v.cbz"), pages=2,
                        extra={"notes.txt": "x", "cover.xml": "<a/>"})
        out = os.path.join(workdir, "o.pdf")
        enhance_document(src, output_path=out, config=fast_config(), force=True)
        import pymupdf
        with pymupdf.open(out) as doc:
            assert len(doc) == 2


class TestTemporaryFiles:

    def test_scratch_space_is_released_when_processing_fails(self, workdir, monkeypatch):
        """A failure after the scratch directory exists must still clean it up."""
        import tempfile

        import rmpp_enhancer.cli as cli

        made = []
        real_mkdtemp = tempfile.mkdtemp

        def spy(*a, **k):
            path = real_mkdtemp(*a, **k)
            made.append(path)
            return path

        monkeypatch.setattr(tempfile, "mkdtemp", spy)
        # Fail during page processing, which is after the directory is made
        monkeypatch.setattr(
            cli, "process_sheet", lambda *_: (_ for _ in ()).throw(RuntimeError("boom"))
        )

        src = build_cbz(os.path.join(workdir, "v.cbz"), pages=3)
        with pytest.raises(RuntimeError, match="boom"):
            enhance_document(src, output_path=os.path.join(workdir, "o.pdf"),
                             config=fast_config(), force=True)

        assert made, "the run should have created scratch space"
        for d in made:
            assert not os.path.exists(d), "scratch space must be removed on failure"

    def test_scratch_space_is_released_on_success(self, workdir, monkeypatch):
        import tempfile

        made = []
        real_mkdtemp = tempfile.mkdtemp
        monkeypatch.setattr(
            tempfile, "mkdtemp",
            lambda *a, **k: made.append(real_mkdtemp(*a, **k)) or made[-1],
        )
        src = build_cbz(os.path.join(workdir, "v.cbz"), pages=2)
        enhance_document(src, output_path=os.path.join(workdir, "o.pdf"),
                         config=fast_config(), force=True)
        assert made and not any(os.path.exists(d) for d in made)

    def test_a_corrupt_page_fails_before_any_work_is_done(self, workdir):
        """Sizing reads headers up front, so a bad page is caught early."""
        path = os.path.join(workdir, "v.cbz")
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("001.jpg", page_bytes(1))
            zf.writestr("002.jpg", b"not a jpeg at all")
        out = os.path.join(workdir, "o.pdf")
        with pytest.raises(UnidentifiedImageError):
            enhance_document(path, output_path=out, config=fast_config(), force=True)
        assert not os.path.exists(out), "no partial PDF should be left behind"


class TestCliArguments:

    def _run(self, *argv):
        import sys
        old = sys.argv
        sys.argv = ["rmpp-pdf-enhancer", *argv]
        try:
            main()
        finally:
            sys.argv = old

    def test_quality_out_of_range_exits(self, workdir):
        src = build_cbz(os.path.join(workdir, "v.cbz"), pages=1)
        for bad in ("0", "101", "-5"):
            with pytest.raises(SystemExit):
                self._run(src, "-q", bad)

    def test_zero_workers_exits(self, workdir):
        src = build_cbz(os.path.join(workdir, "v.cbz"), pages=1)
        with pytest.raises(SystemExit):
            self._run(src, "-w", "0")

    def test_no_inputs_exits(self):
        with pytest.raises(SystemExit):
            self._run()

    def test_already_optimized_inputs_are_skipped(self, workdir, capsys):
        src = os.path.join(workdir, "Book_PaperPro_Optimized.pdf")
        build_image_dir(os.path.join(workdir, "x"), pages=1)
        open(src, "wb").write(b"%PDF-1.4\n")
        with pytest.raises(SystemExit):
            self._run(src)
        assert "Skipping already optimized" in capsys.readouterr().out
