from __future__ import annotations

from importlib.util import find_spec


class MissingDependencyError(ImportError):
    """Raised when an optional dependency required for a feature is not installed."""


def require_extra(extra: str, *module_names: str) -> None:
    """Import each of `module_names`, raising a single error naming `extra` if any are missing.

    Call this before importing optional third-party packages in a module so
    users get a `pip install "rpakit[extra]"` hint instead of a raw
    ModuleNotFoundError.
    """
    missing = [name for name in module_names if find_spec(name) is None]
    if not missing:
        return

    message = f"""rpakit's '{extra}' features require the following package(s), which are not installed: {", ".join(missing)}.
    Install them with:
        pip install "rpakit[{extra}]"

    or with uv:
        uv add "rpakit[{extra}]"
    """
    raise MissingDependencyError(message)
