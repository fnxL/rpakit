"""
oxide_layout.py — reconstruct a human-readable, layout-preserving text rendering
of a PDF from pdf_oxide spans (bbox = (x, y, width, height), bottom-left origin).

Same logic as v1 for clustering and blank-line handling; roughly 3x faster on
the Python side. Span placement was fixed to stop breaking words apart - see
render_line()'s docstring - stacked multi-line headers are folded onto one
row where they don't collide - see pack_lines()'s docstring - and rotated
text (sidebar captions, diagonal watermark stamps) is dropped entirely,
matching pypdf's layout mode - see split_by_rotation()'s docstring.

Pipeline
--------
0. Drop spans made of rotated characters (needs page.chars; see
   split_by_rotation()) before any of the following steps see them.
1. Ingest spans into flat tuples, dropping blanks, and sort them once.
2. Cluster into visual lines by vertical mid-point (y is bottom-left, so larger
   y = higher on the page).
3. Estimate one monospace "character cell" width from the spans themselves,
   then fold a baseline into the line above it where the two are close enough
   and don't collide (see pack_lines()).
4. Place each span at column round((x0 - x_origin) / char_width), except two
   spans that are genuinely touching in the source (see render_line()).
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
#   1 x0     left edge of the *stripped* text (nudged right past any leading
#             whitespace baked into the span's bbox)
#   2 text   stripped text (blank spans are dropped at ingest)
#   3 height
#   4 width  of the raw (unstripped) span, for the char-width estimate
#   5 rawlen len() of the *unstripped* text, for the char-width estimate
#   6 x1     right edge of the *stripped* text (nudged left past any trailing
#             whitespace baked into the span's bbox)
_NYMID: Final = 0
_X0: Final = 1
_TEXT: Final = 2
_H: Final = 3
_W: Final = 4
_RAWLEN: Final = 5
_X1: Final = 6
Row = tuple[float, float, str, float, float, int, float]

_get_x0 = itemgetter(_X0)

_ROTATION_TOL: Final = 5.0  # degrees of slop around 0/360 still counted as horizontal


# --------------------------------------------------------------------------- #
# Step 0 — set aside rotated text (sidebar captions, diagonal watermark stamps)
# --------------------------------------------------------------------------- #
def _char_rotation_lookup(chars: Iterable) -> dict[tuple[float, float], float]:
    """Map a rounded character origin to that character's rotation.

    Built from ``page.chars`` (pdf_oxide's per-character data), which carries
    a genuine ``rotation_degrees`` — the span-level API doesn't expose
    rotation at all, and a rotated span's own bbox is reported as if it were
    ordinary horizontal text, which is exactly the false signal that lands it
    on the wrong line. A span's bbox origin matches its first character's
    bbox origin, so this lookup lets us classify whole spans by position.
    """
    return {
        (round(c.bbox[0], 1), round(c.bbox[1], 1)): c.rotation_degrees for c in chars
    }


def _is_rotated(span, lookup: dict[tuple[float, float], float]) -> bool:
    rotation = lookup.get((round(span.bbox[0], 1), round(span.bbox[1], 1)))
    if rotation is None:
        return False  # no char data for this position: assume horizontal
    rotation %= 360
    return _ROTATION_TOL < rotation < 360 - _ROTATION_TOL


def split_by_rotation(spans: Iterable, chars: Iterable | None) -> tuple[list, list]:
    """Separate genuinely rotated spans from normally-oriented ones.

    A 90°-rotated sidebar caption ("A" / "STATUS" stacked to read top-to-
    bottom beside a section) or a diagonal "ASSESSED COPY" watermark stamp
    has real page coordinates that happen to fall inside an ordinary
    horizontal row's y-range, but a bbox that (per pdf_oxide) doesn't reflect
    the rotation — so left in the mix, it gets diced into the row's column
    math and corrupts a real field (``STATUS14.STATE OF ORIGIN``,
    ``B DECLARAN5.CB NAME``). There's no square-grid coordinate that
    correctly places rotated text next to horizontal text anyway, so callers
    render only the horizontal spans and discard the rotated ones entirely —
    matching pypdf's own layout mode, which drops rotated text the same way.

    Without ``chars`` (no per-character rotation data available) every span
    is treated as horizontal, matching the old behaviour. The rotated list is
    still returned (rather than just filtering in place) in case a caller
    wants it for something other than discarding.
    """
    if chars is None:
        return list(spans), []
    lookup = _char_rotation_lookup(chars)
    horizontal: list = []
    rotated: list = []
    for span in spans:
        (rotated if _is_rotated(span, lookup) else horizontal).append(span)
    return horizontal, rotated


# --------------------------------------------------------------------------- #
# Step 1 — ingest
# --------------------------------------------------------------------------- #
def to_rows(spans: Iterable) -> list[Row]:
    """Turn pdf_oxide spans (or Span-like objects) into sorted internal rows.

    Accepts anything exposing ``.text`` and ``.bbox``. Blank spans are dropped
    here so no later stage has to test for them again.

    A span's bbox covers its *raw*, unstripped text, so a leading or trailing
    space is baked into the box as extra width the stripped text doesn't
    actually occupy. Left uncorrected, that phantom width makes two spans that
    are genuinely touching (e.g. a word split mid-run by a kerning pair, with
    no space in between) look like they have a real gap between them once
    stripped. We shrink the box down to the stripped text's own span, using
    the run's own average advance width to estimate how much of the box each
    trimmed character accounted for.
    """
    rows: list[Row] = []
    append = rows.append
    for span in spans:
        raw = span.text
        text = raw.strip()
        if not text:
            continue
        x, y, w, h = span.bbox
        rawlen = len(raw)
        lead = rawlen - len(raw.lstrip())
        trail = rawlen - len(raw.rstrip())
        per_char = w / rawlen if rawlen else 0.0
        x0 = x + lead * per_char
        x1 = x + w - trail * per_char
        append((-(y + h * 0.5), x0, text, h, w, rawlen, x1))
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
# Step 3b — pack stacked sub-headers onto one visual row
# --------------------------------------------------------------------------- #
def pack_lines(
    lines: list[list[Row]],
    mids: Sequence[float],
    line_height: float,
) -> tuple[list[list[Row]], list[float], list[float]]:
    """Fold a baseline into the line above it when the two are printed as one row.

    A multi-line column header ("Factory" over "Item No.", "Total" over "CBM")
    puts each stacked label on its own baseline, a few points apart — closer
    together than a real second line of text but still a distinct cluster from
    group_rows(). A baseline joins the line above when both hold: no blank
    line would separate them anyway (they're spaced closer than one line
    height), and none of its spans horizontally overlaps a span already on
    that line. The second condition is what tells a genuinely stacked header
    label ("Item No.", off to the side of "Factory") apart from a second row
    of the *same* header ("CBM" stacked directly under "Total") that must stay
    on its own line — and doubles as the guard against folding an unrelated
    paragraph line into the one above it, since two full-width lines of prose
    almost always overlap end to end.

    Returns the packed line groups alongside two mid-point lists of the same
    length: each group's *entry* mid (its first, topmost baseline — the one to
    compare against the line above when spacing it) and *exit* mid (its last,
    bottommost baseline — the one to compare against the line below).
    """
    if not lines:
        return [], [], []

    groups = [list(lines[0])]
    ranges = [[(r[_X0], r[_X1]) for r in lines[0]]]
    entry_mids = [mids[0]]
    exit_mids = [mids[0]]

    for line, mid in zip(lines[1:], mids[1:]):
        blanks = round((exit_mids[-1] - mid) / line_height) - 1
        row_ranges = [(r[_X0], r[_X1]) for r in line]
        collides = blanks > 0 or any(
            nx0 < ex1 and ex0 < nx1
            for nx0, nx1 in row_ranges
            for ex0, ex1 in ranges[-1]
        )
        if collides:
            groups.append(list(line))
            ranges.append(row_ranges)
            entry_mids.append(mid)
            exit_mids.append(mid)
        else:
            groups[-1].extend(line)
            ranges[-1].extend(row_ranges)
            exit_mids[-1] = mid

    return groups, entry_mids, exit_mids


# --------------------------------------------------------------------------- #
# Steps 4 & 5 — rendering
# --------------------------------------------------------------------------- #
def render_line(line: list[Row], char_width: float, x_origin: float) -> str:
    """Lay one visual line out on a character grid.

    Every span is placed by its absolute position (``x0`` relative to
    ``x_origin``) — that's what keeps label:value pairs and table columns
    aligned across *different* rows, since it plants each span at the column
    its own real coordinates imply rather than one built up from whatever
    happens to precede it on this particular row.

    The one place absolute position misleads is two spans that are genuinely
    touching: a word split mid-run by a kerning pair, with no space in the
    source. A "T" rendered as its own 1-character-wide span is physically
    wider than that (kerning nudges the next span left to compensate), so its
    absolute column and the next span's absolute column can come out a full
    column apart even though nothing separates them. We detect that case from
    the real gap between the two spans' own edges and glue them with no space,
    instead of trusting the column math.

    The other place it misunderstates: a run of narrower- or wider-than-median
    characters earlier on the line (a condensed table font, a run of digits)
    accumulates a rounding drift that isn't there in the real geometry. Two
    spans with a genuinely wide gap between them (two table columns) can end
    up column-adjacent purely because everything placed *before* them on this
    line ran a font-width fraction narrower than ``char_width`` claims. So a
    real, non-touching gap is never trusted to the absolute column alone: it's
    also converted to spaces directly from the two spans' own edges, and
    whichever placement is more generous wins.
    """
    if len(line) > 1:
        line.sort(key=_get_x0)
    parts: list[str] = []
    length = 0
    prev_x1: float | None = None
    for row in line:
        col = max(round((row[_X0] - x_origin) / char_width), 0)
        if parts:
            gap = row[_X0] - cast(float, prev_x1)
            if gap < char_width * 0.5:
                col = length
            else:
                col = max(col, length + max(round(gap / char_width), 1))
        if col > length:
            parts.append(" " * (col - length))
            length = col
        text = row[_TEXT]
        parts.append(text)
        length += len(text)
        prev_x1 = row[_X1]
    return "".join(parts).rstrip()


def render_rows(
    rows: Sequence[Row],
    char_width: float | None = None,
    line_height: float | None = None,
    max_blank_lines: int = 3,
    trim_left: bool = True,
    line_tol: float = 0.5,
    x_origin: float | None = None,
) -> str:
    """Render one page, given rows already produced by to_rows().

    ``char_width``, ``line_height`` and ``x_origin`` are each estimated from
    ``rows`` when not given explicitly. For a single page rendered on its own
    that's the only option, but ``render_pdf`` passes all three in from the
    whole document instead: a repeating header on a form-style PDF sits at
    the exact same coordinates on every page, and estimating these three
    per-page (from whatever that one page happens to contain) can shift that
    header's rendered column by a character or two from one page to the next
    for no reason a reader of the page itself could ever see.
    """
    if not rows:
        return ""

    cw = char_width or estimate_char_width(rows)
    lines = group_rows(rows, tol_ratio=line_tol)
    # Real (un-negated) mid-point of each line, ascending source order = top-down.
    mids = [-_median_of_sorted([r[_NYMID] for r in line]) for line in lines]
    lh = line_height or estimate_line_height([-m for m in mids], rows)
    lines, entry_mids, exit_mids = pack_lines(lines, mids, lh)
    if x_origin is None:
        x_origin = min(r[_X0] for r in rows) if trim_left else 0.0

    out: list[str] = []
    prev_exit_mid: float | None = None
    for line, entry_mid, exit_mid in zip(lines, entry_mids, exit_mids):
        if prev_exit_mid is not None:
            blanks = round((prev_exit_mid - entry_mid) / lh) - 1
            if blanks > 0:
                out.extend([""] * min(blanks, max_blank_lines))
        out.append(render_line(line, cw, x_origin))
        prev_exit_mid = exit_mid

    return "\n".join(out)


def render_page(spans: Iterable, chars: Iterable | None = None, **kwargs) -> str:
    """Render one page of raw spans as layout-preserving text.

    Pass ``chars`` too (``page.chars``) to drop rotated text — sidebar
    captions, diagonal watermark stamps — from the output entirely; see
    split_by_rotation(). Without it, every span is treated as horizontal,
    same as before.
    """
    horizontal, _rotated = split_by_rotation(spans, chars)
    return render_rows(to_rows(horizontal), **kwargs)


def render_pdf(
    pdf_path: str,
    char_width: float | None = None,
    line_height: float | None = None,
    trim_left: bool = True,
    **kwargs,
) -> str:
    """Extract and render one PDF.

    ``char_width``, ``line_height`` and the left margin are estimated once
    from every page's rows combined, then held fixed across all of them —
    see render_rows()'s docstring for why a per-page estimate would make a
    repeating header drift between pages. Rotated text (sidebar captions,
    diagonal watermark stamps) is dropped per page — see
    split_by_rotation().
    """
    from pdf_oxide import PdfDocument

    # `PdfDocument.__exit__` is typed to return `bool`, so a checker can't
    # rule out it suppressing an exception raised inside the block below —
    # in that case control falls through to `return result` having never
    # hit either return further down, hence the eager default here.
    result = ""
    with PdfDocument(pdf_path) as doc:
        pages = list(doc.pages)
        pages_rows = [
            to_rows(
                split_by_rotation(cast("Page", page).spans, cast("Page", page).chars)[0]
            )
            for page in pages
        ]
        all_rows = [row for rows in pages_rows for row in rows]
        if not all_rows:
            result = PAGE_SEPARATOR.join("" for _ in pages_rows)
        else:
            cw = char_width or estimate_char_width(all_rows)
            x_origin = min(r[_X0] for r in all_rows) if trim_left else 0.0
            if line_height is None:
                all_lines = group_rows(all_rows, tol_ratio=kwargs.get("line_tol", 0.5))
                all_mids = [
                    -_median_of_sorted([r[_NYMID] for r in line]) for line in all_lines
                ]
                line_height = estimate_line_height([-m for m in all_mids], all_rows)

            result = PAGE_SEPARATOR.join(
                render_rows(
                    rows,
                    char_width=cw,
                    line_height=line_height,
                    x_origin=x_origin,
                    **kwargs,
                )
                for rows in pages_rows
            )

    return result
