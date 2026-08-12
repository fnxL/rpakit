from collections.abc import Iterable
from io import BufferedReader
from typing import TypeAlias

from rpakit.types import FileSource as _BaseFileSource

FileSource: TypeAlias = _BaseFileSource | BufferedReader


def _check_backend(backend: str, allowed: tuple[str, ...]) -> None:
    if backend not in allowed:
        raise ValueError(
            f"Invalid backend: {backend!r}. Supported backends: {', '.join(allowed)}"
        )


def _normalize_pages(page: Iterable[int] | int) -> list[int]:
    if isinstance(page, int):
        return [page]
    if isinstance(page, Iterable):
        return list(page)

    raise TypeError(f"Invalid type for pages: {type(page).__name__}")


def _validate_page(page_num: int, total_pages: int) -> None:
    if not (0 <= page_num < total_pages):
        raise ValueError(
            f"Invalid page number: {page_num}. Must be between 0 and {total_pages - 1}."
        )
