"""Package and snapshot-format metadata.

Keep this in a real submodule so the CLI does not depend on attributes being
present on the package root. That makes editable installs more resilient when
an old or incomplete checkout was previously installed as a namespace package.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

DISTRIBUTION_NAME = "repo-riposte"
FALLBACK_VERSION = "0.2.0"
SNAPSHOT_FORMAT_VERSION = "1"

try:
    __version__ = version(DISTRIBUTION_NAME)
except PackageNotFoundError:  # Running directly from an uninstalled source tree.
    __version__ = FALLBACK_VERSION

__all__ = ["SNAPSHOT_FORMAT_VERSION", "__version__"]
