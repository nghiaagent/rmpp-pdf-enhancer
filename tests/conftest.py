"""
Shared builders for behaviour tests.

Every builder makes a small, self-describing input on disk so a test can state
what a user did rather than how the fixture was assembled.
"""

import io
import os
import zipfile

import pymupdf
import pytest
from PIL import Image, ImageDraw

from rmpp_enhancer.pipeline import EnhancerConfig

# Page proportions of a typical manga scan, kept small so the suite stays quick.
PAGE_W, PAGE_H = 600, 840
SPREAD_W, SPREAD_H = 1200, 840


def make_page(label="", size=(PAGE_W, PAGE_H), color=(248, 246, 242)):
    """A page with a border and a label, so composition is visually checkable."""
    img = Image.new("RGB", size, color)
    draw = ImageDraw.Draw(img)
    draw.rectangle([4, 4, size[0] - 5, size[1] - 5], outline=(20, 20, 24), width=4)
    if label:
        draw.text((size[0] // 2 - 10, size[1] // 2), str(label), fill=(20, 20, 24))
    return img


def page_bytes(label="", size=(PAGE_W, PAGE_H), fmt="JPEG"):
    buf = io.BytesIO()
    make_page(label, size).save(buf, fmt, **({"quality": 88} if fmt == "JPEG" else {}))
    return buf.getvalue()


def build_cbz(path, pages=6, spreads=(), comicinfo=None, extra=None):
    """A comic archive. ``spreads`` holds 0-indexed pages to make double-width."""
    with zipfile.ZipFile(path, "w") as zf:
        if comicinfo is not None:
            zf.writestr("ComicInfo.xml", comicinfo)
        for i in range(pages):
            size = (SPREAD_W, SPREAD_H) if i in spreads else (PAGE_W, PAGE_H)
            zf.writestr(f"{i + 1:03d}.jpg", page_bytes(i + 1, size))
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return path


def build_image_dir(root, pages=4, chapters=None):
    """A folder of scans, optionally split into chapter subfolders."""
    os.makedirs(root, exist_ok=True)
    if chapters:
        for chapter, count in chapters.items():
            sub = os.path.join(root, chapter)
            os.makedirs(sub, exist_ok=True)
            for i in range(count):
                make_page(i + 1).save(os.path.join(sub, f"{i + 1:03d}.png"))
    else:
        for i in range(pages):
            make_page(i + 1).save(os.path.join(root, f"{i + 1:03d}.png"))
    return root


def build_pdf(path, pages=4, toc=None, landscape_pages=()):
    """A vector PDF, optionally with an outline."""
    doc = pymupdf.open()
    for i in range(pages):
        size = (842, 595) if i in landscape_pages else (595, 842)
        page = doc.new_page(width=size[0], height=size[1])
        page.insert_text((72, 200), f"Page {i + 1}")
    if toc:
        doc.set_toc([[1, title, num] for title, num in toc])
    doc.save(path)
    doc.close()
    return path


COMICINFO_RTL = (
    '<?xml version="1.0"?><ComicInfo><Manga>YesAndRightToLeft</Manga></ComicInfo>'
)
COMICINFO_LTR = '<?xml version="1.0"?><ComicInfo><Manga>No</Manga></ComicInfo>'


def fast_config(**kwargs):
    """Config with the pixel filters off, for tests about layout not colour."""
    defaults = dict(color_correction=False, edge_inking=False, quality=70)
    defaults.update(kwargs)
    return EnhancerConfig(**defaults)


@pytest.fixture
def workdir(tmp_path):
    return str(tmp_path)
