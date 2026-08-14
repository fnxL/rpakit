# rpakit

A Python toolkit for Robotic Process Automation (RPA) and ETL pipelines, providing
solutions to common automation challenges: reading messy Excel workbooks, extracting
text/tables from PDFs, cleaning up `polars` DataFrames, and general string utilities.

## Installation

```bash
pip install rpakit
```

```bash
uv add rpakit
```

`rpakit` works out of the box for Excel and DataFrame utilities. PDF support is an
optional extra (it pulls in `pdfplumber`, `pdf-oxide`, and `pypdf`):

```bash
pip install "rpakit[pdf]"
# or
uv add "rpakit[pdf]"
```

If you try to use `rpakit.pdf` without the extra installed, you'll get a
`MissingDependencyError` telling you exactly what to install.

Requires Python 3.11+.

## Modules

| Module | What it's for |
| --- | --- |
| [`rpakit.excel`](#rpakitexcel) | Reading Excel workbooks into `polars` DataFrames, detecting header rows, listing sheets |
| [`rpakit.pdf`](#rpakitpdf) | Extracting text and tables from PDFs |
| [`rpakit.df`](#rpakitdf) | Cleaning up/validating `polars` DataFrames (column standardization, schema casting) |
| [`rpakit.string`](#rpakitstring) | Text normalization and random string generation |
| [`rpakit.types`](#rpakittypes) | Shared type aliases |

---

## `rpakit.excel`

Utilities for reading Excel workbooks (`.xlsx`, `.xlsm`, `.xls`, etc.) into
[`polars`](https://pola.rs) DataFrames, built on top of
[`python-calamine`](https://github.com/dimastbk/python-calamine) for fast, dependency-light
parsing.

Everything in this module accepts a `FileSource`, which is a path (`str` / `pathlib.Path`)
or an in-memory `io.BytesIO`/file-like object.

### `ExcelReader`

```python
from rpakit.excel.excel_reader import ExcelReader

reader = ExcelReader("report.xlsx")

reader.sheets  # -> list[SheetMetadata] for every sheet (incl. hidden)
reader.visible_sheets  # -> list[SheetMetadata] excluding hidden sheets

df = reader.read_sheet()
```

`ExcelReader` opens the workbook once and lets you read one or more sheets into
`polars.DataFrame`s via `read_sheet()`, with optional header detection and column
standardization built in.

#### `read_sheet(...)`

```python
df = reader.read_sheet(
    sheet_name=None,  # str | None — sheet to read by name
    sheet_id=None,  # int | None — 1-based sheet position (can't combine with sheet_name)
    use_first_visible=False,  # read the first non-hidden sheet if neither of the above is given
    detect_header_opts=None,  # DetectHeaderOpts — heuristically find the header row (see detect_header below)
    header_row=None,  # int | None — explicit 0-based header row; overrides detect_header_opts entirely
    normalize_column_names=False,  # lowercase/strip/underscore-ify column names before alias matching
    column_aliases=None,  # Mapping[str, str | Sequence[str]] — rename matched columns to canonical names
    scan_all_sheets=False,  # with column_aliases, pick whichever visible sheet matches the most canonical columns
    drop_empty_rows=True,
    drop_empty_cols=True,
    schema_overrides=None,  # dict[str, pl.DataType] — cast columns after everything else
)
```

Processing order once the raw sheet is read: `normalize_column_names` → `column_aliases`
standardization → `schema_overrides`.

**Reading a specific sheet:**

```python
df = reader.read_sheet(sheet_name="Purchase Orders")
# or by 1-based position
df = reader.read_sheet(sheet_id=2)
```

**Auto-detecting the header row** (useful for exports with title banners, "Generated on"
lines, blank spacer rows, etc. above the real header):

```python
df = reader.read_sheet(
    detect_header_opts={
        "max_scan_rows": 100,
        "expected_headers": ["po number", "quantity"],
    },
)
```

**Renaming messy headers to canonical names**, e.g. turning `"PO#"` / `"po no."` /
`"Purchase Order"` into a single `po_number` column:

```python
column_aliases = {
    "po_number": ["po#", "po no.", "purchase order"],
    "quantity": ["ord qty", "qty", "order quantity"],
}
df = reader.read_sheet(column_aliases=column_aliases)
```

**Scanning every sheet** and picking whichever one's header actually matches your expected
columns (handy when you don't know in advance which sheet — "Data", "Sheet1", "Export"... —
holds the real data):

```python
df = reader.read_sheet(column_aliases=column_aliases, scan_all_sheets=True)
```

**Casting columns after reading:**

```python
import polars as pl

df = reader.read_sheet(schema_overrides={"quantity": pl.Int64, "amount": pl.Float64})
```

> **Note:** `schema_overrides` matches column names case insensitively.

### `detect_header`

```python
from rpakit.excel import detect_header

row_idx: int = detect_header(
    source,  # FileSource | CalamineWorkbook
    sheet_id=None,  # 1-based sheet position
    sheet_name=None,  # sheet name — takes precedence over sheet_id; can't combine both
    max_scan_rows=100,  # how many leading rows to scan
    weights=DEFAULT_WEIGHTS,  # HeaderWeights — tune the scoring heuristic
    expected_headers=None,  # Sequence[str] — labels expected in the header row
    column_aliases=None,  # Mapping[str, Sequence[str]] — canonical -> alias spellings
)
```

Scans up to `max_scan_rows` rows and scores each one on how "header-like" it looks:

- **density** — share of non-empty cells
- **uniqueness** — share of non-empty cells with distinct values
- **string_ratio** — share of non-empty cells that are text
- **data_contrast** — how much more text-like this row is than the row below it (a header
  sitting above numeric/date data)
- **density_jump** — how much denser this row is than the row above it (a header sitting
  below a title/blank row)

The row with the highest weighted score wins. Rows that are partial/full repeats of the row
directly below them (as happens when a vertically-merged header cell gets unmerged into
duplicate values down every row of the merge) are never picked over the real, data-aligned
row.

```python
row_idx = detect_header("report.xlsx")
```

**Boosting detection with known column names.** `expected_headers` and `column_aliases` are
one-shot signals — if a row matches them, it wins outright over the base heuristic.
`column_aliases` takes precedence if both are given:

```python
row_idx = detect_header(
    "report.xlsx", expected_headers=["po number", "quantity", "ship date"]
)

row_idx = detect_header(
    "report.xlsx",
    column_aliases={
        "po_number": ["po#", "purchase order"],
        "quantity": ["qty", "ord qty"],
    },
)
```

**Tuning the scoring weights:**

```python
from rpakit.excel.detect_header import HeaderWeights

weights = HeaderWeights(
    density=0.4, uniqueness=0.3, string_ratio=0.2, data_contrast=0.1, density_jump=0.0
)
row_idx = detect_header("report.xlsx", weights=weights)
```

### `list_sheets`

```python
from rpakit.excel import list_sheets

sheets = list_sheets("report.xlsx", skip_hidden=False)
# -> [SheetMetadata(name="Data", index=0, is_hidden=False), ...]
```

Returns a `SheetMetadata` (a frozen dataclass with `name`, `index`, `is_hidden`) for every
*worksheet* in the workbook (other sheet types, e.g. chart sheets, are ignored), in original
workbook order. Pass `skip_hidden=True` to omit hidden sheets.

### `convert_to_html`

Converts a single-sheet `.xlsx` file into an HTML `<table>` string (via `xlsx2html`),
preserving styling — handy for embedding a spreadsheet preview in an email or report.

```python
from rpakit.excel.convert_to_html import convert_to_html

html = convert_to_html("report.xlsx")  # -> str | None
```

Accepts a `FileSource`. Returns `None` if no `<table>` could be extracted from the
converted output.

---

## `rpakit.pdf`

Text and table extraction from PDFs, via [`PdfParser`](#pdfparser). Requires the `pdf`
extra:

```bash
pip install "rpakit[pdf]"
```

Text extraction is powered by [`pdf-oxide`](https://pypi.org/project/pdf-oxide/) (fast,
Rust-backed, with a layout-preserving renderer). Table extraction is powered by
[`pdfplumber`](https://github.com/jsvine/pdfplumber).

### `PdfParser`

```python
from rpakit.pdf import PdfParser

with PdfParser("invoice.pdf", password=None) as parser:
    parser.page_count  # -> int

    text = parser.extract_text_all()  # whole document, layout-preserving
    text = parser.extract_text(page=0)  # a single page
    text = parser.extract_text(page=[0, 1, 2])  # several pages

    lines = parser.extract_text_lines()  # extract_text_all(), split into lines
    blocks = parser.extract_blocks()  # raw text spans, no layout reconstruction

    tables = parser.extract_tables_all()  # every table on every page
    tables = parser.extract_tables(page=0)  # tables on one page
```

`PdfParser` opens both backends up front (`open()`) and closes them on `__exit__`/`close()`,
so use it as a context manager (or call `.close()` yourself when you're done). Pages are
0-indexed throughout.

#### Text extraction

```python
parser.extract_text(page=0, layout=True, backend="pdfoxide") -> str
parser.extract_text_all(layout=True, backend="pdfoxide") -> str
parser.extract_text_lines() -> list[str]
parser.extract_blocks(backend="pdfoxide") -> list[str]
```

- `page` accepts a single page number or an iterable of page numbers.
- `layout=True` (default) reconstructs the page's visual layout (columns, spacing) as plain
  text — good for tabular/form-like PDFs. `layout=False` just concatenates each text span in
  reading order, which is faster and better for prose.
- `extract_blocks()` returns the raw list of text spans as extracted from the page, with no
  layout reconstruction at all.

#### Table extraction

```python
parser.extract_tables(
    page=0,
    table_settings=None,                 # pdfplumber table-detection settings, e.g. {"vertical_strategy": "text"}
    region=None,                          # (x0, top, x1, bottom) crop box, in PDF points
    backend="pdfplumber",
) -> list[list[str]]

parser.extract_tables_all(table_settings=None, region=None, backend="pdfplumber") -> list[list[str]]
```

Both return a flat list of rows (each row a `list[str]`) across every table found on the
requested page(s) — tables aren't kept separate from one another. `table_settings` is passed
straight through to `pdfplumber`'s `Page.extract_tables()`; see the
[pdfplumber docs](https://github.com/jsvine/pdfplumber#extracting-tables) for the available
strategies. `region` crops each page to a bounding box before extracting, which helps when a
table sits in a known, fixed location on every page.

```python
# Only extract from the top-left quadrant of every page:
rows = parser.extract_tables_all(region=(0, 0, 300, 400))
```

---

## `rpakit.df`

Small `polars`-DataFrame utilities for cleaning up and validating tabular data, typically
used after reading a sheet with [`rpakit.excel`](#rpakitexcel).

### `standardize_columns`

Renames a DataFrame's columns to canonical names based on a mapping of canonical name to
possible aliases, matching case- and punctuation-insensitively.

```python
from rpakit.df import standardize_columns

column_aliases = {
    "full_name": ["name"],
    "years_old": ["age"],
}

df, restore_map = standardize_columns(df, column_aliases)
# df.columns -> [..., "full_name", "years_old", ...]
# restore_map -> {"full_name": "name", "years_old": "age"} (canonical -> original name)
```

Columns with no matching alias are left unchanged. Aliases may be given as a single string
or a list of strings. Raises `ValueError` if the same alias is declared for two different
canonical names, or if more than one column in the DataFrame would map to the same canonical
name. The returned `restore_map` lets you rename the columns back to their original names
later if needed.

### `normalize_columns`

Normalizes every column name in a DataFrame: lowercased, punctuation/brackets stripped,
whitespace collapsed and replaced with underscores (via
[`rpakit.string.normalize_text`](#rpakitstring)).

```python
from rpakit.df import normalize_columns

df.columns  # -> ["Foo Bar", "Baz-Qux"]
df = normalize_columns(df)
df.columns  # -> ["foo_bar", "baz_qux"]
```

> **Note:** this mutates `df.columns` in place; the returned DataFrame is the same object,
> returned for convenient chaining.

### `require_columns`

Raises `ValueError` if any of the given columns are missing from the DataFrame — useful as
a guard clause right after reading a sheet, so a downstream `KeyError` becomes an immediate,
readable error instead.

```python
from rpakit.df import require_columns

require_columns(df, ["po_number", "quantity", "ship_date"])
# raises ValueError("Missing required columns: ship_date...") if it's absent
```

### `safe_schema_override`

```python
from rpakit.df import safe_schema_override
import polars as pl

df = safe_schema_override(
    df, {"quantity": pl.Int64, "amount": pl.Float64}, strict=False
)
```

Casts the given columns to the specified `polars` dtypes. Returns `df` unchanged if
`schema_overrides` is empty. Column names in `schema_overrides` are matched case-insensitively with the df column names. Extra column names are ignored.

---

## `rpakit.string`

General-purpose text utilities used throughout the rest of the library (e.g. by
`rpakit.df` and `rpakit.excel` for case/punctuation-insensitive matching).

### `normalize_text`

```python
from rpakit.string import normalize_text

normalize_text("  Hello,   World!  ")  # -> "hello world"
normalize_text("Foo - Bar", separator="_")  # -> "foo_bar"
normalize_text("Café Münchën")  # -> "cafe munchen"
```

```python
normalize_text(
    text,                            # str | int — non-str/int input returns ""
    pattern=r"[^a-zA-Z0-9\_\s]",     # regex (str or compiled) of characters to strip
    separator=None,                  # if given, replaces whitespace in the result with this string
    lowercase=True,
    convert_accents_to_ascii=True,   # fold accented characters to their closest ASCII equivalent
    collapse_spaces=True,            # collapse runs of whitespace into a single space
) -> str
```

`int` values are stringified before normalizing; any other non-string input returns `""`.
Whitespace collapsing runs *after* the pattern is stripped, so removing a character like the
`-` in `"Foo - Bar"` doesn't leave a double space behind.

```python
normalize_text("abc123def", pattern=r"[0-9]")  # -> "abcdef"
normalize_text(
    "Foo   Bar", collapse_spaces=False
)  # -> "foo   bar"... actually collapses leading/trailing only when False
```

### `random_string`

```python
from rpakit.string import random_string

random_string()  # 12-char random string, letters + digits
random_string(length=10, characters="abcdefghijklmnopqrstuvwxyz")
```

Generates a cryptographically secure random string (via Python's `secrets` module) of the
given `length`, drawn from `characters` (default: ASCII letters + digits).

---

## `rpakit.types`

Shared type aliases used across the library's public APIs.

```python
from rpakit.types import FileSource
# FileSource = str | Path | BytesIO
```

`FileSource` is the accepted input type for anything that reads a file (Excel workbooks,
PDFs): a file path (`str` or `pathlib.Path`), or an in-memory `io.BytesIO` object.
`rpakit.pdf` additionally accepts `io.BufferedReader` (i.e. a regular open file handle)
wherever `FileSource` is expected.

---

## Optional extras

| Extra | Installs | Enables |
| --- | --- | --- |
| `pdf` | `pdf-oxide`, `pdfplumber`, `pypdf` | `rpakit.pdf` |
| `windows` | *(reserved)* | Windows-specific automation helpers |
| `filesystem` | *(reserved)* | Filesystem automation helpers |

Install multiple extras together:

```bash
pip install "rpakit[pdf,windows,filesystem]"
```

If an extra isn't installed, importing the module that needs it raises a
`rpakit._optional.MissingDependencyError` with the exact `pip`/`uv` command to fix it.

## License

Apache-2.0. See [LICENSE](LICENSE).
