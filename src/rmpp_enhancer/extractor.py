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
import threading
import zipfile
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple
from PIL import Image
import pymupdf

from rmpp_enhancer.pipeline import rmpp_fit_scale


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}


def is_image_member(name: str) -> bool:
    """True for archive/directory entries that are real page images.

    Filters out macOS resource-fork sidecars (``__MACOSX/._page.jpg``) and other
    dot-files, which carry image extensions but are not decodable images.
    """
    if name.endswith("/"):
        return False
    parts = name.split("/")
    if "__MACOSX" in parts:
        return False
    basename = parts[-1]
    if basename.startswith("."):
        return False
    return os.path.splitext(basename)[1].lower() in IMAGE_EXTENSIONS


def natural_sort_key(s: str):
    """Sort strings containing numbers in human/natural order (e.g. 1, 2, 10)."""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r"(\d+)", s)]


@dataclass
class PageItem:
    page_number: int                 # 1-indexed overall page number
    chapter_name: Optional[str]      # Optional chapter/section name for PDF bookmarks
    load_image: Callable[[], Image.Image]  # Lazy loader function to conserve memory
    name: str = ""                   # Source filename, for spread-naming heuristics
    # Dimensions without decoding pixels. Layout and spread detection need every
    # page's size up front; decoding a whole volume for that would be wasteful.
    load_size: Optional[Callable[[], Tuple[int, int]]] = None

    def size(self) -> Tuple[int, int]:
        if self.load_size is not None:
            return self.load_size()
        return self.load_image().size


@dataclass
class ExtractedDocument:
    title: str
    pages: List[PageItem]
    chapters: List[Tuple[str, int]]  # (chapter_name, 1-indexed start_page_number)
    source_path: Optional[str] = None  # Archive path, for reading ComicInfo.xml


def _load_image_from_path(path: str) -> Image.Image:
    with Image.open(path) as im:
        return im.copy()


def _size_from_path(path: str) -> Tuple[int, int]:
    """Image dimensions from the header alone -- Pillow does not decode pixels."""
    with Image.open(path) as im:
        return im.size


