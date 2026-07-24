from __future__ import annotations

from pathlib import Path

import repo_riposte
from repo_riposte import _version

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_public_version_is_read_from_pyproject() -> None:
    expected = _version._read_pyproject_version(PROJECT_ROOT / "pyproject.toml")

    assert expected == "0.2.1"
    assert repo_riposte.__version__ == expected


def test_installed_metadata_is_the_wheel_fallback(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        _version,
        "_source_pyproject_path",
        lambda: tmp_path / "missing-pyproject.toml",
    )
    monkeypatch.setattr(_version, "distribution_version", lambda _name: "9.8.7")

    assert _version._resolve_version() == "9.8.7"


def test_missing_source_and_distribution_has_explicit_unknown_version(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        _version,
        "_source_pyproject_path",
        lambda: tmp_path / "missing-pyproject.toml",
    )

    def missing_distribution(_name: str) -> str:
        raise _version.PackageNotFoundError

    monkeypatch.setattr(_version, "distribution_version", missing_distribution)

    assert _version._resolve_version() == "0+unknown"
