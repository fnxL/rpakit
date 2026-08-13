from __future__ import annotations

from datetime import date
from io import BytesIO
from typing import Any

import pytest
import xlsxwriter

from rpakit.excel.detect_header import (
    DEFAULT_WEIGHTS,
    HeaderWeights,
    _apply_boost,
    _cells_equal,
    _demote_duplicate_header_rows,
    _is_empty,
    _is_repeat_of_next,
    _match_counts,
    _resolve_label_lookup,
    _row_stats,
    _score_row,
    detect_header,
)


def _xlsx(
    rows: list[list[Any]],
    *,
    sheet_name: str | None = None,
    extra_sheets: dict[str, list[list[Any]]] | None = None,
) -> BytesIO:
    """Build an in-memory .xlsx workbook from a list of rows."""
    buf = BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    date_format = wb.add_format({"num_format": "yyyy-mm-dd"})

    def _write_rows(ws: Any, rows: list[list[Any]]) -> None:
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                if isinstance(value, date):
                    ws.write_datetime(r, c, value, date_format)
                else:
                    ws.write(r, c, value)

    _write_rows(wb.add_worksheet(sheet_name), rows)
    for name, extra_rows in (extra_sheets or {}).items():
        _write_rows(wb.add_worksheet(name), extra_rows)

    wb.close()
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# HeaderWeights
# ---------------------------------------------------------------------------


def test_default_weights_sum_to_one():
    w = DEFAULT_WEIGHTS
    total = w.density + w.uniqueness + w.string_ratio + w.data_contrast + w.density_jump
    assert total == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# _is_empty
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, True),
        ("", True),
        ("   ", True),
        ("x", False),
        (0, False),
        (0.0, False),
        ("0", False),
        (False, False),
    ],
)
def test_is_empty(value, expected):
    assert _is_empty(value) is expected


# ---------------------------------------------------------------------------
# _row_stats
# ---------------------------------------------------------------------------


def test_row_stats_all_empty_row():
    stats = _row_stats([None, "", "  "], n_cols=3)
    assert stats.column_span == 3
    assert stats.non_empty_ratio == 0.0
    assert stats.unique_ratio == 0.0
    assert stats.string_ratio == 0.0


def test_row_stats_fully_dense_unique_strings():
    stats = _row_stats(["A", "B", "C"], n_cols=3)
    assert stats.column_span == 3
    assert stats.non_empty_ratio == 1.0
    assert stats.unique_ratio == 1.0
    assert stats.string_ratio == 1.0


def test_row_stats_duplicates_and_mixed_types():
    stats = _row_stats(["A", "A", 1], n_cols=3)
    assert stats.non_empty_ratio == 1.0
    assert stats.unique_ratio == pytest.approx(2 / 3)
    assert stats.string_ratio == pytest.approx(2 / 3)


def test_row_stats_shorter_than_widest_row():
    # n_cols reflects the sheet's widest row, not this row's own length.
    stats = _row_stats(["A", "B"], n_cols=4)
    assert stats.non_empty_ratio == 0.5


# ---------------------------------------------------------------------------
# _score_row
# ---------------------------------------------------------------------------


def test_score_row_disqualifies_single_column_span():
    stats = [_row_stats(["A"], n_cols=1)]
    assert _score_row(stats, 0, DEFAULT_WEIGHTS) == 0.0


def test_score_row_disqualifies_all_empty_row():
    stats = [_row_stats([None, None], n_cols=2)]
    assert _score_row(stats, 0, DEFAULT_WEIGHTS) == 0.0


def test_score_row_rewards_contrast_with_row_below():
    # header (all text) directly above a numeric data row.
    stats = [
        _row_stats(["Name", "Amount"], n_cols=2),
        _row_stats(["Bob", 10], n_cols=2),
    ]
    score = _score_row(stats, 0, DEFAULT_WEIGHTS)
    expected = (
        DEFAULT_WEIGHTS.density * 1.0
        + DEFAULT_WEIGHTS.uniqueness * 1.0
        + DEFAULT_WEIGHTS.string_ratio * 1.0
        + DEFAULT_WEIGHTS.data_contrast * 0.5  # 1.0 - 0.5
    )
    assert score == pytest.approx(expected)


def test_score_row_uses_custom_weights():
    stats = [
        _row_stats(["Name", "Amount"], n_cols=2),
        _row_stats(["Bob", 10], n_cols=2),
    ]
    density_only = HeaderWeights(
        density=1.0,
        uniqueness=0.0,
        string_ratio=0.0,
        data_contrast=0.0,
        density_jump=0.0,
    )
    assert _score_row(stats, 0, density_only) == pytest.approx(1.0)


