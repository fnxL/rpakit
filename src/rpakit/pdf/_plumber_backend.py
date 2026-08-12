from collections.abc import Iterable

import pdfplumber

from rpakit.pdf._helpers import FileSource, _validate_page


class PlumberBackend:
    def __init__(
        self,
        source: FileSource,
        password: str | None = None,
    ):
        self.doc = pdfplumber.open(source, password=password)

    @property
    def page_count(self) -> int:
        return len(self.doc.pages)

    def close(self):
        pass

    def extract_tables(
        self,
        pages: Iterable[int],
        table_settings: dict[str, str | None] | None = None,
        region: tuple[float, float, float, float] | None = None,
    ) -> list[list[str]]:
        rows = []
        total_pages = self.page_count
        for page_num in pages:
            _validate_page(page_num, total_pages)
            target = self.doc.pages[page_num]
            if region:
                target = target.crop(region)

            for table in target.extract_tables(table_settings):
                for row in table:
                    cells = [(c or "").strip() for c in row]
                    rows.append(cells)
        return rows

    def extract_tables_all(
        self,
        table_settings: dict[str, str | None] | None = None,
        region: tuple[float, float, float, float] | None = None,
    ) -> list[list[str]]:

        rows: list[list[str]] = []
        for page in self.doc.pages:
            target = page
            if region:
                target = page.crop(region)

            for table in target.extract_tables(table_settings):
                for row in table:
                    cells = [(c or "").strip() for c in row]
                    rows.append(cells)
        return rows
