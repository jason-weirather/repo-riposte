"""Resolve the package version from the project's authoritative metadata.

During source-tree and editable-install development, read ``[project].version``
directly from the repository's ``pyproject.toml``. Built wheels do not normally
contain that root build file, so installed distributions fall back to the core
metadata generated from the same value during the build.
"""

from __future__ import annotations

import re
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10.
    import tomli as tomllib

DISTRIBUTION_NAME = "repo-riposte"
UNKNOWN_VERSION = "0+unknown"


def _source_pyproject_path() -> Path:
    """Return the expected pyproject.toml path for this src-layout checkout."""
    return Path(__file__).resolve().parents[2] / "pyproject.toml"


def _normalized_name(value: str) -> str:
    """Normalize a distribution name using the packaging-name convention."""
    return re.sub(r"[-_.]+", "-", value).casefold()


def _read_pyproject_version(path: Path) -> str | None:
    """Read this distribution's static version from *path*, if applicable.

    ``None`` means the path is absent or belongs to another project. A present
    repo-riposte pyproject with malformed or missing version metadata is an
    error rather than an invitation to silently report stale metadata.
    """
    if not path.is_file():
        return None

    with path.open("rb") as handle:
        document: dict[str, Any] = tomllib.load(handle)

    project = document.get("project")
    if not isinstance(project, dict):
        return None

    project_name = project.get("name")
    if not isinstance(project_name, str):
        return None
    if _normalized_name(project_name) != _normalized_name(DISTRIBUTION_NAME):
        return None

    project_version = project.get("version")
    if not isinstance(project_version, str) or not project_version.strip():
        raise RuntimeError(
            f"{path} must define a non-empty static [project].version value."
        )
    return project_version.strip()


def _resolve_version() -> str:
    """Resolve the source version first, then installed distribution metadata."""
    source_version = _read_pyproject_version(_source_pyproject_path())
    if source_version is not None:
        return source_version

    try:
        return distribution_version(DISTRIBUTION_NAME)
    except PackageNotFoundError:
        return UNKNOWN_VERSION


__version__ = _resolve_version()

__all__ = ["__version__"]