def test_score_row_rewards_density_jump_from_row_above():
    stats = [
        _row_stats([None, None], n_cols=2),  # blank row above
        _row_stats(["Name", "Amount"], n_cols=2),
    ]
    score = _score_row(stats, 1, DEFAULT_WEIGHTS)
    expected = (
        DEFAULT_WEIGHTS.density * 1.0
        + DEFAULT_WEIGHTS.uniqueness * 1.0
        + DEFAULT_WEIGHTS.string_ratio * 1.0
        + DEFAULT_WEIGHTS.density_jump * 1.0  # 1.0 - 0.0
    )
    assert score == pytest.approx(expected)


# ---------------------------------------------------------------------------
# _cells_equal / _is_repeat_of_next / _demote_duplicate_header_rows
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("PO Number", "po number", True),
        ("PO#", "po", True),
        ("Name", "Age", False),
        (5, 5, True),
        (5, 5.0, True),  # int/float compare equal like Python's ==
        (5, 7, False),
        ("5", 5, False),  # a string is never equal to a non-string
        (None, None, True),
    ],
)
def test_cells_equal(a, b, expected):
    assert _cells_equal(a, b) is expected


def test_is_repeat_of_next_true_when_overlapping_cells_all_match():
    # row has an extra populated cell the next row doesn't - still a repeat.
    assert _is_repeat_of_next(
        ["Name", "Age", "Height", "UNNAMED"], ["Name", "Age", "Height", None]
    )


def test_is_repeat_of_next_false_on_any_mismatch():
    assert not _is_repeat_of_next(["Name", "Age", "Height"], ["Ajay", 2, 3])


def test_is_repeat_of_next_false_when_nothing_overlaps():
    # no shared populated position means there's nothing to call a "repeat".
    assert not _is_repeat_of_next([None, None], [None, None])
    assert not _is_repeat_of_next(["Name", None], [None, "Age"])


def test_is_repeat_of_next_does_not_confuse_distinct_numbers():
    # both numeric and neither equal to the other - never a "repeat", even
    # though neither side has meaningful normalized text.
    assert not _is_repeat_of_next([1, 2, 3], [4, 5, 6])


def test_demote_duplicate_header_rows_keeps_only_the_last_of_a_run():
    rows = [
        ["Name", "Age", "Height", "UNNAMED"],
        ["Name", "Age", "Height", None],
        ["Name", "Age", "Height", None],
        ["Ajay", 2, 3],
    ]
    scores = [0.825, 0.675, 0.775, 0.5417]
    demoted = _demote_duplicate_header_rows(rows, scores)
    assert demoted == [0.0, 0.0, 0.775, 0.5417]


def test_demote_duplicate_header_rows_leaves_non_repeats_untouched():
    rows = [["Col1", "Col2"], ["PO Number", "Quantity"], ["PO1", 5]]
    scores = [0.9, 0.7, 0.5]
    assert _demote_duplicate_header_rows(rows, scores) == scores


def test_demote_duplicate_header_rows_does_not_demote_into_a_disqualified_row():
    # a row is only demoted in favor of a row below that itself qualifies
    # (score > 0); a repeat followed by a blank row is left alone.
    rows = [["Name", "Age"], [None, None]]
    scores = [0.9, 0.0]
    assert _demote_duplicate_header_rows(rows, scores) == scores


# ---------------------------------------------------------------------------
# _resolve_label_lookup
# ---------------------------------------------------------------------------


def test_resolve_label_lookup_expected_headers_map_to_themselves():
    lookup = _resolve_label_lookup(["PO Number", "Quantity"], None)
    assert lookup == {"po number": "po number", "quantity": "quantity"}


def test_resolve_label_lookup_column_aliases_map_to_canonical():
    lookup = _resolve_label_lookup(
        None, {"po_number": ["po#", "purchase order"], "quantity": ["qty"]}
    )
    assert lookup == {
        "po": "po_number",
        "purchase order": "po_number",
        "qty": "quantity",
    }


def test_resolve_label_lookup_expected_headers_take_precedence():
    lookup = _resolve_label_lookup(["po number"], {"quantity": ["qty"]})
    assert lookup == {"po number": "po number"}


def test_resolve_label_lookup_none_when_neither_given():
    assert _resolve_label_lookup(None, None) is None
    assert _resolve_label_lookup([], {}) is None


