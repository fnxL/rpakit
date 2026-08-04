from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import TypeAlias

FileSource: TypeAlias = str | Path | BytesIO
