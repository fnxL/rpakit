from __future__ import annotations

from dataclasses import dataclass
from io import BufferedReader, BytesIO

from python_calamine import CalamineWorkbook, SheetTypeEnum, SheetVisibleEnum

from rpakit.types import FileSource


@dataclass(frozen=True, slots=True)
class SheetMetadata:
    """Metadata describing a worksheet in an Excel workbook."""

    name: str
    index: int
    is_hidden: bool


def list_sheets(
    source: FileSource,
    *,
    skip_hidden: bool = False,
) -> list[SheetMetadata]:
    """
    List the worksheets contained in an Excel workbook.

    Only worksheets are included in the result; other sheet types supported
    by the workbook are ignored. The returned worksheets preserve their
    original workbook order.


    Parameters
    ----------
    source : FileSource
        Excel workbook source. This can be a file path or a supported
        file-like object.
    skip_hidden : bool, optional, default=False
        If True, hidden sheets are not included in the result, by default False.

    Returns
    -------
    list[SheetMetadata]
        A list containing metadata for each worksheet. Each entry contains:

        - ``name``: Worksheet name.
        - ``index``: Zero-based worksheet index in the workbook.
        - ``is_hidden``: Whether the worksheet is hidden.

        If ``skip_hidden=True``, hidden worksheets are omitted.

    Notes
    -----
    If ``source`` is a ``BufferedReader`` or ``BytesIO`` object, its position
    is reset to the beginning before the workbook is opened.
    """
    if isinstance(source, (BufferedReader, BytesIO)):
        source.seek(0)

    sheets: list[SheetMetadata] = []

    with CalamineWorkbook.from_object(source) as workbook:
        for index, meta in enumerate(workbook.sheets_metadata):
            if meta.typ is not SheetTypeEnum.WorkSheet:
                continue

            is_hidden = meta.visible is not SheetVisibleEnum.Visible
            if skip_hidden and is_hidden:
                continue

            sheets.append(
                SheetMetadata(
                    name=meta.name,
                    index=index,
                    is_hidden=is_hidden,
                )
            )

    return sheets