def test_resolve_label_lookup_drops_labels_that_normalize_to_empty():
    lookup = _resolve_label_lookup(["   ", "!!!"], None)
    assert lookup == {}


# ---------------------------------------------------------------------------
# _match_counts
# ---------------------------------------------------------------------------


def test_match_counts_counts_distinct_target_labels_per_row():
    rows = [
        ["Purchase Order Report"],
        ["PO Number", "Quantity", "Ship Start Date"],
        ["PO1", 5, "2026-01-01"],
    ]
    lookup = _resolve_label_lookup(
        ["po number", "quantity", "ship start date", "does not exist"], None
    )
    assert lookup is not None
    assert _match_counts(rows, lookup) == [0, 3, 0]


def test_match_counts_does_not_double_count_same_canonical():
    # Two different aliases for the same canonical column in one row still
    # count once, not twice.
    lookup = _resolve_label_lookup(None, {"po_number": ["po#", "purchase order"]})
    rows = [["po#", "purchase order"]]
    assert lookup is not None
    assert _match_counts(rows, lookup) == [1]


def test_match_counts_is_case_and_punctuation_insensitive():
    lookup = _resolve_label_lookup(["PO Number"], None)
    rows = [["po#"], ["PO NUMBER"], ["  Po. Number  "]]
    assert lookup is not None
    assert _match_counts(rows, lookup) == [0, 1, 1]


def test_match_counts_empty_lookup():
    rows = [["A", "B"], ["C", "D"]]
    assert _match_counts(rows, {}) == [0, 0]


# ---------------------------------------------------------------------------
# _apply_boost
# ---------------------------------------------------------------------------


def test_apply_boost_boosts_only_max_count_rows():
    scores = [0.9, 0.1, 0.5]
    counts = [1, 3, 3]
    boosted = _apply_boost(scores, counts)
    assert boosted[0] == 0.9
    assert boosted[1] > boosted[0]
    assert boosted[2] > boosted[0]
    # among tied counts, the higher base score still wins
    assert boosted[2] > boosted[1]


def test_apply_boost_noop_when_no_matches():
    scores = [0.9, 0.1, 0.5]
    assert _apply_boost(scores, [0, 0, 0]) == scores


# ---------------------------------------------------------------------------
# detect_header - basic behaviour
# ---------------------------------------------------------------------------


def test_detect_header_finds_obvious_header_row():
    buf = _xlsx(
        [
            ["Monthly Report"],  # sparse title row, only 1 column wide
            ["Name", "Amount", "Date"],
            ["Bob", 10, "2026-01-01"],
            ["Alice", 20, "2026-01-02"],
        ]
    )
    assert detect_header(buf) == 1


def test_detect_header_empty_sheet_returns_zero():
    buf = _xlsx([])
    assert detect_header(buf) == 0


def test_detect_header_sheet_name_selects_sheet():
    buf = _xlsx(
        [["Junk"]],
        sheet_name="Summary",
        extra_sheets={"Data": [["Name", "Amount"], ["Bob", 10]]},
    )
    assert detect_header(buf, sheet_name="Data") == 0


def test_detect_header_sheet_id_is_one_indexed():
    buf = _xlsx(
        [["Junk"]],
        sheet_name="Summary",
        extra_sheets={"Data": [["Name", "Amount"], ["Bob", 10]]},
    )
    assert detect_header(buf, sheet_id=2) == 0


def test_detect_header_rejects_both_sheet_id_and_sheet_name():
    buf = _xlsx([["Name", "Amount"], ["Bob", 10]])
    with pytest.raises(ValueError, match="sheet_id and sheet_name"):
        detect_header(buf, sheet_id=1, sheet_name="Sheet")


def test_detect_header_rejects_sheet_id_zero():
    buf = _xlsx([["Name", "Amount"], ["Bob", 10]])
    with pytest.raises(ValueError, match="sheet_id cannot be 0"):
        detect_header(buf, sheet_id=0)


def test_detect_header_prefers_last_row_of_an_unmerged_header_block():
    # A vertically-merged header cell, unmerged by the reader into repeated
    # values down every row of the merge - only the last row (index 6) is
    # actually column-aligned with the data that follows.
    buf = _xlsx(
        [
            [None, None, None, None],
            [None, None, None, None],
            [None, None, "IMPORT", None],
            ["Name", "Age", "Height", "UNNAMED"],
            ["Name", "Age", "Height", None],
            ["Name", "Age", "Height", None],
            ["Name", "Age", "Height", None],
            ["Ajay", 2, 3],
            ["Sanjay", 5, 3],
            ["Ranjeet", 4, 3],
        ]
    )
    assert detect_header(buf) == 6


