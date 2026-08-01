"""Helpers for reporting missing optional dependencies with an actionable message."""

from __future__ import annotations

import importlib.util


class MissingDependencyError(ImportError):
    """Raised when an optional dependency required for a feature is not installed."""


def require_extra(extra: str, *module_names: str) -> None:
    """Import each of `module_names`, raising a single error naming `extra` if any are missing.

    Call this before importing optional third-party packages in a module so
    users get a `pip install "rpakit[extra]"` hint instead of a raw
    ModuleNotFoundError.
    """
    missing = [name for name in module_names if importlib.util.find_spec(name) is None]
    if not missing:
        return

    raise MissingDependencyError(
        f"rpakit's '{extra}' features require the following package(s), "
        f"which are not installed: {', '.join(missing)}.\n\n"
        f"Install them with:\n"
        f'    pip install "rpakit[{extra}]"\n\n'
        f"or with uv:\n"
        f'    uv add "rpakit[{extra}]"'
    )
