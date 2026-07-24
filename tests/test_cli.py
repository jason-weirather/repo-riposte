from __future__ import annotations

import subprocess
from pathlib import Path

from click.testing import CliRunner

from repo_riposte.cli import main


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(repo: Path) -> None:
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")


def _commit_all(repo: Path, message: str = "initial") -> str:
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", message)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def test_cli_renders_exact_commit_and_reports_omissions(tmp_path: Path) -> None:
    repo = tmp_path / "demo"
    _init_repo(repo)

    (repo / "src").mkdir()
    (repo / "README.md").write_text(
        "# Demo\n\nA nested fence:\n\n```python\nprint('hello')\n```\n",
        encoding="utf-8",
    )
    (repo / "src" / "app.py").write_text("print('from commit')\n", encoding="utf-8")
    (repo / "image.bin").write_bytes(b"abc\x00def")
    committed_sha = _commit_all(repo)
    branch = _git(repo, "branch", "--show-current").stdout.strip()

    # This working-tree edit must not leak into the snapshot.
    (repo / "src" / "app.py").write_text("print('uncommitted')\n", encoding="utf-8")

    result = CliRunner().invoke(
        main,
        [
            str(repo),
            "--branch",
            branch,
            "--commit",
            committed_sha,
            "--output",
            "-",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "README.md" in result.output
    assert result.output.index("### `README.md`") < result.output.index("### `src/app.py`")
    assert "print('from commit')" in result.output
    assert "print('uncommitted')" not in result.output
    assert "binary content (NUL byte detected)" in result.output
    assert "````markdown" in result.output


def test_default_output_uses_top_level_name_and_seven_character_sha(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "demo-project"
    _init_repo(repo)
    _git(repo, "config", "core.abbrev", "12")

    (repo / "src").mkdir()
    (repo / "README.md").write_text("# Demo project\n", encoding="utf-8")
    (repo / "src" / "app.py").write_text("print('demo')\n", encoding="utf-8")
    sha = _commit_all(repo)

    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(main, [str(repo / "src")])

    expected = tmp_path / f"demo-project-{sha[:7]}.md"
    assert result.exit_code == 0, result.output
    assert expected.is_file()
    assert "# Repository snapshot: `demo-project`" in expected.read_text(encoding="utf-8")
    assert expected.name in result.output


def test_ssh_origin_name_drives_default_output(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "checkout"
    _init_repo(repo)
    (repo / "README.md").write_text("# Remote-named repository\n", encoding="utf-8")
    sha = _commit_all(repo)
    _git(
        repo,
        "remote",
        "add",
        "origin",
        "git@github.com:jason-weirather/repo-riposte.git",
    )

    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(main, [str(repo)])

    expected = tmp_path / f"repo-riposte-{sha[:7]}.md"
    assert result.exit_code == 0, result.output
    assert expected.is_file()
    assert "# Repository snapshot: `repo-riposte`" in expected.read_text(encoding="utf-8")


def test_custom_output_path_is_honored(tmp_path: Path) -> None:
    repo = tmp_path / "custom-output"
    _init_repo(repo)
    (repo / "README.md").write_text("# Custom output\n", encoding="utf-8")
    _commit_all(repo)

    destination = tmp_path / "nested" / "anything-you-like.md"
    result = CliRunner().invoke(main, [str(repo), "--output", str(destination)])

    assert result.exit_code == 0, result.output
    assert destination.is_file()
    assert "# Repository snapshot:" in destination.read_text(encoding="utf-8")


def test_sensitive_files_are_omitted_but_env_example_is_included(tmp_path: Path) -> None:
    repo = tmp_path / "sensitive-demo"
    _init_repo(repo)
    (repo / "certs").mkdir()
    (repo / "keys").mkdir()

    (repo / "README.md").write_text("# Sensitive demo\n", encoding="utf-8")
    (repo / ".env").write_text("ROOT_SECRET=do-not-render\n", encoding="utf-8")
    (repo / ".env.production").write_text(
        "PROD_SECRET=also-do-not-render\n", encoding="utf-8"
    )
    (repo / ".env.example").write_text("API_TOKEN=replace-me\n", encoding="utf-8")
    (repo / "certs" / "server.pem").write_text(
        "PEM_SECRET=do-not-render\n", encoding="utf-8"
    )
    (repo / "keys" / "private.key").write_text(
        "KEY_SECRET=do-not-render\n", encoding="utf-8"
    )
    _commit_all(repo)

    result = CliRunner().invoke(main, [str(repo), "--output", "-"])

    assert result.exit_code == 0, result.output
    assert "API_TOKEN=replace-me" in result.output
    assert "ROOT_SECRET=do-not-render" not in result.output
    assert "PROD_SECRET=also-do-not-render" not in result.output
    assert "PEM_SECRET=do-not-render" not in result.output
    assert "KEY_SECRET=do-not-render" not in result.output
    assert "excluded by default sensitive-file policy" in result.output
    assert ".env-style file; .env.example is allowed" in result.output
    assert "omitted before their blobs were read" in result.output
    assert "`certs/server.pem`" in result.output
    assert "`keys/private.key`" in result.output


def test_sensitive_files_can_be_included_explicitly(tmp_path: Path) -> None:
    repo = tmp_path / "sensitive-override"
    _init_repo(repo)
    (repo / "README.md").write_text("# Override\n", encoding="utf-8")
    (repo / ".env").write_text("EXPLICIT_ENV=visible\n", encoding="utf-8")
    (repo / "private.key").write_text("EXPLICIT_KEY=visible\n", encoding="utf-8")
    _commit_all(repo)

    result = CliRunner().invoke(
        main,
        [str(repo), "--include-sensitive-files", "--output", "-"],
    )

    assert result.exit_code == 0, result.output
    assert "EXPLICIT_ENV=visible" in result.output
    assert "EXPLICIT_KEY=visible" in result.output
    assert "excluded by default sensitive-file policy" not in result.output


def test_file_budget_keeps_root_readme_first(tmp_path: Path) -> None:
    repo = tmp_path / "budget-demo"
    _init_repo(repo)

    (repo / "README.md").write_text("# Important overview\n", encoding="utf-8")
    (repo / "aaa.py").write_text("print('code')\n", encoding="utf-8")
    _commit_all(repo)

    result = CliRunner().invoke(
        main,
        [str(repo), "--max-files", "1", "--output", "-"],
    )

    assert result.exit_code == 0, result.output
    assert "# Important overview" in result.output
    assert "print('code')" not in result.output
    assert "1-file document limit" in result.output


def test_non_repository_path_gets_a_clear_error(tmp_path: Path) -> None:
    ordinary_directory = tmp_path / "not-a-repository"
    ordinary_directory.mkdir()

    result = CliRunner().invoke(main, [str(ordinary_directory)])

    assert result.exit_code != 0
    assert "Not a Git repository" in result.output


def test_version_option_starts_without_importing_version_from_package_root() -> None:
    result = CliRunner().invoke(main, ["--version"])

    assert result.exit_code == 0, result.output
    assert "repo-riposte, version" in result.output



def test_dot_defaults_to_the_current_git_worktree(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "inside-repo"
    _init_repo(repo)
    (repo / "README.md").write_text("# Inside\n", encoding="utf-8")
    sha = _commit_all(repo)
    monkeypatch.chdir(repo)

    result = CliRunner().invoke(main, ["."])
    expected = repo / f"inside-repo-{sha[:7]}.md"

    assert result.exit_code == 0, result.output
    assert expected.is_file()
