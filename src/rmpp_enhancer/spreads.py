"""
Double-page spread and reading-direction detection for comics and manga.

A spread is one artwork drawn across two facing pages. Placed naively it gets
split down the middle of a sheet boundary, which is the failure this module
prevents.

The approach follows what shipping readers actually do, strongest signal first:

1. ``ComicInfo.xml`` -- the ComicRack metadata file carried inside most .cbz
   archives marks spreads with ``DoublePage="true"`` and declares reading order
   with ``<Manga>YesAndRightToLeft</Manga>``. When present this is authoritative
   and no guessing is needed. Kavita, Komga and ComicRack all read it.
2. Aspect ratio -- an image wider than it is tall is a spread already joined
   into one file. This is the whole of Mihon's detector (``isWideImage`` is
   ``outWidth > outHeight``) and of TachiyomiJ2K's (``height < width``).
3. Filename -- ``012-013.jpg`` names both pages it covers.

Notably absent: matching one page's gutter pixels against the next to re-pair a
spread that was split into two files. No mainstream reader does this. Mihon and
TachiyomiJ2K both treat a split spread as two ordinary pages and instead expose
a manual "shift double pages" control, because pairing parity cannot be
recovered reliably. This module does the same -- see ``shift`` in
:func:`group_pages`.
"""

import os
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

# Two page numbers in one name: 012-013, 012_013, p12-13
JOINED_NAME = re.compile(r"(\d+)\s*[-_]\s*(\d+)(?!\d)")

LTR = "ltr"
RTL = "rtl"

# Fallback when nothing declares a direction. Right-to-left is the default
# because the archives this tool is pointed at are overwhelmingly manga, and a
# .cbz that carries no ComicInfo.xml is far more likely to be one than not.
# Anything the archive actually declares still wins over this.
DEFAULT_READING_DIRECTION = RTL


@dataclass(frozen=True)
class PageGroup:
    """Source page indices that must share one row, in reading order."""

    indices: Tuple[int, ...]
    span: int
    reason: str


def read_comicinfo(archive_path: str) -> Optional[ET.Element]:
    """Return the parsed ComicInfo.xml from a .cbz, or None when absent."""
    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            name = next(
                (n for n in zf.namelist() if os.path.basename(n).lower() == "comicinfo.xml"),
                None,
            )
            if name is None:
                return None
            return ET.fromstring(zf.read(name))
    except (zipfile.BadZipFile, ET.ParseError, OSError, KeyError):
        return None


def reading_direction_from_comicinfo(root: Optional[ET.Element]) -> Optional[str]:
    """``"rtl"`` when the archive declares right-to-left manga order."""
    if root is None:
        return None
    node = root.find("Manga")
    if node is None or not node.text:
        return None
    value = node.text.strip().lower()
    if value == "yesandrighttoleft":
        return RTL
    if value in ("yes", "no", "unknown"):
        return LTR
    return None


def double_pages_from_comicinfo(root: Optional[ET.Element]) -> Dict[int, bool]:
    """Map of 0-indexed page number to its declared ``DoublePage`` flag."""
    flags: Dict[int, bool] = {}
    if root is None:
        return flags
    for page in root.iter("Page"):
        image = page.get("Image")
        if image is None:
            continue
        try:
            index = int(image)
        except ValueError:
            continue
        flags[index] = str(page.get("DoublePage", "false")).strip().lower() == "true"
    return flags


def is_wide(size: Tuple[int, int]) -> bool:
    """True when an image is wider than it is tall, i.e. an already-joined spread.

    This is exactly Mihon's ``isWideImage`` and TachiyomiJ2K's ``height < width``.
    """
    width, height = size
    return width > height


def name_marks_joined_spread(name: str) -> bool:
    """True when a filename names two consecutive pages, e.g. ``012-013.jpg``."""
    stem = os.path.splitext(os.path.basename(name))[0]
    return any(
        int(second) == int(first) + 1 for first, second in JOINED_NAME.findall(stem)
    )


def classify_pages(
    names: Sequence[str],
    sizes: Sequence[Tuple[int, int]],
    declared: Optional[Dict[int, bool]] = None,
) -> List[Tuple[bool, str]]:
    """For each page, whether it is a joined spread and which signal said so."""
    declared = declared or {}
    result: List[Tuple[bool, str]] = []
    for index, (name, size) in enumerate(zip(names, sizes)):
        if index in declared:
            result.append((declared[index], "comicinfo"))
        elif is_wide(size):
            result.append((True, "aspect"))
        elif name_marks_joined_spread(name):
            result.append((True, "filename"))
        else:
            result.append((False, "single"))
    return result


def group_pages(
    names: Sequence[str],
    sizes: Sequence[Tuple[int, int]],
    per_row: int,
    declared: Optional[Dict[int, bool]] = None,
    shift: bool = False,
) -> List[PageGroup]:
    """Partition pages into groups that must not be split across sheets.

    A joined spread claims two cells so it is never cut by a row boundary; every
    other page claims one. ``shift`` offsets the pairing by one page, the same
    escape hatch TachiyomiJ2K exposes as "shift double pages", for volumes whose
    spreads land on the wrong parity.
    """
    flags = classify_pages(names, sizes, declared)
    groups: List[PageGroup] = []

    if shift and flags:
        # The first page claims the whole row, so everything after it pairs on
        # the opposite parity. Isolating it as a single cell would change nothing.
        groups.append(PageGroup((0,), per_row, "shift"))
        start = 1
    else:
        start = 0

    for index in range(start, len(flags)):
        joined, reason = flags[index]
        # A spread needs two cells; in a one-per-row layout it gets its own sheet
        span = min(2, per_row) if joined else 1
        groups.append(PageGroup((index,), span, reason))
    return groups


def resolve_reading_direction(requested: str, archive_path: Optional[str]) -> Tuple[str, str]:
    """Resolve ``ltr``/``rtl``/``auto`` into a direction and how it was decided.

    Precedence: an explicit flag, then whatever the archive declares, then
    :data:`DEFAULT_READING_DIRECTION`. A volume that says ``<Manga>No</Manga>``
    is therefore still laid out left-to-right under the default.
    """
    if requested in (LTR, RTL):
        return requested, "requested"
    declared = reading_direction_from_comicinfo(read_comicinfo(archive_path)) if archive_path else None
    if declared:
        return declared, "comicinfo"
    return DEFAULT_READING_DIRECTION, "default"
