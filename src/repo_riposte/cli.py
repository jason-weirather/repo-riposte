from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

import click

from repo_riposte._meta import __version__
from repo_riposte.git import GitError, open_repository
from repo_riposte.models import Snapshot
from repo_riposte.policy import InclusionPolicy
from repo_riposte.render import render_snapshot
from repo_riposte.snapshot import build_snapshot


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument("repository", required=False, default=".")
@click.option(
    "-b",
    "--branch",
    metavar="BRANCH",
    help="Render the tip of BRANCH, or validate --commit against it.",
)
@click.option(
    "-c",
    "--commit",
    "commit_ref",
    metavar="COMMIT",
    help=(
        "Commit, tag, or other commit-ish to render. "
        "When --branch is also given, COMMIT must be reachable from it."
    ),
)
@click.option(
    "-o",
    "--output",
    metavar="PATH",
    help=(
        "Write Markdown to PATH. By default writes "
        "<repository>-<7-character-commit>.md in the current directory. "
        "Use '-' for standard output."
    ),
)
@click.option(
    "--max-file-kb",
    type=click.IntRange(min=1),
    default=1024,
    show_default=True,
    help="Hard size limit for any included file.",
)
@click.option(
    "--max-noncode-kb",
    type=click.IntRange(min=1),
    default=256,
    show_default=True,
    help="Lower size limit for files not recognized as code or project metadata.",
)
@click.option(
    "--max-total-kb",
    type=click.IntRange(min=0),
    default=0,
    show_default=True,
    help="Maximum combined included blob size; 0 means unlimited.",
)
@click.option(
    "--max-files",
    type=click.IntRange(min=0),
    default=0,
    show_default=True,
    help="Maximum number of included files; 0 means unlimited.",
)
@click.option(
    "--exclude",
    "exclude_patterns",
    multiple=True,
    metavar="GLOB",
    help="Exclude a tracked path using a shell-style glob. Repeatable.",
)
@click.option(
    "--include-sensitive-files",
    "--include-sensitive",
    "include_sensitive",
    is_flag=True,
    help=(
        "Include normally protected environment and key files such as .env, "
        ".env.local, *.env, *.pem, and *.key. Use with care."
    ),
)
@click.option(
    "--tree-max-children",
    type=click.IntRange(min=1),
    default=40,
    show_default=True,
    help="Maximum entries shown per directory before that tree branch is abbreviated.",
)
@click.option(
    "--omitted-details-limit",
    type=click.IntRange(min=0),
    default=200,
    show_default=True,
    help="Maximum omitted-file rows listed in the Markdown appendix.",
)
@click.version_option(version=__version__, prog_name="repo-riposte")
def main(
    repository: str,
    branch: str | None,
    commit_ref: str | None,
    output: str | None,
    max_file_kb: int,
    max_noncode_kb: int,
    max_total_kb: int,
    max_files: int,
    exclude_patterns: tuple[str, ...],
    include_sensitive: bool,
    tree_max_children: int,
    omitted_details_limit: int,
) -> None:
    """Render one exact Git commit as a single Markdown document.

    REPOSITORY defaults to the current directory. It may be a local working
    tree, a bare repository, or a cloneable HTTPS/SSH Git location. No checkout
    is modified; tracked blobs are read directly from Git's object database.
    """
    if max_noncode_kb > max_file_kb:
        raise click.UsageError("--max-noncode-kb cannot exceed --max-file-kb.")

    policy = InclusionPolicy(
        max_file_bytes=max_file_kb * 1024,
        max_noncode_bytes=max_noncode_kb * 1024,
        max_total_bytes=max_total_kb * 1024 if max_total_kb else None,
        max_included_files=max_files or None,
        exclude_patterns=exclude_patterns,
        exclude_sensitive=not include_sensitive,
    )

    try:
        with open_repository(repository) as git_repository:
            snapshot = build_snapshot(
                git_repository,
                branch=branch,
                commit_ref=commit_ref,
                policy=policy,
            )
            markdown = render_snapshot(
                snapshot,
                tree_max_children=tree_max_children,
                omitted_details_limit=omitted_details_limit,
            )

        selected_output = output or default_output_filename(snapshot)
        destination = _write_output(markdown, selected_output)
        if destination is not None:
            click.echo(f"Wrote {destination.resolve()}", err=True)
    except GitError as exc:
        raise click.ClickException(str(exc)) from exc
    except OSError as exc:
        raise click.ClickException(str(exc)) from exc


def default_output_filename(snapshot: Snapshot) -> str:
    """Return the deterministic default output name for a snapshot."""
    repository_name = _safe_filename_component(snapshot.repository_name)
    short_sha = snapshot.commit.sha[:7].lower()
    return f"{repository_name}-{short_sha}.md"


def _safe_filename_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("._-")
    cleaned = cleaned[:120].rstrip("._-")
    return cleaned or "repository"


def _write_output(markdown: str, output: str) -> Path | None:
    if output == "-":
        sys.stdout.write(markdown)
        return None
    if not output.strip():
        raise OSError("Output path cannot be empty.")

    destination = Path(output).expanduser()
    if destination.exists() and destination.is_dir():
        raise OSError(f"Output path is a directory: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            handle.write(markdown)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
        temporary_name = None
        return destination
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass
