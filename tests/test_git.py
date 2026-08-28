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


def test_remote_open_uses_complete_bare_clone(monkeypatch) -> None:
    from repo_riposte import git as git_module

    source = "git@example.com:owner/project.git"
    commands: list[list[str]] = []

    class FakeGitRepository:
        def __init__(self, cwd, source_label: str) -> None:
            self.cwd = cwd
            self.source_label = source_label

    def fake_run(command, **_kwargs):
        commands.append(command)
        return git_module.subprocess.CompletedProcess(
            command,
            0,
            stdout=b"",
            stderr=b"",
        )

    monkeypatch.setattr(git_module.shutil, "which", lambda _name: "/usr/bin/git")
    monkeypatch.setattr(git_module.subprocess, "run", fake_run)
    monkeypatch.setattr(git_module, "GitRepository", FakeGitRepository)

    with git_module.open_repository(source) as repository:
        target = repository.cwd

    assert commands == [
        [
            "git",
            "clone",
            "--bare",
            "--quiet",
            "--",
            source,
            str(target),
        ]
    ]
