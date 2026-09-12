"""
PDF compilation and Table of Contents (TOC) bookmark builder.

Uses img2pdf for lossless, direct JPEG stream injection, and PyMuPDF to inject
clean native PDF navigation outlines/bookmarks for reMarkable Paper Pro.
"""

import os
from typing import List, Tuple
import img2pdf
import pymupdf


def compile_pdf(
    jpeg_paths: List[str],
    output_pdf_path: str,
    chapters: List[Tuple[str, int]] = None,
) -> str:
    """
    Compiles a sequence of JPEG files into a single PDF without re-encoding,
    and applies Table of Contents (TOC) bookmarks if provided.

    Args:
        jpeg_paths: List of file paths to optimized JPEGs.
        output_pdf_path: Destination path for the generated PDF.
        chapters: Optional list of (chapter_title, 1-indexed start_page).

    Returns:
        The output PDF file path.
    """
    if not jpeg_paths:
        raise ValueError("No images provided to compile_pdf")

    os.makedirs(os.path.dirname(os.path.abspath(output_pdf_path)), exist_ok=True)

    # 1. Lossless injection via img2pdf (preserves 229 DPI & 4:4:4 chroma directly)
    pdf_bytes = img2pdf.convert(jpeg_paths)
    with open(output_pdf_path, "wb") as f:
        f.write(pdf_bytes)

    # 2. Inject Table of Contents / Outline Bookmarks if present
    if chapters:
        try:
            doc = pymupdf.open(output_pdf_path)
            total_pages = len(doc)

            toc = []
            for title, page_num in chapters:
                # Ensure page number is clamped within document boundaries
                clamped_page = max(1, min(page_num, total_pages))
                toc.append([1, title, clamped_page])

            doc.set_toc(toc)
            # Save outline updates into file
            temp_toc_pdf = output_pdf_path + ".tmp"
            doc.save(temp_toc_pdf, garbage=3, deflate=True)
            doc.close()
            os.replace(temp_toc_pdf, output_pdf_path)
        except Exception as e:
            # Fall back gracefully to base PDF without failing compilation
            print(f"Warning: Failed to inject PDF bookmarks: {e}")

    return output_pdf_path