def _size_from_zip(zip_path: str, member_name: str, probe_bytes: int = 65536) -> Tuple[int, int]:
    """Dimensions of a zipped image, reading only enough bytes for the header."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        with zf.open(member_name) as f:
            head = f.read(probe_bytes)
    try:
        with Image.open(io.BytesIO(head)) as im:
            return im.size
    except Exception:
        # Header past the probe window (rare); fall back to a full read
        with Image.open(io.BytesIO(_read_zip_member(zip_path, member_name))) as im:
            return im.size


def _read_zip_member(zip_path: str, member_name: str) -> bytes:
    with zipfile.ZipFile(zip_path, "r") as zf:
        with zf.open(member_name) as f:
            return f.read()


def _load_image_from_zip(zip_path: str, member_name: str) -> Image.Image:
    with zipfile.ZipFile(zip_path, "r") as zf:
        with zf.open(member_name) as f:
            with Image.open(io.BytesIO(f.read())) as im:
                return im.copy()


_PDF_HANDLES = threading.local()


def _get_pdf(pdf_path: str) -> pymupdf.Document:
    """Returns a per-thread open handle for ``pdf_path``.

    Pages are loaded lazily and concurrently, so without this every page would
    re-parse the whole PDF cross-reference table. Only one document is kept per
    thread (documents are processed one at a time), so file handles stay bounded.
    """
    cached_path = getattr(_PDF_HANDLES, "path", None)
    if cached_path == pdf_path:
        return _PDF_HANDLES.doc

    old = getattr(_PDF_HANDLES, "doc", None)
    if old is not None:
        old.close()
    _PDF_HANDLES.path = None
    _PDF_HANDLES.doc = None

    doc = pymupdf.open(pdf_path)
    _PDF_HANDLES.path = pdf_path
    _PDF_HANDLES.doc = doc
    return doc


def _load_image_from_pdf(pdf_path: str, page_idx: int) -> Image.Image:
    doc = _get_pdf(pdf_path)
    page = doc[page_idx]

    # Check if page is a pure single full-page scan without text or rotation
    imgs = page.get_images()
    if len(imgs) == 1 and page.rotation == 0:
        text = page.get_text().strip()
        if not text:
            img_rects = page.get_image_rects(imgs[0][0])
            if img_rects:
                r = img_rects[0]
                # Covers at least 85% of page area
                if r.width >= 0.85 * page.rect.width and r.height >= 0.85 * page.rect.height:
                    base_img = doc.extract_image(imgs[0][0])
                    if base_img["width"] >= 600 and base_img["height"] >= 600:
                        img_bytes = base_img["image"]
                        with Image.open(io.BytesIO(img_bytes)) as im:
                            return im.copy()

    # For all vector, document, article, textbook, and multi-element PDF pages:
    # Render the complete page (text, fonts, math, figures, vectors) at Option A resolution
    scale = rmpp_fit_scale(page.rect.width, page.rect.height)

    mat = pymupdf.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat, alpha=False)
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
                if is_image_member(f)
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
                            name=fname,
                            load_size=lambda p=full_path: _size_from_path(p),
                        )
                    )
                    page_num += 1

    # Also handle flat files in root directory
    root_files = [
        f for f in sorted(os.listdir(dir_path), key=natural_sort_key)
        if os.path.isfile(os.path.join(dir_path, f)) and is_image_member(f)
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
                    name=fname,
                    load_size=lambda p=full_path: _size_from_path(p),
                )
            )

    return ExtractedDocument(title=title, pages=pages, chapters=chapters, source_path=dir_path)


def extract_from_zip(archive_path: str) -> ExtractedDocument:
    """Extracts images from a .cbz or .zip archive."""
    title = os.path.splitext(os.path.basename(archive_path))[0]
    pages: List[PageItem] = []
    chapters: List[Tuple[str, int]] = []

    with zipfile.ZipFile(archive_path, "r") as zf:
        members = [m for m in zf.namelist() if is_image_member(m)]

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
            current_chapter = None

        pages.append(
            PageItem(
                page_number=page_num,
                chapter_name=ch_name,
                load_image=lambda z=archive_path, m=member: _load_image_from_zip(z, m),
                name=member,
                load_size=lambda z=archive_path, m=member: _size_from_zip(z, m),
            )
        )

    return ExtractedDocument(title=title, pages=pages, chapters=chapters, source_path=archive_path)


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
            ch_title = str(item[1]).strip()
            p_num = int(item[2])
            chapters.append((ch_title, p_num))

    pages: List[PageItem] = []
    for i in range(total_pages):
        page_num = i + 1
        # The rendered size follows from the page box, so it is known already
        rect = doc[i].rect
        scale = rmpp_fit_scale(rect.width, rect.height)
        rendered = (max(1, round(rect.width * scale)), max(1, round(rect.height * scale)))
        pages.append(
            PageItem(
                page_number=page_num,
                chapter_name=None,
                load_image=lambda p=pdf_path, idx=i: _load_image_from_pdf(p, idx),
                name=f"page_{page_num:05d}",
                load_size=lambda s=rendered: s,
            )
        )
    doc.close()

    return ExtractedDocument(title=title, pages=pages, chapters=chapters, source_path=pdf_path)


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
        pages = [
            PageItem(
                page_number=1,
                chapter_name=None,
                load_image=lambda: _load_image_from_path(input_path),
                name=os.path.basename(input_path),
                load_size=lambda: _size_from_path(input_path),
            )
        ]
        return ExtractedDocument(title=title, pages=pages, chapters=[], source_path=input_path)
    else:
        raise ValueError(f"Unsupported file format: {ext} (supported: .cbz, .zip, .pdf, image folders)")
