from io import BufferedReader, BytesIO

from python_calamine import CalamineWorkbook, SheetTypeEnum, SheetVisibleEnum

from rpakit.types import FileSource


def list_sheets(
    source: FileSource,
    *,
    skip_hidden: bool = False,
) -> list[str]:
    """
    List worksheet names in workbook order.

    Uses calamine's own workbook metadata, so checking sheet visibility needs
    no extra dependency. Chart/dialog/macro sheets are never included. Set
    `skip_hidden=True` to also drop sheets hidden in Excel.b

    Parameters
    ----------
    source : FileSource
        Path to file or file-like object.
    skip_hidden : bool, optional
        If True, exclude sheets hidden or very-hidden in Excel. Default False.

    Returns
    -------
    list[str]
        Worksheet names, in the order they appear in the workbook.
    """
    if isinstance(source, (BufferedReader, BytesIO)):
        source.seek(0)

    sheet_names: list[str] = []

    with CalamineWorkbook.from_object(source) as workbook:
        for meta in workbook.sheets_metadata:
            if meta.typ is not SheetTypeEnum.WorkSheet:
                continue

            if skip_hidden and meta.visible is not SheetVisibleEnum.Visible:
                continue

            sheet_names.append(meta.name)

    return sheet_names