def test_detect_header_respects_max_scan_rows():
    # single-column numeric filler: never header-like, but still real rows.
    filler = [[i] for i in range(1, 16)]
    rows = filler + [["PO Number", "Quantity", "Ship Date"], ["PO1", 5, "2026-01-01"]]
    buf1 = _xlsx(rows)
    assert detect_header(buf1, max_scan_rows=100) == 15

    buf2 = _xlsx(rows)
    # header sits outside the scanned window, so it can't be selected.
    result = detect_header(buf2, max_scan_rows=5)
    assert result != 15
    assert result < 5


# ---------------------------------------------------------------------------
# detect_header - expected-headers / column-alias boosts
# ---------------------------------------------------------------------------


def _decoy_and_header_rows() -> list[list[Any]]:
    """Rows where the base heuristic prefers row 0 over the real header (row 2)."""
    return [
        ["Col1", "Col2", "Col3", "Col4"],  # decoy: dense, unique, all text
        [1, 2, 3, 4],  # numeric row makes the decoy's contrast look great
        ["PO Number", "Quantity"],  # the real header
        ["PO1", 5],
    ]


def test_detect_header_without_boost_can_pick_the_wrong_row():
    buf = _xlsx(_decoy_and_header_rows())
    assert detect_header(buf) == 0


def test_detect_header_expected_headers_override_base_score():
    buf = _xlsx(_decoy_and_header_rows())
    result = detect_header(buf, expected_headers=["po number", "quantity"])
    assert result == 2


def test_detect_header_expected_headers_with_no_match_falls_back_to_base_score():
    buf = _xlsx(_decoy_and_header_rows())
    result = detect_header(buf, expected_headers=["does not appear anywhere"])
    assert result == 0


def test_detect_header_column_aliases_override_base_score():
    buf = _xlsx(_decoy_and_header_rows())
    column_aliases = {
        "po_number": ["po#", "po no.", "purchase order", "po number"],
        "quantity": ["ord qty", "qty", "order quantity", "quantity"],
    }
    result = detect_header(buf, column_aliases=column_aliases)
    assert result == 2


def test_detect_header_column_aliases_with_no_match_falls_back_to_base_score():
    buf = _xlsx(_decoy_and_header_rows())
    result = detect_header(buf, column_aliases={"unrelated": ["does not appear"]})
    assert result == 0


def test_detect_header_rejects_both_boosts_together():
    buf = _xlsx(_decoy_and_header_rows())
    with pytest.raises(ValueError, match="expected_headers and column_aliases"):
        detect_header(
            buf,
            expected_headers=["po number"],
            column_aliases={"po_number": ["po#"]},
        )


def test_detect_header_column_aliases_are_normalized_against_cells():
    buf = _xlsx(
        [
            ["Field1", "Field2", "Field3", "Field4"],
            [1, 2, 3, 4],
            ["PO#", "Ord. Qty"],
            ["PO1", 5],
        ]
    )
    # "po number"/"quantity" wouldn't literally match "PO#"/"Ord. Qty", but
    # normalized aliases do.
    result = detect_header(
        buf,
        column_aliases={"po_number": ["po#"], "quantity": ["ord qty"]},
    )
    assert result == 2


# ---------------------------------------------------------------------------
# detect_header - realistic / complex scenarios
# ---------------------------------------------------------------------------


def test_detect_header_realistic_export_with_banner_and_typed_data():
    # A typical automated export: a title banner, a generated-on line, a
    # blank spacer, then the real header, then rows mixing strings, dates,
    # ints and floats.
    buf = _xlsx(
        [
            ["ACME Corp - Purchase Order Export"],
            ["Generated: 2026-08-01"],
            [None, None, None, None, None],
            ["PO Number", "Vendor", "Order Date", "Qty", "Amount"],
            ["PO-1001", "Acme Supplies", date(2026, 1, 15), 10, 199.99],
            ["PO-1002", "Beta Traders", date(2026, 1, 16), 5, 89.5],
            ["PO-1003", "Gamma Inc", date(2026, 1, 17), 20, 450.0],
        ]
    )
    assert detect_header(buf) == 3


