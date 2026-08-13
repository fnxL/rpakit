from collections.abc import Mapping

import polars as pl

from rpakit.string import normalize_text as _norm


def normalize_columns(df: pl.DataFrame) -> pl.DataFrame:
    """Normalize a dataframe's column names.

    Each column name is lowercased, stripped of punctuation/brackets, and
    has its whitespace collapsed and replaced with underscores (via
    :func:`rpakit.string.normalize_text`)

    Parameters
    ----------
    df : pl.DataFrame
        Input dataframe.

    Returns
    -------
    pl.DataFrame
        The same dataframe, with normalized column names.

    Note
    ----
    `df` is mutated directly (``df.columns`` is reassigned); the return
    value is the same object, provided for convenient chaining.

    Examples
    --------
    >>> df = pl.DataFrame({"Foo Bar": 1, "Baz-Qux": 2})
    >>> df.columns
    ['Foo Bar', 'Baz-Qux']
    >>> df = normalize_columns(df)
    >>> df.columns
    ['foo_bar', 'baz_qux']
    """
    df.columns = [_norm(c, separator="_") for c in df.columns]
    return df


def safe_schema_override(
    df: pl.DataFrame,
    schema_overrides: Mapping[str, pl.DataType],
    strict: bool = False,
) -> pl.DataFrame:
    if not schema_overrides:
        return df

    df_col_map = {}
    for col in df.columns:
        df_col_map[col.lower().strip()] = col

    valid_schema_overrides = {}
    for col, dtype in schema_overrides.items():
        lower = col.lower().strip()
        if lower in df_col_map:
            orig_col = df_col_map[lower]
            valid_schema_overrides[orig_col] = dtype

    return df.cast(schema_overrides, strict=strict)  # ty: ignore[invalid-argument-type]
