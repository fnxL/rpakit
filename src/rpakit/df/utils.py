from collections.abc import Mapping

import polars as pl


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
