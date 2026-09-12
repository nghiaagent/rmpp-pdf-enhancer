"""
Input document and archive extractor.

Supports:
- Image directories (flat or multi-chapter subfolders)
- Comic archives (.cbz, .zip)
- Existing PDF files (extracts image streams or renders pages at 229 PPI)
- Single image files
- Natural alphanumeric sorting for page ordering
"""

import io
import os
import re
import zipfile
from dataclasses import dataclass
from typing import Callable, Generator, List, Optional, Tuple
from PIL import Image
import pymupdf


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}


def natural_sort_key(s: str):
    """Sort strings containing numbers in human/natural order (e.g. 1, 2, 10)."""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r"(\d+)", s)]


@dataclass
class PageItem:
    page_number: int                 # 1-indexed overall page number
    chapter_name: Optional[str]      # Optional chapter/section name for PDF bookmarks
    load_image: Callable[[], Image.Image]  # Lazy loader function to conserve memory


@dataclass
class ExtractedDocument:
    title: str
    pages: List[PageItem]
    chapters: List[Tuple[str, int]]  # (chapter_name, 1-indexed start_page_number)


def _load_image_from_path(path: str) -> Image.Image:
    with Image.open(path) as im:
        return im.copy()


def _load_image_from_zip(zip_path: str, member_name: str) -> Image.Image:
    with zipfile.ZipFile(zip_path, "r") as zf:
        with zf.open(member_name) as f:
            with Image.open(io.BytesIO(f.read())) as im:
                return im.copy()


def _load_image_from_pdf(pdf_path: str, page_idx: int) -> Image.Image:
    doc = pymupdf.open(pdf_path)
    page = doc[page_idx]
    imgs = page.get_images()

    if imgs:
        # Extract direct image stream
        xref = imgs[0][0]
        base_img = doc.extract_image(xref)
        img_bytes = base_img["image"]
        doc.close()
        with Image.open(io.BytesIO(img_bytes)) as im:
            return im.copy()
    else:
        # Fallback: render vector / text PDF page at native 229 DPI (matrix = 229 / 72)
        zoom = 229.0 / 72.0
        mat = pymupdf.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        doc.close()
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def extract_from_directory(dir_path: str) -> ExtractedDocument:
    """Extracts images from a directory, grouping subfolders into chapters if present."""
    title = os.path.basename(os.path.normpath(dir_path))
    pages: List[PageItem] = []
    chapters: List[Tuple[str, int]] = []

    # Check if there are subdirectories (chapters)
    subdirs = [d for d in sorted(os.listdir(dir_path), key=natural_sort_key) if os.path.isdir(os.path.join(dir_path, d))]

    if subdirs:
        page_num = 1
        for sdir in subdirs:
            subdir_path = os.path.join(dir_path, sdir)
            files = [
                f for f in sorted(os.listdir(subdir_path), key=natural_sort_key)
                if os.path.splitext(f)[1].lower() in IMAGE_EXTENSIONS
            ]
            if files:
                chapters.append((sdir, page_num))
                for fname in files:
                    full_path = os.path.join(subdir_path, fname)
                    pages.append(
                        PageItem(
                            page_number=page_num,
                            chapter_name=sdir,
                            load_image=lambda p=full_path: _load_image_from_path(p),
                        )
                    )
                    page_num += 1

    # Also handle flat files in root directory
    root_files = [
        f for f in sorted(os.listdir(dir_path), key=natural_sort_key)
        if os.path.isfile(os.path.join(dir_path, f)) and os.path.splitext(f)[1].lower() in IMAGE_EXTENSIONS
    ]
    if root_files:
        start_num = len(pages) + 1
        if subdirs:
            chapters.append((title, start_num))
        for fname in root_files:
            full_path = os.path.join(dir_path, fname)
            pages.append(
                PageItem(
                    page_number=len(pages) + 1,
                    chapter_name=title if subdirs else None,
                    load_image=lambda p=full_path: _load_image_from_path(p),
                )
            )

    return ExtractedDocument(title=title, pages=pages, chapters=chapters)


def extract_from_zip(archive_path: str) -> ExtractedDocument:
    """Extracts images from a .cbz or .zip archive."""
    title = os.path.splitext(os.path.basename(archive_path))[0]
    pages: List[PageItem] = []
    chapters: List[Tuple[str, int]] = []

    with zipfile.ZipFile(archive_path, "r") as zf:
        members = [
            m for m in zf.namelist()
            if not m.endswith("/") and os.path.splitext(m)[1].lower() in IMAGE_EXTENSIONS
        ]

    members.sort(key=natural_sort_key)

    # Detect chapter folders inside zip
    current_chapter = None
    for idx, member in enumerate(members):
        page_num = idx + 1
        parts = member.split("/")
        if len(parts) > 1:
            ch_name = parts[0]
            if ch_name != current_chapter:
                current_chapter = ch_name
                chapters.append((current_chapter, page_num))
        else:
            ch_name = None

        pages.append(
            PageItem(
                page_number=page_num,
                chapter_name=ch_name,
                load_image=lambda z=archive_path, m=member: _load_image_from_zip(z, m),
            )
        )

    return ExtractedDocument(title=title, pages=pages, chapters=chapters)


def extract_from_pdf(pdf_path: str) -> ExtractedDocument:
    """Extracts images and TOC outlines from an existing PDF."""
    title = os.path.splitext(os.path.basename(pdf_path))[0]
    doc = pymupdf.open(pdf_path)
    total_pages = len(doc)

    # Extract existing PDF Table of Contents
    toc = doc.get_toc()  # [[lvl, title, page, ...], ...]
    chapters: List[Tuple[str, int]] = []
    for item in toc:
        if len(item) >= 3:
            ch_title = item[1]
            p_num = int(item[2])
            chapters.append((ch_title, p_num))

    pages: List[PageItem] = []
    for i in range(total_pages):
        page_num = i + 1
        pages.append(
            PageItem(
                page_number=page_num,
                chapter_name=None,
                load_image=lambda p=pdf_path, idx=i: _load_image_from_pdf(p, idx),
            )
        )
    doc.close()

    return ExtractedDocument(title=title, pages=pages, chapters=chapters)


def extract_document(input_path: str) -> ExtractedDocument:
    """Universal loader that detects format and returns ExtractedDocument."""
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input path does not exist: {input_path}")

    if os.path.isdir(input_path):
        return extract_from_directory(input_path)

    ext = os.path.splitext(input_path)[1].lower()
    if ext in (".cbz", ".zip"):
        return extract_from_zip(input_path)
    elif ext == ".pdf":
        return extract_from_pdf(input_path)
    elif ext in IMAGE_EXTENSIONS:
        # Single image
        title = os.path.splitext(os.path.basename(input_path))[0]
        pages = [PageItem(page_number=1, chapter_name=None, load_image=lambda: _load_image_from_path(input_path))]
        return ExtractedDocument(title=title, pages=pages, chapters=[])
    else:
        raise ValueError(f"Unsupported file format: {ext} (supported: .cbz, .zip, .pdf, image folders)")
