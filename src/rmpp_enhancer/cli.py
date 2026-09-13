"""
Command-line interface for rmpp-pdf-enhancer.
"""

import argparse
import os
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from rmpp_enhancer import __version__
from rmpp_enhancer.extractor import PageItem, extract_document
from rmpp_enhancer.layout import (
    MAX_PER_ROW,
    LayoutPlan,
    choose_layout,
    compose_sheet,
    pack_rows,
)
from rmpp_enhancer.pdf_builder import compile_pdf
from rmpp_enhancer.pipeline import (
    EnhancerConfig,
    apply_corrections,
    load_3d_lut,
    prepare_rgb,
    save_page_jpeg,
    scale_to_rmpp_geometry,
)
from rmpp_enhancer.spreads import group_pages, read_comicinfo, double_pages_from_comicinfo, resolve_reading_direction


DEFAULT_WORKERS = min(8, os.cpu_count() or 4)
OPTIMIZED_SUFFIX = "_PaperPro_Optimized"


def optimized_output_path(input_path: str, dest_dir: Optional[str] = None) -> str:
    """Default output path for an input: ``<stem>_PaperPro_Optimized.pdf``.

    The path is normalized first, so a directory named with a trailing separator
    -- which is what shell tab-completion produces -- keeps its name instead of
    collapsing to an empty stem.
    """
    normalized = os.path.normpath(input_path)
    parent = dest_dir if dest_dir is not None else os.path.dirname(os.path.abspath(normalized))
    stem = os.path.splitext(os.path.basename(normalized))[0]
    return os.path.join(parent, f"{stem}{OPTIMIZED_SUFFIX}.pdf")


@dataclass(frozen=True)
class SheetTask:
    """One output page: the source pages on it and how many cells each claims."""

    index: int
    pages: Tuple[PageItem, ...]
    spans: Tuple[int, ...]


def process_sheet(args: Tuple[SheetTask, str, LayoutPlan, EnhancerConfig]) -> str:
    task, work_dir, plan, config = args
    images = [prepare_rgb(page.load_image()) for page in task.pages]

    if plan.composes:
        sheet = compose_sheet(images, plan, task.spans)
    else:
        sheet = scale_to_rmpp_geometry(images[0], config)

    dst_path = os.path.join(work_dir, f"page_{task.index:05d}.jpg")
    save_page_jpeg(apply_corrections(sheet, config), dst_path, config)
    return dst_path


def build_sheets(doc, plan: LayoutPlan, config: EnhancerConfig) -> Tuple[List[SheetTask], Dict[int, int]]:
    """Group source pages into sheets and map each source page to its sheet.

    The returned mapping is what keeps the table of contents honest: when two
    pages share a sheet, every bookmark past that point would otherwise point at
    the wrong page.
    """
    archive = doc.source_path if getattr(doc, "source_path", None) else None
    declared = double_pages_from_comicinfo(read_comicinfo(archive)) if archive else {}

    sizes = [page.size() for page in doc.pages]
    if plan.per_row > 1 and config.keep_spreads_together:
        groups = group_pages(
            [page.name for page in doc.pages],
            sizes,
            per_row=plan.per_row,
            declared=declared,
            shift=config.shift_pages,
        )
    else:
        groups = group_pages(
            [page.name for page in doc.pages], sizes, per_row=1, declared={}, shift=False
        )

    rows = pack_rows([g.span for g in groups], plan.per_row)

    tasks: List[SheetTask] = []
    page_to_sheet: Dict[int, int] = {}
    for sheet_index, row in enumerate(rows):
        members: List[PageItem] = []
        spans: List[int] = []
        for group_idx in row:
            group = groups[group_idx]
            for page_index in group.indices:
                members.append(doc.pages[page_index])
                spans.append(group.span)
                page_to_sheet[page_index + 1] = sheet_index + 1
        tasks.append(SheetTask(sheet_index, tuple(members), tuple(spans)))

    return tasks, page_to_sheet


def remap_chapters(
    chapters: List[Tuple[str, int]], page_to_sheet: Dict[int, int]
) -> List[Tuple[str, int]]:
    """Retarget bookmarks from source page numbers to output sheet numbers.

    Without this every bookmark past the first multi-page sheet points at the
    wrong place, because N source pages collapse into one output page.
    """
    remapped = []
    for title, page_num in chapters:
        remapped.append((title, page_to_sheet.get(page_num, page_num)))
    return remapped


