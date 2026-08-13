from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import nullcontext
from dataclasses import dataclass
from io import BufferedReader, BytesIO

from python_calamine import CalamineSheet, CalamineWorkbook

from rpakit.string import normalize_text
from rpakit.types import FileSource

# Additive bonus applied to whichever row(s) win the one-shot boost signal
# (`expected_headers` or `column_aliases` matching). Base scores from
# `_score_row` are a weighted sum of ratios in [0, 1], so anything comfortably
# above 1.0 guarantees the boosted row wins outright, while still scaling
# with match count so ties among boosted rows fall back to the stronger
# match. This is deliberately not a `HeaderWeights` field: it overrides the
# base heuristic rather than blending with it, so it doesn't belong in an
# abstraction built for independent, additive signals.
_BOOST_SCALE = 1000.0


@dataclass(frozen=True, slots=True)
class HeaderWeights:
    """Relative importance of each header-likeness signal used by `_score_row`.

    The row in the scanned range with the highest weighted sum of signals is
    assumed to be the header. Fields are independent knobs, so adding a new
    signal only means adding a field here and a term in `_score_row` - no
    positional weight vector to keep in sync.
    """

    density: float = 0.30
    """Share of columns that are non-empty."""
    uniqueness: float = 0.25
    """Share of non-empty cells with distinct values."""
    string_ratio: float = 0.20
    """Share of non-empty cells that are strings."""
    data_contrast: float = 0.15
    """How much more text-like this row is than the row below it (header -> data)."""
    density_jump: float = 0.10
    """How much denser this row is than the row above it (title/blank -> header)."""


DEFAULT_WEIGHTS = HeaderWeights()


@dataclass(frozen=True, slots=True)
class _RowStats:
    """Precomputed, reusable signals for a single row."""

    column_span: int
    non_empty_ratio: float
    unique_ratio: float
    string_ratio: float


def _row_stats(row: Sequence[object], n_cols: int) -> _RowStats:
    non_empty = [v for v in row if not _is_empty(v)]
    if not non_empty:
        return _RowStats(
            column_span=len(row),
            non_empty_ratio=0.0,
            unique_ratio=0.0,
            string_ratio=0.0,
        )

    return _RowStats(
        column_span=len(row),
        non_empty_ratio=len(non_empty) / n_cols,
        unique_ratio=len(set(non_empty)) / len(non_empty),
        string_ratio=sum(1 for v in non_empty if isinstance(v, str)) / len(non_empty),
    )


def _resolve_sheet(
    workbook: CalamineWorkbook,
    *,
    sheet_id: int | None,
    sheet_name: str | None,
) -> CalamineSheet:
    if sheet_name is not None:
        return workbook.get_sheet_by_name(sheet_name)
    if sheet_id is not None:
        return workbook.get_sheet_by_index(sheet_id - 1)
    return workbook.get_sheet_by_index(0)


def _is_empty(value: object) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _cells_equal(a: object, b: object) -> bool:
    """True if two cell values represent the same content.

    Strings compare after normalization (case/punctuation-insensitive);
    everything else compares by raw equality so distinct numbers, dates,
    etc. are never mistaken for a match just because neither is text.
    """
    if isinstance(a, str) and isinstance(b, str):
        return normalize_text(a) == normalize_text(b)
    return a == b


def _is_repeat_of_next(row: Sequence[object], next_row: Sequence[object]) -> bool:
    """True if `row` agrees with `next_row` at every position where both are populated.

    Vertically-merged header cells are commonly unmerged by spreadsheet
    readers into identical values repeated down every row of the merge. Such
    a row is a partial or full repeat of the row below it - real content on
    its own, but never the row that should be preferred over the one
    actually touching the data.
    """
    overlapped = False
    for a, b in zip(row, next_row):
        if _is_empty(a) or _is_empty(b):
            continue
        if not _cells_equal(a, b):
            return False
        overlapped = True
    return overlapped


def _demote_duplicate_header_rows(
    rows: Sequence[Sequence[object]], scores: Sequence[float]
) -> list[float]:
    """Zero out a row's score when it's a repeat of a row below that also qualifies.

    Among a run of rows produced by an unmerged header cell, only the last
    one has column alignment that actually matches the data that follows -
    earlier repeats should never be able to outscore it, no matter how dense
    or unique they happen to look on their own.
    """
    demoted = list(scores)
    for i in range(len(rows) - 1):
        if scores[i + 1] > 0.0 and _is_repeat_of_next(rows[i], rows[i + 1]):
            demoted[i] = 0.0
    return demoted


def _resolve_label_lookup(
    expected_headers: Sequence[str] | None,
    column_aliases: Mapping[str, Sequence[str]] | None,
) -> dict[str, str] | None:
    """Build a normalized-cell-text -> target-label lookup for the active boost.

    `column_aliases` map each alias to its canonical column name;
    `expected_headers` map to themselves. When both are given, `column_aliases`
    wins outright and `expected_headers` is ignored, so this only ever
    resolves a single mode, once per call. Returns `None` when neither is
    given.
    """
    if column_aliases:
        return {
            normalized: canonical
            for canonical, aliases in column_aliases.items()
            for alias in aliases
            if (normalized := normalize_text(alias))
        }
    if expected_headers:
        return {
            normalized: normalized
            for h in expected_headers
            if (normalized := normalize_text(h))
        }
    return None


def _match_counts(
    rows: Sequence[Sequence[object]],
    label_lookup: Mapping[str, str],
) -> list[int]:
    """Count, per row, how many distinct target labels its cells match."""
    counts = []
    for row in rows:
        normalized_cells = {normalize_text(v) for v in row if not _is_empty(v)}
        matched = {
            label_lookup[cell] for cell in normalized_cells if cell in label_lookup
        }
        counts.append(len(matched))
    return counts


