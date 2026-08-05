from __future__ import annotations

import re

import pytest

from rpakit.string import normalize_text

# ---------------------------------------------------------------------------
# Non-string / non-int input -> ""
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        None,
        3.14,
        [1, 2, 3],
        {"a": 1},
        (1, 2),
        object(),
    ],
)
def test_non_string_non_int_input_returns_empty_string(value):
    assert normalize_text(value) == ""


# ---------------------------------------------------------------------------
# int coercion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (42, "42"),
        (0, "0"),
        (-42, "42"),  # the "-" is stripped by the default pattern
    ],
)
def test_int_input_is_stringified(value, expected):
    assert normalize_text(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, "true"),
        (False, "false"),
    ],
)
def test_bool_input_is_stringified_like_int(value, expected):
    # bool is a subclass of int, so it goes through the same coercion path.
    assert normalize_text(value) == expected


# ---------------------------------------------------------------------------
# Basic normalization
# ---------------------------------------------------------------------------


def test_empty_string_returns_empty_string():
    assert normalize_text("") == ""


def test_whitespace_only_returns_empty_string():
    assert normalize_text("   ") == ""


def test_strips_punctuation_and_collapses_whitespace():
    assert normalize_text("  Hello,   World!  ") == "hello world"


def test_removes_punctuation_without_leaving_double_spaces():
    # Regression: deleting a punctuation run flanked by spaces used to
    # leave a double space behind because collapsing happened before the
    # pattern substitution.
    assert normalize_text("Foo - Bar") == "foo bar"


def test_tabs_and_newlines_are_collapsed_to_single_spaces():
    assert normalize_text("Hello\t\nWorld") == "hello world"


def test_leaves_alphanumerics_untouched():
    assert normalize_text("abc123") == "abc123"


# ---------------------------------------------------------------------------
# lowercase
# ---------------------------------------------------------------------------


def test_lowercase_true_by_default():
    assert normalize_text("HELLO World") == "hello world"


def test_lowercase_false_preserves_case():
    assert normalize_text("HELLO World", lowercase=False) == "HELLO World"


# ---------------------------------------------------------------------------
# convert_accents_to_ascii
# ---------------------------------------------------------------------------


def test_accents_are_folded_to_ascii_by_default():
    assert normalize_text("Café Münchën") == "cafe munchen"


def test_accents_left_alone_when_disabled_are_then_stripped_by_pattern():
    # With folding disabled, accented characters are neither ASCII letters
    # nor digits nor whitespace, so the default pattern strips them.
    assert normalize_text("café", convert_accents_to_ascii=False) == "caf"


# ---------------------------------------------------------------------------
# collapse_spaces
# ---------------------------------------------------------------------------


def test_collapse_spaces_true_by_default_merges_runs():
    assert normalize_text("Foo   Bar") == "foo bar"


def test_collapse_spaces_false_preserves_internal_whitespace_runs():
    assert normalize_text("Foo - Bar", collapse_spaces=False) == "foo  bar"


def test_collapse_spaces_false_still_strips_leading_and_trailing():
    assert normalize_text("  Foo Bar  ", collapse_spaces=False) == "foo bar"


# ---------------------------------------------------------------------------
# separator
# ---------------------------------------------------------------------------


def test_separator_none_by_default_leaves_single_spaces():
    assert normalize_text("Foo Bar") == "foo bar"


def test_separator_replaces_spaces():
    assert normalize_text("Foo Bar Baz", separator="_") == "foo_bar_baz"


def test_separator_applies_after_punctuation_removal_and_collapsing():
    assert normalize_text("Foo - Bar", separator="_") == "foo_bar"


def test_separator_empty_string_removes_spaces_entirely():
    assert normalize_text("Foo Bar", separator="") == "foobar"


def test_separator_multi_character():
    assert normalize_text("Foo Bar", separator="---") == "foo---bar"


# ---------------------------------------------------------------------------
# pattern
# ---------------------------------------------------------------------------


def test_custom_pattern_as_raw_string():
    assert normalize_text("abc123def", pattern=r"[0-9]") == "abcdef"


def test_custom_pattern_as_compiled_regex():
    assert normalize_text("Hello World", pattern=re.compile(r"[aeiou]")) == "hll wrld"


def test_default_pattern_keeps_unicode_word_characters_absent():
    # Non-ASCII letters aren't in [a-zA-Z0-9\s], so they're stripped even
    # though they're "alphanumeric" in a broader sense.
    assert normalize_text("你好 World", convert_accents_to_ascii=False) == "world"


# ---------------------------------------------------------------------------
# Combined options
# ---------------------------------------------------------------------------


def test_all_options_combined():
    result = normalize_text(
        "  Café - MÜNCHEN_2024!!  ",
        separator="_",
        lowercase=True,
        convert_accents_to_ascii=True,
        collapse_spaces=True,
    )
    # The literal "_" in "MÜNCHEN_2024" is removed by the default pattern
    # (it's neither an ASCII letter/digit nor whitespace), so it doesn't
    # survive to be affected by `separator` the way the space does.
    assert result == "cafe_munchen2024"


def test_no_transformations_when_all_flags_disabled():
    result = normalize_text(
        "Café   Bar",
        lowercase=False,
        convert_accents_to_ascii=False,
        collapse_spaces=False,
    )
    # "é" is stripped by the default pattern regardless, since it's neither
    # an ASCII letter/digit nor whitespace.
    assert result == "Caf   Bar"
