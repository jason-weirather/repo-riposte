from __future__ import annotations

import pytest

from repo_riposte.git import _repository_name_from_location


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "https://github.com/jason-weirather/repo-riposte.git",
            "repo-riposte",
        ),
        (
            "git@github.com:jason-weirather/repo-riposte.git",
            "repo-riposte",
        ),
        (
            "ssh://git@github.com/jason-weirather/repo-riposte.git",
            "repo-riposte",
        ),
    ],
)
def test_repository_name_is_consistent_across_remote_url_styles(
    source: str,
    expected: str,
) -> None:
    assert _repository_name_from_location(source) == expected
