import re
import unicodedata
from re import Pattern

_DEFAULT_PATTERN = re.compile(r"[^a-zA-Z0-9\s]")
_WHITESPACE_RUN = re.compile(r"\s+")


def normalize_text(
    text: object,
    pattern: Pattern[str] | str = _DEFAULT_PATTERN,
    separator: str | None = None,
    lowercase: bool = True,
    convert_accents_to_ascii: bool = True,
    collapse_spaces: bool = True,
) -> str:
    """Normalize a string by removing unwanted characters and casing.

    Characters matching ``pattern`` (by default, anything that isn't an
    ASCII letter, digit, or whitespace) are deleted from `text`. Non-string,
    non-int input is treated as empty; ``int`` values are stringified first.

    Parameters
    ----------
    text : object
        The text to normalize. ``int`` values are converted with ``str()``
        before normalizing; any other non-string value returns "".
    pattern : Pattern[str] | str, optional
        Regex whose matches are removed from `text`, by default anything
        that isn't an ASCII letter, digit, or whitespace
        (``r"[^a-zA-Z0-9\\s]"``).
    separator : str | None, optional
        If given, replaces whitespace in the result with this string, by
        default None (whitespace is left as single spaces).
    lowercase : bool, optional
        Whether to lowercase `text` before normalizing, by default True.
    convert_accents_to_ascii : bool, optional
        Whether to fold accented characters down to their closest ASCII
        equivalent (e.g. "café" -> "cafe"), by default True.
    collapse_spaces : bool, optional
        Whether to collapse runs of whitespace into a single space, by
        default True. This runs *after* `pattern` is removed, so characters
        deleted from between words (e.g. the "-" in "Foo - Bar") don't leave
        double spaces behind.

    Returns
    -------
    str
        The normalized string, or "" if `text` is not a string or int.

    Examples
    --------
    >>> normalize_text("  Hello,   World!  ")
    'hello world'
    >>> normalize_text("Foo - Bar", separator="_")
    'foo_bar'
    >>> normalize_text("Café Münchën")
    'cafe munchen'
    """
    if isinstance(text, int):
        text = str(text)
    elif not isinstance(text, str):
        return ""

    if lowercase:
        text = text.lower()

    if convert_accents_to_ascii:
        text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()

    if not isinstance(pattern, Pattern):
        pattern = re.compile(pattern)

    text = pattern.sub("", text)
    text = _WHITESPACE_RUN.sub(" ", text).strip() if collapse_spaces else text.strip()

    if separator is not None:
        text = text.replace(" ", separator)

    return text