def _apply_boost(scores: list[float], counts: Sequence[int]) -> list[float]:
    """Add a large, count-scaled bonus to whichever row(s) hit the max match count.

    A one-shot signal is meant to override the base heuristic outright, so
    only rows tied for the highest match count are boosted; everything else
    is left untouched.
    """
    max_count = max(counts, default=0)
    if max_count == 0:
        return scores
    return [
        score + _BOOST_SCALE * count if count == max_count else score
        for score, count in zip(scores, counts)
    ]


def _score_row(stats: Sequence[_RowStats], idx: int, weights: HeaderWeights) -> float:
    current = stats[idx]

    # A header row must span at least two columns and have some content.
    if current.column_span < 2 or current.non_empty_ratio == 0.0:
        return 0.0

    # Data contrast: a real header is more text-like than the data row below it.
    data_contrast = 0.0
    if idx + 1 < len(stats):
        data_contrast = max(0.0, current.string_ratio - stats[idx + 1].string_ratio)

    # Density jump: a real header is denser than whatever precedes it
    # (e.g. a title row or a blank row).
    density_jump = 0.0
    if idx > 0:
        density_jump = max(
            0.0, current.non_empty_ratio - stats[idx - 1].non_empty_ratio
        )

    return (
        weights.density * current.non_empty_ratio
        + weights.uniqueness * current.unique_ratio
        + weights.string_ratio * current.string_ratio
        + weights.data_contrast * data_contrast
        + weights.density_jump * density_jump
    )


def detect_header(
    source: FileSource | CalamineWorkbook,
    *,
    sheet_id: int | None = None,
    sheet_name: str | None = None,
    max_scan_rows: int = 100,
    weights: HeaderWeights = DEFAULT_WEIGHTS,
    expected_headers: Sequence[str] | None = None,
    column_aliases: Mapping[str, Sequence[str]] | None = None,
) -> int:
    """Guess which row of a worksheet holds the column headers.

    Scans up to `max_scan_rows` rows of the chosen sheet and scores each one
    on how header-like it looks (dense, mostly text, mostly unique values,
    denser than the row above, more text-like than the row below), returning
    the index of the best-scoring row.

    A row that's a partial or full repeat of the row directly below it - as
    happens when a spreadsheet reader unmerges a vertically-merged header
    cell into duplicate values down every row of the merge - is never picked
    over that row, since only the last row of such a run is actually column-
    aligned with the data that follows.

    Optional boosts
    ----------------
    `expected_headers` and `column_aliases` are one-shot signals: when a
    match is found, the row(s) tied for the most matches get a large
    additive bonus that overrides the base heuristic outright. Both are
    matched case- and punctuation-insensitively, and both are skipped
    entirely when their argument is not provided. If both are provided,
    `column_aliases` wins outright and `expected_headers` is ignored.

    Parameters
    ----------
    source : FileSource | CalamineWorkbook
        Path to file, file-like object, or an already-open workbook.
    sheet_id : int, optional
        1-indexed sheet position. Ignored if `sheet_name` is given. Defaults
        to the first sheet.
    sheet_name : str, optional
        Sheet name; takes precedence over `sheet_id`.
    max_scan_rows : int, optional
        How many leading rows to scan. Default 200.
    expected_headers : Sequence[str], optional
        Expected header labels, e.g. `["po number", "quantity", "ship start
        date"]`. The row containing the most of them (normalized, case
        insensitive) wins a strong score boost. Ignored if `column_aliases`
        is also provided.
    column_aliases : Mapping[str, Sequence[str]], optional
        Canonical column name -> possible header spellings, e.g.
        `{"po_number": ["po#", "po no.", "purchase order"], "quantity":
        ["ord qty", "qty", "order quantity"]}`. The row matching the most
        distinct *canonical* columns (normalized, case insensitive) wins a
        strong score boost. Takes precedence over `expected_headers` if both
        are provided.

    Returns
    -------
    int
        0-indexed row number of the detected header.

    Raises
    ------
    ValueError
        If both `sheet_id` and `sheet_name` are provided.
    """
    if sheet_id is not None and sheet_name is not None:
        raise ValueError(
            "sheet_id and sheet_name cannot be used together; pass at most one of them"
        )
    if sheet_id is not None and sheet_id == 0:
        raise ValueError("sheet_id cannot be 0; pass a non-zero sheet_id")

    if isinstance(source, CalamineWorkbook):
        workbook_ctx = nullcontext(source)
    else:
        if isinstance(source, (BufferedReader, BytesIO)):
            source.seek(0)
        workbook_ctx = CalamineWorkbook.from_object(source)

    with workbook_ctx as workbook:
        sheet = _resolve_sheet(workbook, sheet_id=sheet_id, sheet_name=sheet_name)
        rows = sheet.to_python(
            nrows=max_scan_rows,
            skip_empty_area=False,
        )

        if not rows:
            return 0

        n_cols = max((len(row) for row in rows), default=0)
        if n_cols == 0:
            return 0

        stats = [_row_stats(row, n_cols) for row in rows]
        scores = [_score_row(stats, i, weights) for i in range(len(rows))]
        scores = _demote_duplicate_header_rows(rows, scores)

        label_lookup = _resolve_label_lookup(expected_headers, column_aliases)
        if label_lookup:
            scores = _apply_boost(scores, _match_counts(rows, label_lookup))

    return max(range(len(rows)), key=scores.__getitem__)