def enhance_document(
    input_path: str,
    output_path: Optional[str] = None,
    config: Optional[EnhancerConfig] = None,
    workers: int = DEFAULT_WORKERS,
    force: bool = False,
) -> str:
    """Enhances a single document/archive into an RMPP-optimized PDF."""
    config = config or EnhancerConfig()
    start_time = time.time()

    output_path = output_path or optimized_output_path(input_path)

    if os.path.exists(output_path) and not force:
        print(f"\n⏭️  Skipping: {os.path.basename(input_path)}")
        print(f"   Output '{os.path.basename(output_path)}' already exists. Use --force to re-process.")
        return output_path

    print("\n=======================================================")
    print(f"📖 Reading: {os.path.basename(input_path)}")
    print("=======================================================")

    doc = extract_document(input_path)
    total_input_pages = len(doc.pages)
    print(f"Detected: {total_input_pages} pages | Chapters: {len(doc.chapters)}")

    if total_input_pages == 0:
        print("Warning: No pages found to process.")
        return ""

    direction, direction_source = resolve_reading_direction(
        config.reading_direction, doc.source_path
    )
    sizes = [page.size() for page in doc.pages]
    plan = choose_layout(
        sizes,
        per_row=config.per_row,
        orientation=config.orientation,
        fit_mode=config.fit_mode,
        rtl=(direction == "rtl"),
    )
    tasks, page_to_sheet = build_sheets(doc, plan, config)

    # Preload LUT into memory before spawning threads
    if config.color_correction:
        load_3d_lut(config.lut_path)

    work_dir = tempfile.mkdtemp(prefix="rmpp_proc_")

    sheet_desc = "native page size" if plan.sheet_size is None else f"{plan.sheet_size[0]}x{plan.sheet_size[1]}"
    print(f"⚡ Processing {total_input_pages} pages into {len(tasks)} sheets with {workers} workers...")
    print(f"   Layout: {plan.per_row} per row on {sheet_desc} | Mode: {plan.fit_mode}"
          f" | Reading: {direction} ({direction_source})")
    print(f"   Settings: Quality Q{config.quality}, Subsampling={'4:4:4' if config.subsampling == 0 else '4:2:0'}")
    print(f"   LUT Correction: {'ON' if config.color_correction else 'OFF'} | Edge Inking: {'ON' if config.edge_inking else 'OFF'}")

    work = [(task, work_dir, plan, config) for task in tasks]

    try:
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=workers) as executor:
            all_jpegs = list(executor.map(process_sheet, work))

        proc_duration = time.time() - t0
        print(f"✓ Processed {len(all_jpegs)} output pages in {proc_duration:.2f}s ({proc_duration / len(all_jpegs):.3f}s/page)")

        print(f"📦 Assembling PDF: {os.path.basename(output_path)}...")
        final_pdf = compile_pdf(all_jpegs, output_path, chapters=remap_chapters(doc.chapters, page_to_sheet))
    finally:
        # Always clear the intermediate JPEGs, including on failure
        shutil.rmtree(work_dir, ignore_errors=True)

    file_size_mb = os.path.getsize(final_pdf) / (1024 * 1024)
    total_duration = time.time() - start_time
    print(f"🎉 Generated {os.path.basename(final_pdf)} ({file_size_mb:.2f} MB) in {total_duration:.2f}s")
    print(f"   Full Path: {final_pdf}")

    return final_pdf


