"""
Multi-page sheet layout.

Places one or more source pages side by side in a single row on a reMarkable
Paper Pro sheet, so a landscape sheet can carry a two-page manga spread, or a
portrait sheet three tall strips.

Layouts are always a single row. A grid would be ambiguous to optimise: waste is
scale-invariant across grids (1x1, 2x2 and 3x3 all waste identically), so
"minimise waste" cannot choose between them. Restricted to one row, waste has a
unique minimum and `per_row="auto"` is well defined -- it picks the row whose
combined aspect best matches the sheet.
"""

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple
from PIL import Image

from rmpp_enhancer.pipeline import RMPP_LONG_SIDE, RMPP_SHORT_SIDE

PORTRAIT = (RMPP_SHORT_SIDE, RMPP_LONG_SIDE)
LANDSCAPE = (RMPP_LONG_SIDE, RMPP_SHORT_SIDE)

FIT = "fit"
FILL = "fill"

MAX_PER_ROW = 8
WHITE = (255, 255, 255)


@dataclass(frozen=True)
class LayoutPlan:
    """How every sheet in a document is built."""

    per_row: int
    # None means "no fixed sheet": a lone page becomes a page of its own size,
    # which is the original 1-up behaviour and keeps output byte-identical.
    sheet_size: Optional[Tuple[int, int]]
    fit_mode: str = FIT
    rtl: bool = False

    @property
    def composes(self) -> bool:
        return self.sheet_size is not None


def cell_bounds(sheet_width: int, per_row: int) -> List[Tuple[int, int]]:
    """Left/right pixel bounds of each cell, tiling the sheet without gaps."""
    edges = [round(i * sheet_width / per_row) for i in range(per_row + 1)]
    return list(zip(edges[:-1], edges[1:]))


def cell_waste(
    image_size: Tuple[int, int],
    sheet_size: Tuple[int, int],
    per_row: int,
    fit_mode: str = FIT,
) -> float:
    """Fraction lost placing one image in one cell of a ``per_row`` row.

    In ``fit`` mode that is unused sheet area; in ``fill`` mode it is the share
    of the image cropped away. Both are in [0, 1) and lower is better.
    """
    iw, ih = image_size
    cw, ch = sheet_size[0] / per_row, sheet_size[1]
    if fit_mode == FILL:
        scale = max(cw / iw, ch / ih)
        return 1.0 - (cw * ch) / (iw * scale * ih * scale)
    scale = min(cw / iw, ch / ih)
    return 1.0 - (iw * scale * ih * scale) / (cw * ch)


def _median_size(sizes: Sequence[Tuple[int, int]]) -> Tuple[int, int]:
    widths = sorted(s[0] for s in sizes)
    heights = sorted(s[1] for s in sizes)
    mid = len(sizes) // 2
    return widths[mid], heights[mid]


def auto_per_row(
    sizes: Sequence[Tuple[int, int]],
    sheet_size: Tuple[int, int],
    fit_mode: str = FIT,
    max_per_row: int = MAX_PER_ROW,
) -> int:
    """Row width that wastes least for a representative page.

    Equivalent to matching the row's combined aspect to the sheet's: N images of
    aspect r tile a sheet of aspect R best when N ~= R/r. A 1:4 strip on a
    portrait (3:4) sheet gives exactly 3 across, at zero waste.
    """
    if not sizes:
        return 1
    median = _median_size(sizes)
    return min(
        range(1, max_per_row + 1),
        key=lambda n: (cell_waste(median, sheet_size, n, fit_mode), n),
    )


