from collections.abc import Mapping, Sequence
from typing import TypedDict

import polars as pl
from python_calamine import CalamineWorkbook

from rpakit.df import standardize_columns
from rpakit.df.utils import safe_schema_override
from rpakit.excel.detect_header import detect_header
from rpakit.excel.helpers import SheetMetadata, list_sheets
from rpakit.string import normalize_text as _norm
from rpakit.types import FileSource


class DetectHeaderOpts(TypedDict):
    """Options for detecting the header row of an Excel sheet."""

    max_scan_rows: int
    expected_headers: Sequence[str] | None


class ExcelReader:
    """Reads an Excel file into a polars DataFrame."""

    def __init__(self, source: FileSource):
        self.source = source
        self._calamine_wb = CalamineWorkbook.from_object(source)
        self.sheets = list_sheets(self._calamine_wb)
        self.visible_sheets = self._get_visible_sheets()

    def _get_visible_sheets(self) -> list[SheetMetadata]:
        return [sheet for sheet in self.sheets if not sheet.is_hidden]

    def _read_raw_sheet(
        self,
        sheet_name: str | None,
        sheet_id: int | None,
        header_row: int | None,
        drop_empty_rows: bool,
        drop_empty_cols: bool,
    ) -> pl.DataFrame:
        read_options = {}
        if header_row is not None:
            read_options["header_row"] = header_row

        return pl.read_excel(
            self.source,
            sheet_id=sheet_id,
            sheet_name=sheet_name,
            drop_empty_cols=drop_empty_cols,
            drop_empty_rows=drop_empty_rows,
            read_options=read_options,
        )

    def _select_best_sheet(
        self,
        detect_header_opts: DetectHeaderOpts | None,
        column_aliases: Mapping[str, str | Sequence[str]],
        drop_empty_rows: bool,
        drop_empty_cols: bool,
    ) -> tuple[str, pl.DataFrame]:
        """Pick whichever visible sheet's header matches the most canonical columns.

        Every visible sheet gets its header row detected (boosted by
        `column_aliases`, same as a normal `detect_header_opts` call) and is
        read into a DataFrame. Each DataFrame is checked against
        `column_aliases` via `standardize_columns`, and the sheet whose
        columns resolve the most distinct canonical names wins - ties keep
        the earliest sheet in workbook order. The winning DataFrame is
        returned as-is (not yet standardized) so the caller can run it
        through the normal post-processing steps exactly once.
        """
        if not self.visible_sheets:
            raise ValueError("Workbook has no visible sheets to select from.")

        opts = detect_header_opts or DetectHeaderOpts(
            max_scan_rows=100, expected_headers=None
        )

        best_name: str | None = None
        best_df: pl.DataFrame | None = None
        best_match_count = -1

        for sheet in self.visible_sheets:
            header_row = self._resolve_header_row(
                sheet_name=sheet.name,
                sheet_id=None,
                detect_header_opts=opts,
                header_row=None,
                column_aliases=column_aliases,
            )
            df = self._read_raw_sheet(
                sheet_name=sheet.name,
                sheet_id=None,
                header_row=header_row,
                drop_empty_rows=drop_empty_rows,
                drop_empty_cols=drop_empty_cols,
            )
            _, restore_map = standardize_columns(df, column_aliases)
            match_count = len(restore_map)

            if match_count > best_match_count:
                best_name, best_df, best_match_count = sheet.name, df, match_count

        assert best_name is not None and best_df is not None  # loop ran >= once
        return best_name, best_df

    def _resolve_header_row(
        self,
        sheet_name: str | None,
        sheet_id: int | None,
        detect_header_opts: DetectHeaderOpts | None,
        header_row: int | None,
        column_aliases: Mapping[str, Sequence[str]] | None,
    ) -> int | None:
        """Resolve the header row to use, giving `header_row` priority.

        If `header_row` is explicitly provided, it wins and `detect_header`
        is not called at all, even if `detect_header_options` is set.
        """
        if header_row is not None:
            return header_row

        if detect_header_opts is None:
            return None

        return detect_header(
            source=self._calamine_wb,
            sheet_name=sheet_name,
            sheet_id=sheet_id,
            column_aliases=column_aliases,
            max_scan_rows=detect_header_opts.get("max_scan_rows") or 100,
            expected_headers=detect_header_opts.get("expected_headers"),
        )

    def read_sheet(
        self,
        sheet_name: str | None = None,
        sheet_id: int | None = None,
        use_first_visible: bool = False,
        detect_header_opts: DetectHeaderOpts | None = None,
        header_row: int
        | None = None,  # Overrides header_row returned from calling detect_header
        normalize_column_names: bool = False,
        column_aliases: Mapping[str, str | Sequence[str]] | None = None,
        scan_all_sheets: bool = False,
        drop_empty_rows: bool = True,
        drop_empty_cols: bool = True,
        schema_overrides: dict[str, pl.DataType] | None = None,
    ) -> pl.DataFrame:
        """
        Reads a single sheet from an excel workbook into a polars DataFrame.

        If neither `sheet_name` nor `sheet_id` is given, the workbook's first
        sheet is read (or its first *visible* sheet, if `use_first_visible`
        is True). The header row is resolved via `header_row` (an explicit
        override that skips header detection entirely) or `detect_header_opts`
        (a heuristic scan); if neither is given, the sheet is read with
        `polars`' default header handling, i.e. the first row is treated as
        the header.

        If `scan_all_sheets` is True and `column_aliases` is provided, every
        visible sheet is scanned instead and the one whose header matches the
        most canonical column names wins - this overrides `sheet_name`,
        `sheet_id`, and `use_first_visible` for sheet selection.

        Once a sheet's raw data is read, post-processing is applied in this
        order: `normalize_column_names`, then `column_aliases` standardization,
        then `schema_overrides`.

        Parameters
        ----------
        sheet_name : str | None, optional
            Name of the sheet to read. Cannot be combined with `sheet_id`, by default None
        sheet_id : int | None, optional
            The 1-based index of the worksheet to read. Cannot be combined with `sheet_name`, by default None
        use_first_visible : bool, optional
            If True and `sheet_name`/`sheet_id` are not provided, reads the first visible sheet in the workbook, by default False
        detect_header_opts : DetectHeaderOpts | None, optional
            Header detection options. If provided (and `header_row` is not), scans for the header row based on certain heuristics. See detect_header.py for more details, by default None
        header_row : int | None, optional
            0-based index of the header row. If provided, this takes priority over `detect_header_opts`, which is not called at all, by default None
        normalize_column_names : bool, optional
            If True, normalizes column names by stripping whitespaces, lower case, remove punctuation, etc. (see `rpakit.string.normalize_text`) before `column_aliases` matching is applied, by default False
        column_aliases : Mapping[str, str  |  Sequence[str]] | None, optional
            Mapping of canonical column names to their possible aliases. If provided, columns matching an alias are renamed to their canonical name via `standardize_columns`, by default None
        scan_all_sheets : bool, optional
            If True and `column_aliases` is provided, selects the visible sheet whose header matches the most canonical column names instead of a single named/indexed sheet. Has no effect if `column_aliases` is None, by default False
        drop_empty_rows : bool, optional
            Remove empty rows from the sheet, by default True
        drop_empty_cols : bool, optional
            Remove empty columns from the sheet, by default True
        schema_overrides : dict[str, pl.DataType] | None, optional
            Mapping of column names to the polars data type to cast them to, applied last via `safe_schema_override`, by default None

        Returns
        -------
        pl.DataFrame
            A polars DataFrame containing the data from the selected sheet.

        Raises
        ------
        ValueError
            If `sheet_name` and `sheet_id` are both provided.
        ValueError
            If `sheet_id` is 0 (indices are 1-based).
        """
        if sheet_name is not None and sheet_id is not None:
            raise ValueError(
                "sheet_name and sheet_idx cannot be specified at the same time."
            )
        if sheet_id == 0:
            raise ValueError("sheet_idx cannot be 0")

        if scan_all_sheets and column_aliases is not None:
            _, df = self._select_best_sheet(
                detect_header_opts=detect_header_opts,
                column_aliases=column_aliases,
                drop_empty_rows=drop_empty_rows,
                drop_empty_cols=drop_empty_cols,
            )
        else:
            if use_first_visible and sheet_name is None:
                sheet_name = self.visible_sheets[0].name

            header_row = self._resolve_header_row(
                sheet_name=sheet_name,
                sheet_id=sheet_id,
                detect_header_opts=detect_header_opts,
                header_row=header_row,
                column_aliases=column_aliases,
            )
            df = self._read_raw_sheet(
                sheet_name=sheet_name,
                sheet_id=sheet_id,
                header_row=header_row,
                drop_empty_rows=drop_empty_rows,
                drop_empty_cols=drop_empty_cols,
            )

        if normalize_column_names:
            df.columns = [_norm(c) for c in df.columns]

        if column_aliases is not None:
            df, _ = standardize_columns(df, column_aliases)

        if schema_overrides is not None:
            df = safe_schema_override(df, schema_overrides)

        return df