def main():
    parser = argparse.ArgumentParser(
        prog="rmpp-pdf-enhancer",
        description="reMarkable Paper Pro PDF enhancer",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("inputs", nargs="+", help="Input file(s): .pdf, .cbz, .zip, or directory of images/scans")
    parser.add_argument("-o", "--output", help="Output PDF file path (or destination directory if multiple inputs)")
    parser.add_argument("-q", "--quality", type=int, default=82, help="JPEG quality (1-100, default %(default)s)")
    parser.add_argument("--subsampling", type=int, choices=[0, 2], default=0, help="Chroma subsampling: 0=4:4:4 (crisp text), 2=4:2:0 (smaller file)")
    parser.add_argument("-w", "--workers", type=int, default=DEFAULT_WORKERS, help="Number of concurrent worker threads")
    parser.add_argument("-f", "--force", action="store_true", help="Force overwrite if output file already exists, and re-process already optimized files")
    parser.add_argument("--no-lut", action="store_true", help="Disable included LUT compensation")
    parser.add_argument("--no-ink", action="store_true", help="Disable bilateral edge-directed inking filter")
    parser.add_argument("--lut-file", help="Custom .cube 3D LUT profile path")
    layout = parser.add_argument_group("sheet layout")
    layout.add_argument(
        "--per-row", default="1", metavar="N|auto",
        help="Source pages side by side on each output sheet, or 'auto' to pick "
             "the row width that wastes least",
    )
    layout.add_argument(
        "--orientation", choices=["portrait", "landscape", "vertical", "horizontal", "auto"],
        default="auto",
        help="Output sheet orientation ('vertical'/'horizontal' are accepted as "
             "aliases for portrait/landscape)",
    )
    layout.add_argument(
        "--fit", choices=["fit", "fill"], default="fit",
        help="fit letterboxes the whole page; fill crops it to cover the cell",
    )
    layout.add_argument(
        "--reading-direction", choices=["ltr", "rtl", "auto"], default="auto",
        help="Page order within a row; auto reads ComicInfo.xml and falls back to rtl",
    )
    layout.add_argument(
        "--no-keep-spreads", dest="keep_spreads", action="store_false",
        help="Allow double-page spreads to be split across sheets",
    )
    layout.add_argument(
        "--shift-pages", action="store_true",
        help="Offset pairing by one page, for volumes whose spreads land on the wrong parity",
    )
    parser.set_defaults(keep_spreads=True)

    parser.add_argument("--batch", action="store_true", help="Treat directory contents as separate sub-documents/chapters")
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")

    args = parser.parse_args()

    if not 1 <= args.quality <= 100:
        parser.error("--quality must be between 1 and 100")
    if args.workers < 1:
        parser.error("--workers must be at least 1")

    if args.per_row == "auto":
        per_row = None
    else:
        try:
            per_row = int(args.per_row)
        except ValueError:
            parser.error("--per-row must be a positive integer or 'auto'")
        if not 1 <= per_row <= MAX_PER_ROW:
            parser.error(f"--per-row must be between 1 and {MAX_PER_ROW}, or 'auto'")

    orientation = {"vertical": "portrait", "horizontal": "landscape"}.get(
        args.orientation, args.orientation
    )

    config = EnhancerConfig(
        quality=args.quality,
        subsampling=args.subsampling,
        color_correction=not args.no_lut,
        edge_inking=not args.no_ink,
        lut_path=args.lut_file,
        per_row=per_row,
        orientation=orientation,
        fit_mode=args.fit,
        keep_spreads_together=args.keep_spreads,
        reading_direction=args.reading_direction,
        shift_pages=args.shift_pages,
    )

    raw_targets = []
    for inp in args.inputs:
        if args.batch and os.path.isdir(inp):
            # Batch mode: find subdirectories and archive files
            for entry in sorted(os.listdir(inp)):
                full = os.path.join(inp, entry)
                if os.path.isdir(full) or os.path.splitext(entry)[1].lower() in (".cbz", ".zip", ".pdf"):
                    raw_targets.append(full)
        else:
            raw_targets.append(inp)

    targets = []
    for t in raw_targets:
        basename = os.path.basename(os.path.normpath(t))
        if not args.force and OPTIMIZED_SUFFIX in basename:
            print(f"⏭️  Skipping already optimized file: {basename}")
            continue
        targets.append(t)

    if not targets:
        print("No valid input files found to process.")
        sys.exit(0)

    print(f"rmpp-pdf-enhancer v{__version__} - reMarkable Paper Pro Universal Optimizer")
    print(f"Total targets to process: {len(targets)}")

    for target in targets:
        out_target = None
        if args.output:
            if os.path.isdir(args.output) or len(targets) > 1:
                # --output names a destination directory for this many outputs
                os.makedirs(args.output, exist_ok=True)
                out_target = optimized_output_path(target, dest_dir=args.output)
            else:
                out_target = args.output

        enhance_document(target, output_path=out_target, config=config, workers=args.workers, force=args.force)


if __name__ == "__main__":
    main()
