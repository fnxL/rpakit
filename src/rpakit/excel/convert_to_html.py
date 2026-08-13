import re

from xlsx2html import xlsx2html

from rpakit.types import FileSource


def convert_to_html(source: FileSource):
    if hasattr(source, "seek"):
        source.seek(0)  # ty: ignore[call-non-callable]

    out_stream = xlsx2html(source)
    out_stream.seek(0)
    html_content = out_stream.read()

    # Extract only the table part of the HTML
    pattern = r"(<table.*?</table>)"
    match = re.search(pattern, html_content, re.DOTALL | re.MULTILINE)
    if match:
        return match.group(1) + "<br><br>"

    return None
