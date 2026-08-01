import polars as pl


def read_excel(path: str) -> pl.DataFrame:
    return pl.read_excel(path)
