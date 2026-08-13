from collections.abc import Mapping, Sequence

import polars as pl

from rpakit.string import normalize_text as _norm


def _build_alias_lookup(
    column_aliases: Mapping[str, str | Sequence[str]],
) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for canonical, aliases in column_aliases.items():
        alias_list = [aliases] if isinstance(aliases, str) else aliases

        lookup[canonical] = _norm(canonical)

        normalized_aliases = {_norm(alias) for alias in alias_list}
        for alias in normalized_aliases:
            if alias in lookup:
                raise ValueError(
                    f"Column alias {alias} is already in use. "
                    f"Maps to both {lookup[alias]!r} and {canonical!r}"
                )
            lookup[alias] = canonical

    return lookup


def _map_dataframe_columns(
    columns: Sequence[str],
    lookup: Mapping[str, str],
) -> tuple[dict[str, str], dict[str, str]]:
    rename_map: dict[str, str] = {}
    restore_map: dict[str, str] = {}
    used_canonicals: dict[str, str] = {}

    for col in columns:
        key = _norm(col)
        if key not in lookup:
            continue

        canonical = lookup[key]
        if canonical in used_canonicals:
            raise ValueError(
                f"Multiple columns map to the same canonical: {canonical!r}."
                f"Column {used_canonicals[canonical]!r} already maps to {canonical!r}. "
                f"Column {col!r} is also trying to map to {canonical!r}."
            )

        used_canonicals[canonical] = col
        restore_map[canonical] = col

        if canonical != col:
            rename_map[col] = canonical

    return rename_map, restore_map


def standardize_columns(
    df: pl.DataFrame,
    column_aliases: Mapping[str, str | Sequence[str]],
) -> tuple[pl.DataFrame, dict[str, str]]:
    """Rename columns to canonical names based on the column_aliases mapping.

    Each column in `df` is matched, case- and format-insensitively (via
    `normalize_text`), against `column_aliases` and renamed to its
    canonical name when a match is found. Columns with no matching alias
    are left unchanged.

    Parameters
    ----------
    df : pl.DataFrame
        The input dataframe.
    column_aliases : Mapping[str, str | Sequence[str]]
        Mapping of standard/canonical column names to a possible alias or
        list of aliases.

    Returns
    -------
    tuple[pl.DataFrame, dict[str, str]]
        The dataframe with matched columns renamed to their canonical
        names, and a `restore_map` (canonical name -> original column
        name) that can be used to rename the columns back.

    Raises
    ------
    ValueError
        If the same alias is declared for more than one canonical name, or
        if more than one column in `df` matches the same canonical name.
    """
    if not column_aliases:
        return df, {}

    lookup = _build_alias_lookup(column_aliases)
    rename_map, restore_map = _map_dataframe_columns(df.columns, lookup)

    if rename_map:
        df = df.rename(rename_map)

    return df, restore_map
