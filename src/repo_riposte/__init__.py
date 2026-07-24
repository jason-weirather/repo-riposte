"""Turn a Git commit into a single Markdown repository snapshot."""

from __future__ import annotations

from repo_riposte._meta import SNAPSHOT_FORMAT_VERSION
from repo_riposte._version import __version__

__all__ = ["SNAPSHOT_FORMAT_VERSION", "__version__"]
