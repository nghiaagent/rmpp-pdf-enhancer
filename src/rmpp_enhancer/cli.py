"""
Command-line interface for rmpp-pdf-enhancer.
"""

import argparse
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List, Tuple

from rmpp_enhancer import __version__
from rmpp_enhancer.extractor import extract_document
from rmpp_enhancer.pdf_builder import compile_pdf
from rmpp_enhancer.pipeline import (
    EnhancerConfig,
    load_3d_lut,
    process_image,
    save_page_jpeg,
)


def process_single_page(args: Tuple[int, any, str, EnhancerConfig]) -> str:
    page_idx, page_item, work_dir, config = args
    img = page_item.load_image()
    processed_img = process_image(img, config)

    dst_name = f"page_{page_idx:05d}.jpg"
    dst_path = os.path.join(work_dir, dst_name)
    save_page_jpeg(processed_img, dst_path, config)
    return dst_path


def enhance_document(
    input_path: str,
    output_path: str = None,
    config: EnhancerConfig = None,
    workers: int = 8,
    force: bool = False,
) -> str:
    """Enhances a single document/archive into an RMPP-optimized PDF."""
    config = config or EnhancerConfig()
    start_time = time.time()

    if not output_path:
        stem = os.path.splitext(os.path.basename(input_path))[0]
        if os.path.isdir(input_path):
            parent_dir = os.path.dirname(os.path.abspath(input_path))
        else:
            parent_dir = os.path.dirname(input_path) or "."
        output_path = os.path.join(parent_dir, f"{stem}_PaperPro_Optimized.pdf")

    if os.path.exists(output_path) and not force:
        print(f"\n⏭️  Skipping: {os.path.basename(input_path)}")
        print(f"   Output '{os.path.basename(output_path)}' already exists. Use --force to re-process.")
        return output_path

    print(f"\n=======================================================")
    print(f"📖 Reading: {os.path.basename(input_path)}")
    print(f"=======================================================")

    doc = extract_document(input_path)
    total_input_pages = len(doc.pages)
    print(f"Detected: {total_input_pages} pages | Chapters: {len(doc.chapters)}")

    if total_input_pages == 0:
        print("Warning: No pages found to process.")
        return ""

    # Preload LUT into memory before spawning threads
    if config.color_correction:
        load_3d_lut(config.lut_path)

    work_dir = f"/tmp/rmpp_proc_{int(time.time() * 1000)}"
    os.makedirs(work_dir, exist_ok=True)

    print(f"⚡ Processing {total_input_pages} pages with {workers} workers...")
    print(f"   Settings: Quality Q{config.quality}, Subsampling={'4:4:4' if config.subsampling == 0 else '4:2:0'}")
    print(f"   LUT Correction: {'ON' if config.color_correction else 'OFF'} | Edge Inking: {'ON' if config.edge_inking else 'OFF'}")

    tasks = [(i, page_item, work_dir, config) for i, page_item in enumerate(doc.pages)]

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        all_jpegs = list(executor.map(process_single_page, tasks))

    proc_duration = time.time() - t0
    print(f"✓ Processed {len(all_jpegs)} output pages in {proc_duration:.2f}s ({proc_duration / len(all_jpegs):.3f}s/page)")

    print(f"📦 Assembling PDF: {os.path.basename(output_path)}...")
    t_pdf = time.time()
    final_pdf = compile_pdf(all_jpegs, output_path, chapters=doc.chapters)
    pdf_duration = time.time() - t_pdf

    # Clean up intermediate images
    shutil.rmtree(work_dir, ignore_errors=True)

    file_size_mb = os.path.getsize(final_pdf) / (1024 * 1024)
    total_duration = time.time() - start_time
    print(f"🎉 Generated {os.path.basename(final_pdf)} ({file_size_mb:.2f} MB) in {total_duration:.2f}s")
    print(f"   Full Path: {final_pdf}")

    return final_pdf


def main():
    parser = argparse.ArgumentParser(
        prog="rmpp-pdf-enhancer",
        description="reMarkable Paper Pro Canvas Color universal PDF, document, textbook and manga enhancer",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("inputs", nargs="+", help="Input file(s): .pdf, .cbz, .zip, or directory of images/scans")
    parser.add_argument("-o", "--output", help="Output PDF file path (or destination directory if multiple inputs)")
    parser.add_argument("-q", "--quality", type=int, default=82, help="JPEG quality (1-100), tuned to 82 for fast cloud sync")
    parser.add_argument("--subsampling", type=int, choices=[0, 2], default=0, help="Chroma subsampling: 0=4:4:4 (crisp text), 2=4:2:0 (smaller file)")
    parser.add_argument("-w", "--workers", type=int, default=min(8, os.cpu_count() or 4), help="Number of concurrent worker threads")
    parser.add_argument("-f", "--force", action="store_true", help="Force overwrite if output file already exists, and re-process already optimized files")
    parser.add_argument("--no-lut", action="store_true", help="Disable 3D LUT Canvas Color compensation")
    parser.add_argument("--no-ink", action="store_true", help="Disable bilateral edge-directed inking filter")
    parser.add_argument("--lut-file", help="Custom .cube 3D LUT profile path")
    parser.add_argument("--batch", action="store_true", help="Treat directory contents as separate sub-documents/chapters")
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")

    args = parser.parse_args()

    config = EnhancerConfig(
        quality=args.quality,
        subsampling=args.subsampling,
        color_correction=not args.no_lut,
        edge_inking=not args.no_ink,
        lut_path=args.lut_file,
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
        basename = os.path.basename(t.rstrip("/\\"))
        if not args.force and "_PaperPro_Optimized" in basename:
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
                os.makedirs(args.output, exist_ok=True)
                stem = os.path.splitext(os.path.basename(target))[0]
                out_target = os.path.join(args.output, f"{stem}_PaperPro_Optimized.pdf")
            else:
                out_target = args.output

        enhance_document(target, output_path=out_target, config=config, workers=args.workers, force=args.force)


if __name__ == "__main__":
    main()
