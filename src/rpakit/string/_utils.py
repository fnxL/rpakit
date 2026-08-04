import re
from re import Pattern


def normalize_text(
    text: object,
    lowercase: bool = True,
    substitute: str = " ",
    pattern: Pattern[str] = re.compile(r"[^a-zA-Z0-9]+"),
) -> str:
    """Normalize a string by collapsing non-alphanumeric runs and casing.

    Any run of characters matching ``pattern`` (by default, anything that
    isn't an ASCII letter or digit) is replaced with ``substitute``, and
    leading/trailing whitespace is stripped before and after substitution.
    Non-string input is treated as empty.

    Parameters
    ----------
    text : str
        The text to normalize. If not a string, an empty string is returned.
    lowercase : bool, optional
        Whether to lowercase `text` before normalizing, by default True.
    substitute : str, optional
        The replacement string for each run of characters matching
        `pattern`, by default " ".
    pattern : Pattern[str], optional
        The compiled regex pattern whose matches are replaced by
        `substitute`, by default re.compile(r"[^a-zA-Z0-9]+").

    Returns
    -------
    str
        The normalized string, or "" if `text` is not a string.

    Examples
    --------
    >>> normalize_text("  Hello,   World!  ")
    'hello world'
    >>> normalize_text("Foo_Bar-Baz", substitute="_")
    'foo_bar_baz'
    """
    if not isinstance(text, str):
        return ""

    if lowercase:
        text = text.lower()

    return pattern.sub(substitute, text.strip()).strip()