def test_detect_header_two_level_grouped_header_prefers_denser_sub_header():
    # A sparse "group label" row (as produced by merged cells spanning
    # several columns) sits above the real, fully-populated column-name row.
    buf = _xlsx(
        [
            ["Personal Info", None, "Contact Info", None],
            ["Name", "Age", "Email", "Phone"],
            ["Bob", 30, "bob@x.com", "555-1234"],
            ["Alice", 25, "alice@x.com", "555-5678"],
        ]
    )
    assert detect_header(buf) == 1


def test_detect_header_non_adjacent_repeat_does_not_trigger_demotion():
    # The header text reappears far below (e.g. a repeated banner or a
    # second data block) - demotion only looks at the row directly below,
    # so this must not suppress the real header at row 0.
    buf = _xlsx(
        [
            ["Name", "Age", "Height"],
            ["Bob", 30, 5.9],
            ["Alice", 25, 5.5],
            ["Name", "Age", "Height"],
            ["Carol", 22, 5.6],
        ]
    )
    assert detect_header(buf) == 0


def test_detect_header_duplicate_block_composes_with_expected_headers_boost():
    # Rows 2 and 3 both contain "Name"/"Age"/"Height" (tied match count), so
    # the boost alone can't break the tie - it must fall back to the
    # already-demoted base score, which still prefers the last row.
    buf = _xlsx(
        [
            [None, None, None, None],
            [None, None, "IMPORT", None],
            ["Name", "Age", "Height", "UNNAMED"],
            ["Name", "Age", "Height", None],
            ["Ajay", 2, 3],
        ]
    )
    result = detect_header(buf, expected_headers=["Name", "Age", "Height"])
    assert result == 3


def test_detect_header_selects_correct_sheet_among_decoy_sheets():
    readme_rows = [["This workbook contains PO data."], ["Contact IT for access."]]
    summary_rows = [["Total POs", 42], ["Total Amount", 91234.56]]
    data_rows = [
        ["Report"],
        [None, None, None],
        ["PO Number", "Quantity", "Ship Date"],
        ["PO1", 5, "2026-01-01"],
        ["PO2", 8, "2026-01-02"],
    ]
    buf = _xlsx(
        readme_rows,
        sheet_name="ReadMe",
        extra_sheets={"Summary": summary_rows, "Data": data_rows},
    )
    assert detect_header(buf, sheet_name="Data") == 2


def test_detect_header_multiple_separate_duplicate_blocks_picks_the_stronger_one():
    # Two unrelated duplicate-header-looking blocks in the same sheet (e.g.
    # two stitched-together exports); each collapses to its own last row,
    # and the higher-scoring one (denser, directly touching real data) wins.
    buf = _xlsx(
        [
            ["Old Name", "Old Age"],  # weak block: only 2 columns, no data below
            ["Old Name", "Old Age"],
            [None, None, None],
            ["Name", "Age", "City"],  # strong block: 3 columns, real data below
            ["Name", "Age", "City"],
            ["Bob", 30, "NYC"],
            ["Alice", 25, "LA"],
        ]
    )
    assert detect_header(buf) == 4


def test_detect_header_duplicate_block_deep_after_long_filler_run():
    filler = [["Filler"] for _ in range(20)]
    rows = filler + [
        ["Name", "Age", "City", "Extra"],
        ["Name", "Age", "City", None],
        ["Bob", 30, "NYC"],
    ]
    assert detect_header(_xlsx(rows), max_scan_rows=100) == 21


def test_detect_header_fully_identical_duplicate_rows_all_demoted_but_last():
    buf = _xlsx(
        [
            ["Name", "Age"],
            ["Name", "Age"],
            ["Name", "Age"],
            ["Name", "Age"],
            ["Bob", 30],
        ]
    )
    assert detect_header(buf) == 3


def test_detect_header_numeric_looking_header_cells():
    # Year-labeled columns: the header row itself is partly numeric, which
    # should not disqualify it from being detected.
    buf = _xlsx(
        [
            ["Region", 2024, 2025, 2026],
            ["North", 100, 120, 140],
            ["South", 80, 95, 110],
        ]
    )
    assert detect_header(buf) == 0


def test_detect_header_single_row_sheet_has_no_qualifying_header():
    # A single row can't have "the row below" contrast and, with only one
    # column populated per cell here, doesn't even span 2 columns - falls
    # back to row 0.
    buf = _xlsx([["OnlyOneCell"]])
    assert detect_header(buf) == 0


def test_detect_header_all_rows_blank_returns_zero():
    buf = _xlsx([[None, None], [None, None], [None, None]])
    assert detect_header(buf) == 0
