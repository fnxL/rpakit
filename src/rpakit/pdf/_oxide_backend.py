from collections.abc import Iterable
from pathlib import Path
from typing import cast

from pdf_oxide import PdfDocument
from pdf_oxide.pdf_oxide import Page

from rpakit.pdf._helpers import FileSource
from rpakit.pdf._oxide_layout import render_page


class OxideBackend:
    def __init__(
        self,
        source: FileSource,
        password: str | None = None,
    ):
        if isinstance(source, str | Path):
            self.doc = PdfDocument(source, password=password)
        else:
            self.doc = PdfDocument.from_bytes(
                source.read(),
                password=password,
            )

    @property
    def page_count(self):
        return self.doc.page_count

    def close(self):
        pass

    def extract_text(
        self,
        pages: Iterable[int],
        layout: bool = True,
    ) -> str:
        parts: list[str] = []
        for page_num in pages:
            spans = self.doc.extract_spans(page_num)
            if layout:
                parts.append(render_page(spans))
            else:
                parts.extend(span.text for span in spans)
        return "\n".join(parts)

    def extract_text_all(self, layout: bool = True):
        # return "\n".join(render_page(cast(Page, page).spans) for page in self.doc.pages)
        return (
            "\n".join(render_page(cast(Page, page).spans) for page in self.doc.pages)
            if layout
            else "\n".join(
                span.text for page in self.doc.pages for span in cast(Page, page).spans
            )
        )

    def extract_blocks(self):
        return [span.text for page in self.doc.pages for span in cast(Page, page).spans]