def choose_layout(
    sizes: Sequence[Tuple[int, int]],
    per_row: Optional[int] = 1,
    orientation: str = "auto",
    fit_mode: str = FIT,
    rtl: bool = False,
) -> LayoutPlan:
    """Resolve CLI-level choices into a concrete plan.

    ``per_row=None`` means auto. ``orientation="auto"`` picks whichever sheet
    wastes less; with a single page per row and no other reason to compose, it
    keeps the original behaviour of letting each page set its own page size.
    """
    explicit_orientation = orientation in ("portrait", "landscape")
    if orientation == "portrait":
        candidates = [PORTRAIT]
    elif orientation == "landscape":
        candidates = [LANDSCAPE]
    else:
        candidates = [PORTRAIT, LANDSCAPE]

    if per_row is None:
        best = min(
            ((sheet, auto_per_row(sizes, sheet, fit_mode)) for sheet in candidates),
            key=lambda sn: (
                cell_waste(_median_size(sizes), sn[0], sn[1], fit_mode) if sizes else 0.0,
                -sn[1],
            ),
        )
        sheet_size, resolved = best
    else:
        resolved = max(1, per_row)
        if len(candidates) == 1:
            sheet_size = candidates[0]
        else:
            sheet_size = min(
                candidates,
                key=lambda s: cell_waste(_median_size(sizes), s, resolved, fit_mode)
                if sizes
                else 0.0,
            )

    # One page per row, no forced orientation and no crop: nothing to compose,
    # so pages keep their own size exactly as they always have.
    if resolved == 1 and not explicit_orientation and fit_mode == FIT:
        sheet_size = None

    return LayoutPlan(per_row=resolved, sheet_size=sheet_size, fit_mode=fit_mode, rtl=rtl)


def place_in_cell(
    img: Image.Image,
    cell_size: Tuple[int, int],
    fit_mode: str = FIT,
) -> Image.Image:
    """Scale ``img`` into ``cell_size``, letterboxing it or cropping to fill."""
    cw, ch = cell_size
    iw, ih = img.size
    if fit_mode == FILL:
        scale = max(cw / iw, ch / ih)
        new = img.resize(
            (max(cw, round(iw * scale)), max(ch, round(ih * scale))),
            Image.Resampling.LANCZOS,
        )
        left = (new.width - cw) // 2
        top = (new.height - ch) // 2
        return new.crop((left, top, left + cw, top + ch))

    scale = min(cw / iw, ch / ih)
    new_w = max(1, min(cw, round(iw * scale)))
    new_h = max(1, min(ch, round(ih * scale)))
    scaled = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    if (new_w, new_h) == (cw, ch):
        return scaled
    cell = Image.new("RGB", (cw, ch), WHITE)
    cell.paste(scaled, ((cw - new_w) // 2, (ch - new_h) // 2))
    return cell


def compose_sheet(
    images: Sequence[Image.Image],
    plan: LayoutPlan,
    spans: Optional[Sequence[int]] = None,
) -> Image.Image:
    """Lay ``images`` across one row of a sheet.

    ``spans`` gives each image's width in cells, so a joined two-page spread can
    occupy two adjacent cells and never straddle a sheet boundary. Under
    right-to-left reading the row is filled from the right.
    """
    if not images:
        raise ValueError("compose_sheet requires at least one image")
    if plan.sheet_size is None:
        raise ValueError("compose_sheet requires a plan with a fixed sheet size")

    spans = list(spans) if spans is not None else [1] * len(images)
    if len(spans) != len(images):
        raise ValueError("spans must be the same length as images")
    if sum(spans) > plan.per_row:
        raise ValueError(
            f"row holds {plan.per_row} cells but images span {sum(spans)}"
        )

    sheet = Image.new("RGB", plan.sheet_size, WHITE)
    bounds = cell_bounds(plan.sheet_size[0], plan.per_row)

    order = list(range(len(images)))
    cursor = 0
    if plan.rtl:
        # Right-to-left: the first page takes the rightmost cell, so walk the
        # images backwards while the cursor still advances left to right. A
        # part-filled row leaves its blank cells on the left.
        order.reverse()
        cursor = plan.per_row - sum(spans)

    for idx in order:
        span = spans[idx]
        x0 = bounds[cursor][0]
        x1 = bounds[cursor + span - 1][1]
        cell = place_in_cell(images[idx], (x1 - x0, plan.sheet_size[1]), plan.fit_mode)
        sheet.paste(cell, (x0, 0))
        cursor += span

    return sheet


def pack_rows(spans: Sequence[int], per_row: int) -> List[List[int]]:
    """Group item indices into rows, never splitting a multi-cell item.

    Greedy left-to-right: an item that will not fit in what is left of the row
    starts a new one. An item wider than a whole row gets a row to itself.
    """
    rows: List[List[int]] = []
    current: List[int] = []
    used = 0
    for idx, span in enumerate(spans):
        if current and used + span > per_row:
            rows.append(current)
            current, used = [], 0
        current.append(idx)
        used += span
    if current:
        rows.append(current)
    return rows
