"""
oxide_layout.py — reconstruct a human-readable, layout-preserving text rendering
of a PDF from pdf_oxide spans (bbox = (x, y, width, height), bottom-left origin).

Same logic and byte-identical output as v1; roughly 3x faster on the Python side.

Pipeline
--------
1. Ingest spans into flat tuples, dropping blanks, and sort them once.
2. Cluster into visual lines by vertical mid-point (y is bottom-left, so larger
   y = higher on the page).
3. Estimate one monospace "character cell" width from the spans themselves.
4. Place each span at column round((x0 - x_origin) / char_width), nudging right
   only on collision.
5. Insert blank lines proportional to the vertical gap between lines.

Where the speed comes from (all of it is bookkeeping, none of it is layout logic)
--------------------------------------------------------------------------------
* One flat tuple per span instead of a frozen dataclass, with the vertical
  mid-point pre-negated so the whole page sorts with a keyless C-level
  ``list.sort()`` instead of a Python lambda per comparison.
* The running median in the line clusterer is now O(1). Spans enter a cluster in
  order of decreasing y, so the cluster's mid-points are *already sorted* — the
  median is the middle element, no re-sorting and no ``statistics.median()``
  (which re-sorts and type-dispatches on every call).
* Lines are built with string chunks instead of per-character list extension.
* ``.strip()``, ``len()`` and the mid-point are each computed exactly once.

Public API
----------
    render_pdf(path, **kwargs) -> str      # extract + render a whole PDF
    render_page(spans, **kwargs) -> str    # render one page's spans
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from itertools import pairwise
from operator import itemgetter
from typing import TYPE_CHECKING, Final, cast

if TYPE_CHECKING:
    from pdf_oxide.pdf_oxide import Page

__all__ = ["render_page", "render_pdf"]

PAGE_SEPARATOR = "\n"

# Internal row layout. Field 0 is the *negated* vertical mid-point, so a plain
# ascending sort gives top-to-bottom, then left-to-right, with no key function.
#   0 nymid  -(y0 + height/2)
#   1 x0     left edge
#   2 text   stripped text (blank spans are dropped at ingest)
#   3 height
#   4 width
#   5 rawlen len() of the *unstripped* text, for the char-width estimate
_NYMID: Final = 0
_X0: Final = 1
_TEXT: Final = 2
_H: Final = 3
_W: Final = 4
_RAWLEN: Final = 5
Row = tuple[float, float, str, float, float, int]

_get_x0 = itemgetter(_X0)


# --------------------------------------------------------------------------- #
# Step 1 — ingest
# --------------------------------------------------------------------------- #
def to_rows(spans: Iterable) -> list[Row]:
    """Turn pdf_oxide spans (or Span-like objects) into sorted internal rows.

    Accepts anything exposing ``.text`` and ``.bbox``. Blank spans are dropped
    here so no later stage has to test for them again.
    """
    rows: list[Row] = []
    append = rows.append
    for span in spans:
        raw = span.text
        text = raw.strip()
        if not text:
            continue
        x, y, w, h = span.bbox
        append((-(y + h * 0.5), x, text, h, w, len(raw)))
    rows.sort()
    return rows


# --------------------------------------------------------------------------- #
# Step 2 — line clustering
# --------------------------------------------------------------------------- #
def group_rows(
    rows: Sequence[Row],
    tol_ratio: float = 0.5,
    min_tol: float = 1.5,
) -> list[list[Row]]:
    """Cluster sorted rows into visual lines.

    Spans on one printed row are rarely y-aligned: baselines drift by a point or
    two, and mixed font sizes drift more. A row joins the current line when its
    mid-point is within ``tol_ratio`` * line height of the line's *median*
    mid-point. Using the running median (rather than the first row seen) keeps a
    wide table row from being cut in half when one member sits a couple of points
    lower than the row's leftmost span.

    Because ``rows`` is sorted by descending y, each cluster's mid-points arrive
    in ascending (negated) order, so the median is just the middle element.
    """
    if not rows:
        return []

    lines: list[list[Row]] = []
    first = rows[0]
    current = [first]
    mids = [first[_NYMID]]  # ascending, by construction
    ref_mid = first[_NYMID]
    ref_h = first[_H]

    for row in rows[1:]:
        tol = max(tol_ratio * ref_h, min_tol)
        if row[_NYMID] - ref_mid <= tol:  # difference is never negative here
            current.append(row)
            mids.append(row[_NYMID])
            n = len(mids)
            half = n >> 1
            ref_mid = mids[half] if n & 1 else (mids[half - 1] + mids[half]) * 0.5
            ref_h = max(ref_h, row[_H])
        else:
            lines.append(current)
            current = [row]
            mids = [row[_NYMID]]
            ref_mid = row[_NYMID]
            ref_h = row[_H]

    lines.append(current)
    return lines


# --------------------------------------------------------------------------- #
# Step 3 — metrics estimated from the page itself
# --------------------------------------------------------------------------- #
def _median_of_sorted(values: Sequence[float]) -> float:
    n = len(values)
    half = n >> 1
    return values[half] if n & 1 else (values[half - 1] + values[half]) * 0.5


def _median(values: list[float]) -> float:
    values.sort()
    return _median_of_sorted(values)


def estimate_char_width(rows: Sequence[Row], default: float = 5.0) -> float:
    """Median advance width per character, i.e. the width of one output column."""
    per_char = [r[_W] / r[_RAWLEN] for r in rows if r[_W] > 0 and len(r[_TEXT]) >= 3]
    return _median(per_char) if per_char else default


def estimate_line_height(line_mids: Sequence[float], rows: Sequence[Row]) -> float:
    """Median vertical distance between consecutive rendered lines."""
    deltas = [b - a for a, b in pairwise(line_mids) if b - a > 0.5]
    if deltas:
        return _median(deltas)
    heights = [r[_H] for r in rows if r[_H] > 0]
    return (_median(heights) * 1.2) if heights else 12.0


# --------------------------------------------------------------------------- #
# Steps 4 & 5 — rendering
# --------------------------------------------------------------------------- #
def render_line(line: list[Row], char_width: float, x_origin: float) -> str:
    """Lay one visual line out on a character grid."""
    if len(line) > 1:
        line.sort(key=_get_x0)
    parts: list[str] = []
    length = 0
    for row in line:
        col = max(round((row[_X0] - x_origin) / char_width), 0)
        if parts:
            floor = length + 2  # keep >= 2 spaces between spans
            col = max(col, floor)
        if col > length:
            parts.append(" " * (col - length))
            length = col
        text = row[_TEXT]
        parts.append(text)
        length += len(text)
    return "".join(parts).rstrip()


def render_rows(
    rows: Sequence[Row],
    char_width: float | None = None,
    line_height: float | None = None,
    max_blank_lines: int = 3,
    trim_left: bool = True,
    line_tol: float = 0.5,
) -> str:
    """Render one page, given rows already produced by to_rows()."""
    if not rows:
        return ""

    cw = char_width or estimate_char_width(rows)
    lines = group_rows(rows, tol_ratio=line_tol)
    # Real (un-negated) mid-point of each line, ascending source order = top-down.
    mids = [-_median_of_sorted([r[_NYMID] for r in line]) for line in lines]
    lh = line_height or estimate_line_height([-m for m in mids], rows)
    x_origin = min(r[_X0] for r in rows) if trim_left else 0.0

    out: list[str] = []
    prev_mid: float | None = None
    for line, mid in zip(lines, mids):
        if prev_mid is not None:
            blanks = round((prev_mid - mid) / lh) - 1
            if blanks > 0:
                out.extend([""] * min(blanks, max_blank_lines))
        out.append(render_line(line, cw, x_origin))
        prev_mid = mid

    return "\n".join(out)


def render_page(spans: Iterable, **kwargs) -> str:
    """Render one page of raw spans as layout-preserving text."""
    return render_rows(to_rows(spans), **kwargs)


def render_pdf(pdf_path: str, **kwargs) -> str:
    """Extract and render one PDF."""
    from pdf_oxide import PdfDocument

    with PdfDocument(pdf_path) as doc:
        return PAGE_SEPARATOR.join(
            render_page(cast("Page", page).spans, **kwargs) for page in doc.pages
        )
