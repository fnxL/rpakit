"""PDFParser — read text, text blocks, and tables out of a PDF via pdf_oxide,
with pdfplumber opened alongside for table extraction.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Final, Literal, Self, TypeAlias, get_args

from rpakit._optional import require_extra
from rpakit.pdf._helpers import (
    FileSource,
    _check_backend,
    _normalize_pages,
)
from rpakit.pdf._oxide_backend import OxideBackend
from rpakit.pdf._plumber_backend import PlumberBackend

require_extra("pdf", "pdfplumber", "pdf_oxide")

TextBackend: TypeAlias = Literal["pdfoxide"]
TablesBackend: TypeAlias = Literal["pdfplumber", "pdfoxide"]

_TEXT_BACKENDS: Final = get_args(TextBackend)
_TABLES_BACKENDS: Final = get_args(TablesBackend)

# Splits a rendered text line into table cells on column gutters (2+ spaces).
_TABLE_GUTTER_RE: Final = re.compile(r"\s{2,}")


class PdfParser:
    """Extracts text,text blocks, pdfs from a PDF."""

    def __init__(
        self,
        source: FileSource,
        password: str | None = None,
    ):
        self._source = source
        self._password = password
        self._oxide_backend: OxideBackend
        self._plumber_backend: PlumberBackend
        self.open()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.close()

    def open(self) -> None:
        self._oxide_backend = OxideBackend(self._source, self._password)
        self._plumber_backend = PlumberBackend(self._source, self._password)

    def close(self) -> None:
        self._oxide_backend.close()
        self._plumber_backend.close()

    @property
    def page_count(self) -> int:
        return int(self._oxide_backend.page_count)

    def extract_text(
        self,
        page: Iterable[int] | int = 0,
        layout: bool = True,
        backend: TextBackend = "pdfoxide",
    ) -> str:

        _check_backend(backend, _TEXT_BACKENDS)
        pages = _normalize_pages(page)

        if backend == "pdfoxide":
            return self._oxide_backend.extract_text(
                pages=pages,
                layout=layout,
            )

    def extract_text_all(
        self,
        layout: bool = True,
        backend: TextBackend = "pdfoxide",
    ) -> str:
        _check_backend(backend, _TEXT_BACKENDS)
        if backend == "pdfoxide":
            return self._oxide_backend.extract_text_all(layout=layout)

    def extract_text_lines(self) -> list[str]:
        return self.extract_text_all().splitlines()

    def extract_blocks(
        self,
        backend: TextBackend = "pdfoxide",
    ) -> list[str]:
        _check_backend(backend, _TEXT_BACKENDS)
        if backend == "pdfoxide":
            return self._oxide_backend.extract_blocks()

    # -- tables ------------------------------------------------------------
    def extract_tables(
        self,
        page: Iterable[int] | int = 0,
        table_settings: dict[str, str | None] | None = None,
        region: tuple[float, float, float, float] | None = None,
        backend: TablesBackend = "pdfplumber",
    ):
        _check_backend(backend, _TABLES_BACKENDS)
        pages = _normalize_pages(page)

        if backend == "pdfplumber":
            return self._plumber_backend.extract_tables(
                pages=pages,
                table_settings=table_settings,
                region=region,
            )

    def extract_tables_all(
        self,
        table_settings: dict[str, str | None] | None = None,
        region: tuple[float, float, float, float] | None = None,
        backend: TablesBackend = "pdfplumber",
    ) -> list[list[str]]:
        _check_backend(backend, _TABLES_BACKENDS)
        if backend == "pdfplumber":
            return self._plumber_backend.extract_tables_all(
                table_settings=table_settings, region=region
            )
        return [[]]
