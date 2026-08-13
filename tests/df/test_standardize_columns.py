import polars as pl
import pytest

from rpakit.df import standardize_columns


def test_standardize_columns_basic():
    df = pl.DataFrame(
        {"name": ["Alice", "Bob"], "age": [25, 30], "city": ["New York", "London"]}
    )

    mapping = {"full_name": ["name"], "years_old": ["age"], "location": ["city"]}

    result, _ = standardize_columns(df, mapping)
    expected_columns = ["full_name", "years_old", "location"]

    assert result.columns == expected_columns
    assert result.shape == df.shape


def test_standardize_columns_case_insensitive():
    """Test that column names are normalized to lowercase."""
    df = pl.DataFrame(
        {"Name": ["Alice", "Bob"], "AGE": [25, 30], "City": ["New York", "London"]}
    )

    mapping = {"full_name": ["name"], "years_old": ["age"], "location": ["city"]}

    result, _ = standardize_columns(df, mapping)
    expected_columns = ["full_name", "years_old", "location"]

    assert result.columns == expected_columns


def test_standardize_columns_with_punctuation():
    """Test that punctuation is stripped from column names."""
    df = pl.DataFrame(
        {"name?": ["Alice", "Bob"], "age!": [25, 30], "city.": ["New York", "London"]}
    )

    mapping = {"full_name": ["name"], "years_old": ["age"], "location": ["city"]}

    result, _ = standardize_columns(df, mapping)
    expected_columns = ["full_name", "years_old", "location"]

    assert result.columns == expected_columns


def test_standardize_columns_with_whitespace():
    """Test that whitespace is stripped from column names."""
    df = pl.DataFrame(
        {
            " name ": ["Alice", "Bob"],
            " age ": [25, 30],
            " city ": ["New York", "London"],
        }
    )

    mapping = {"full_name": ["name"], "years_old": ["age"], "location": ["city"]}

    result, _ = standardize_columns(df, mapping)
    expected_columns = ["full_name", "years_old", "location"]

    assert result.columns == expected_columns


def test_standardize_columns_partial_match():
    """Test column renaming with partial matches in the mapping."""
    df = pl.DataFrame(
        {
            "first_name": ["Alice", "Bob"],
            "age_years": [25, 30],
            "city_name": ["New York", "London"],
        }
    )

    mapping = {"name": ["first_name"], "age": ["age_years"], "city": ["city_name"]}

    result, _ = standardize_columns(df, mapping)
    expected_columns = ["name", "age", "city"]

    assert result.columns == expected_columns


def test_standardize_columns_string_mapping():
    """Test column mapping with string values instead of lists."""
    df = pl.DataFrame({"name": ["Alice", "Bob"], "age": [25, 30]})

    # Using string instead of list for mapping
    mapping = {"full_name": "name", "years_old": "age"}

    result, _ = standardize_columns(df, mapping)
    expected_columns = ["full_name", "years_old"]

    assert result.columns == expected_columns


def test_standardize_columns_no_changes_needed():
    """Test that DataFrame is returned unchanged if no mappings apply."""
    df = pl.DataFrame({"name": ["Alice", "Bob"], "age": [25, 30]})

    mapping = {"full_name": ["first_name"], "years_old": ["birth_age"]}

    result, _ = standardize_columns(df, mapping)

    # The columns should remain unchanged since no mappings apply
    assert result.columns == df.columns
    assert result.shape == df.shape


def test_standardize_columns_duplicate_mapping_error():
    """Test that ValueError is raised when duplicate column names exist in mapping."""
    df = pl.DataFrame({"name": ["Alice", "Bob"], "age": [25, 30]})

    # This mapping has duplicate column names that map to different final names
    mapping = {
        "full_name": ["name"],
        "person_name": ["name"],  # 'name' maps to both 'full_name' and 'person_name'
    }

    with pytest.raises(ValueError, match="Column alias name is already in use."):
        standardize_columns(df, mapping)


def test_standardize_columns_multiple_df_columns_to_same_final_error():
    """Test that ValueError is raised when multiple DataFrame columns map to the same final name."""
    df = pl.DataFrame(
        {
            "name": ["Alice", "Bob"],
            "first_name": [
                "Alice",
                "Bob",
            ],  # This will match the same final name as 'name'
            "age": [25, 30],
        }
    )

    mapping = {
        "full_name": [
            "name",
            "first_name",
        ],  # Both 'name' and 'first_name' map to 'full_name'
    }

    # This should raise an error because both columns in the df will map to the same final name
    with pytest.raises(ValueError, match="Multiple columns map to the same"):
        standardize_columns(df, mapping)


def test_standardize_columns_empty_mapping():
    """Test that DataFrame is returned unchanged if mapping is empty."""
    df = pl.DataFrame({"name": ["Alice", "Bob"], "age": [25, 30]})

    mapping = {}

    result, _ = standardize_columns(df, mapping)

    assert result.columns == df.columns
    assert result.shape == df.shape


def test_standardize_columns_complex_normalization():
    """Test comprehensive normalization with mixed case, punctuation, and whitespace."""
    df = pl.DataFrame(
        {
            "Name ?": ["Alice", "Bob"],
            "AGE !": [25, 30],
            " City . ": ["New York", "London"],
        }
    )

    mapping = {"full_name": ["name"], "years_old": ["age"], "location": ["city"]}

    result, _ = standardize_columns(df, mapping)
    expected_columns = ["full_name", "years_old", "location"]

    assert result.columns == expected_columns
