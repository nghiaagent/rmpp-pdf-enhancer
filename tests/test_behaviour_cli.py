"""
Behaviour: the command-line workflows a user actually runs.

Driven through main() with real argv, so argument wiring is covered too.
"""

import os
import sys

import pymupdf
import pytest

from rmpp_enhancer.cli import OPTIMIZED_SUFFIX, main
from tests.conftest import build_cbz, build_image_dir

FAST = ["--no-lut", "--no-ink", "-q", "60"]


def run(*argv):
    old = sys.argv
    sys.argv = ["rmpp-pdf-enhancer", *argv]
    try:
        main()
    finally:
        sys.argv = old


class TestOutputNaming:

    def test_default_name_sits_next_to_the_input(self, workdir):
        src = build_cbz(os.path.join(workdir, "Volume01.cbz"), pages=2)
        run(src, *FAST)
        assert os.path.exists(os.path.join(workdir, f"Volume01{OPTIMIZED_SUFFIX}.pdf"))

    def test_directory_input_keeps_its_name(self, workdir):
        build_image_dir(os.path.join(workdir, "scanned_pages"), pages=2)
        run(os.path.join(workdir, "scanned_pages") + os.sep, *FAST)
        assert os.path.exists(
            os.path.join(workdir, f"scanned_pages{OPTIMIZED_SUFFIX}.pdf")
        )

    def test_explicit_output_path_is_honoured(self, workdir):
        src = build_cbz(os.path.join(workdir, "v.cbz"), pages=2)
        target = os.path.join(workdir, "custom name.pdf")
        run(src, "-o", target, *FAST)
        assert os.path.exists(target)


class TestSkipAndForce:

    def test_existing_output_is_not_rebuilt(self, workdir):
        src = build_cbz(os.path.join(workdir, "v.cbz"), pages=2)
        out = os.path.join(workdir, "o.pdf")
        run(src, "-o", out, *FAST)
        first = os.path.getmtime(out)
        run(src, "-o", out, *FAST)
        assert os.path.getmtime(out) == first

    def test_force_rebuilds(self, workdir):
        src = build_cbz(os.path.join(workdir, "v.cbz"), pages=2)
        out = os.path.join(workdir, "o.pdf")
        run(src, "-o", out, *FAST)
        run(src, "-o", out, "-f", *FAST)
        assert os.path.exists(out)

    def test_an_optimized_file_is_not_reprocessed(self, workdir, capsys):
        already = os.path.join(workdir, f"Book{OPTIMIZED_SUFFIX}.pdf")
        open(already, "wb").write(b"%PDF-1.4\n")
        with pytest.raises(SystemExit):
            run(already, *FAST)
        assert "Skipping already optimized" in capsys.readouterr().out


class TestMultipleInputs:

    def test_several_inputs_go_into_one_output_directory(self, workdir):
        a = build_cbz(os.path.join(workdir, "A.cbz"), pages=2)
        b = build_cbz(os.path.join(workdir, "B.cbz"), pages=3)
        out_dir = os.path.join(workdir, "out")
        run(a, b, "-o", out_dir, *FAST)
        produced = sorted(os.listdir(out_dir))
        assert produced == [f"A{OPTIMIZED_SUFFIX}.pdf", f"B{OPTIMIZED_SUFFIX}.pdf"]

    def test_batch_splits_a_folder_into_separate_documents(self, workdir):
        library = os.path.join(workdir, "library")
        os.makedirs(library)
        build_cbz(os.path.join(library, "One.cbz"), pages=2)
        build_cbz(os.path.join(library, "Two.cbz"), pages=2)
        out_dir = os.path.join(workdir, "out")
        run(library, "--batch", "-o", out_dir, *FAST)
        assert len(os.listdir(out_dir)) == 2

    def test_without_batch_a_folder_is_one_document(self, workdir):
        library = os.path.join(workdir, "library")
        build_image_dir(library, chapters={"ch1": 2, "ch2": 2})
        out = os.path.join(workdir, "one.pdf")
        run(library, "-o", out, *FAST)
        with pymupdf.open(out) as doc:
            assert len(doc) == 4
            assert [e[1] for e in doc.get_toc()] == ["ch1", "ch2"]


class TestLayoutFlagsEndToEnd:

    @pytest.mark.parametrize(
        "flags,expected_sheets",
        [
            ([], 6),
            (["--per-row", "2", "--orientation", "horizontal"], 3),
            (["--per-row", "3", "--orientation", "horizontal"], 2),
            (["--per-row", "auto", "--orientation", "vertical"], 6),
        ],
    )
    def test_sheet_count_matches_the_requested_layout(self, workdir, flags, expected_sheets):
        src = build_cbz(os.path.join(workdir, "v.cbz"), pages=6)
        out = os.path.join(workdir, "o.pdf")
        run(src, "-o", out, "-f", *FAST, *flags)
        with pymupdf.open(out) as doc:
            assert len(doc) == expected_sheets

    def test_version_flag_exits_cleanly(self, capsys):
        with pytest.raises(SystemExit) as exc:
            run("--version")
        assert exc.value.code == 0
        assert "rmpp-pdf-enhancer" in capsys.readouterr().out
