from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from urllib.parse import urlsplit, urlunsplit

from repo_riposte.models import CommitInfo, GitFile


class GitError(RuntimeError):
    """Raised when Git cannot produce the requested snapshot."""


def _git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    return environment


def _safe_repository_label(value: str) -> str:
    """Remove URL credentials before source metadata or errors are rendered."""
    try:
        parsed = urlsplit(value)
        if parsed.scheme and parsed.netloc:
            host = parsed.hostname or ""
            if ":" in host and not host.startswith("["):
                host = f"[{host}]"
            try:
                port = f":{parsed.port}" if parsed.port is not None else ""
            except ValueError:
                port = ""
            return urlunsplit((parsed.scheme, f"{host}{port}", parsed.path, "", ""))
    except ValueError:
        pass

    scp_style = re.fullmatch(r"([^@/]+)@([^:]+):(.+)", value)
    if scp_style:
        username, host, path = scp_style.groups()
        safe_username = "git" if username == "git" else "<redacted>"
        return f"{safe_username}@{host}:{path}"
    return value


def _repository_name_from_location(value: str) -> str | None:
    """Extract a repository name from an HTTPS, SSH, or filesystem location."""
    safe_value = _safe_repository_label(value).rstrip("/")
    candidate = ""

    try:
        parsed = urlsplit(safe_value)
        if parsed.scheme and parsed.path:
            candidate = PurePosixPath(parsed.path).name
    except ValueError:
        candidate = ""

    if not candidate:
        scp_style = re.fullmatch(r"(?:[^@/]+@)?[^:]+:(.+)", safe_value)
        if scp_style:
            candidate = PurePosixPath(scp_style.group(1)).name

    if not candidate:
        candidate = Path(safe_value).name

    candidate = candidate.removesuffix(".git").strip()
    return candidate or None


class GitRepository:
    def __init__(self, cwd: Path, source_label: str) -> None:
        self.cwd = cwd
        self.source_label = source_label
        self._assert_repository()

    def _command(self, *args: str) -> list[str]:
        return ["git", "-C", str(self.cwd), *args]

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
        command = self._command(*args)
        try:
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                env=_git_environment(),
            )
        except FileNotFoundError as exc:
            raise GitError("Git is required but was not found on PATH.") from exc

        if check and result.returncode != 0:
            stderr = result.stderr.decode("utf-8", "replace").strip()
            raise GitError(f"Git command failed: {' '.join(command)}\n{stderr}")
        return result

    def _assert_repository(self) -> None:
        result = self._run("rev-parse", "--git-dir", check=False)
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", "replace").strip()
            detail = f"\n{stderr}" if stderr else ""
            raise GitError(f"Not a Git repository: {self.cwd}{detail}")

    @property
    def origin_url(self) -> str | None:
        result = self._run("config", "--get", "remote.origin.url", check=False)
        if result.returncode != 0:
            return None
        value = result.stdout.decode("utf-8", "replace").strip()
        return _safe_repository_label(value) if value else None

    @property
    def repository_name(self) -> str:
        origin = self.origin_url
        if origin:
            candidate = _repository_name_from_location(origin)
            if candidate:
                return candidate

        top_level = self._run("rev-parse", "--show-toplevel", check=False)
        if top_level.returncode == 0:
            top_level_path = top_level.stdout.decode("utf-8", "replace").strip()
            if top_level_path:
                return Path(top_level_path).name

        source_candidate = _repository_name_from_location(self.source_label)
        if source_candidate:
            return source_candidate
        return self.cwd.name.removesuffix(".git") or "repository"

    @staticmethod
    def _validate_ref(ref: str) -> None:
        if not ref or ref.startswith("-") or "\x00" in ref:
            raise GitError(f"Invalid Git ref: {ref!r}")

    def _resolve_ref(self, ref: str) -> str:
        self._validate_ref(ref)
        result = self._run("rev-parse", "--verify", f"{ref}^{{commit}}", check=False)
        if result.returncode != 0:
            raise GitError(f"Could not resolve Git revision {ref!r} to a commit.")
        return result.stdout.decode("ascii").strip()

    def _resolve_branch(self, branch: str) -> str:
        self._validate_ref(branch)
        candidates = (
            (branch,)
            if branch.startswith("refs/")
            else (f"refs/heads/{branch}", f"refs/remotes/origin/{branch}", branch)
        )
        for candidate in candidates:
            result = self._run(
                "rev-parse",
                "--verify",
                f"{candidate}^{{commit}}",
                check=False,
            )
            if result.returncode == 0:
                return result.stdout.decode("ascii").strip()
        raise GitError(f"Could not resolve Git branch {branch!r}.")

    def resolve_commit(self, branch: str | None, commit: str | None) -> str:
        branch_sha = self._resolve_branch(branch) if branch else None
        commit_sha = self._resolve_ref(commit) if commit else None

        if branch_sha and commit_sha:
            ancestry = self._run(
                "merge-base",
                "--is-ancestor",
                commit_sha,
                branch_sha,
                check=False,
            )
            if ancestry.returncode == 1:
                raise GitError(
                    f"Commit {commit_sha} is not reachable from branch {branch!r}."
                )
            if ancestry.returncode != 0:
                stderr = ancestry.stderr.decode("utf-8", "replace").strip()
                raise GitError(f"Could not verify branch ancestry.\n{stderr}")
            return commit_sha

        if commit_sha:
            return commit_sha
        if branch_sha:
            return branch_sha
        return self._resolve_ref("HEAD")

    def commit_info(self, sha: str) -> CommitInfo:
        result = self._run(
            "show",
            "-s",
            "--format=%H%x00%s%x00%an%x00%aI",
            sha,
        )
        fields = result.stdout.rstrip(b"\n").split(b"\x00")
        if len(fields) != 4:
            raise GitError("Git returned unexpected commit metadata.")
        full_sha, subject, author_name, authored_at = (
            field.decode("utf-8", "replace") for field in fields
        )
        return CommitInfo(
            sha=full_sha,
            short_sha=full_sha[:7],
            subject=subject,
            author_name=author_name,
            authored_at=authored_at,
        )

    def list_files(self, sha: str) -> tuple[GitFile, ...]:
        result = self._run("ls-tree", "-r", "-z", "-l", "--full-tree", sha)
        entries: list[GitFile] = []

        for record in result.stdout.split(b"\x00"):
            if not record:
                continue
            try:
                metadata, raw_path = record.split(b"\t", 1)
                mode, object_type, oid, raw_size = metadata.split()
            except ValueError as exc:
                raise GitError("Git returned an unexpected tree entry.") from exc

            size_bytes = None if raw_size == b"-" else int(raw_size)
            entries.append(
                GitFile(
                    path=raw_path.decode("utf-8", "backslashreplace"),
                    mode=mode.decode("ascii"),
                    object_type=object_type.decode("ascii"),
                    oid=oid.decode("ascii"),
                    size_bytes=size_bytes,
                )
            )

        return tuple(sorted(entries, key=lambda entry: entry.path.casefold()))

    def iter_blobs(self, entries: Iterable[GitFile]) -> Iterator[tuple[GitFile, bytes]]:
        command = self._command("cat-file", "--batch")
        stderr_buffer = tempfile.TemporaryFile()
        try:
            try:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=stderr_buffer,
                    env=_git_environment(),
                )
            except FileNotFoundError as exc:
                raise GitError("Git is required but was not found on PATH.") from exc

            if process.stdin is None or process.stdout is None:
                process.kill()
                raise GitError("Could not open pipes for git cat-file.")

            completed = False
            try:
                for entry in entries:
                    process.stdin.write(entry.oid.encode("ascii") + b"\n")
                    process.stdin.flush()

                    header = process.stdout.readline().rstrip(b"\n")
                    parts = header.split()
                    if len(parts) == 2 and parts[1] == b"missing":
                        raise GitError(f"Git blob is missing: {entry.oid}")
                    if len(parts) != 3:
                        raise GitError(f"Unexpected git cat-file response: {header!r}")

                    _oid, object_type, raw_size = parts
                    if object_type != b"blob":
                        raise GitError(
                            f"Expected blob for {entry.path!r}, got "
                            f"{object_type.decode('ascii', 'replace')}."
                        )

                    size = int(raw_size)
                    content = _read_exact(process.stdout, size)
                    if _read_exact(process.stdout, 1) != b"\n":
                        raise GitError("Malformed git cat-file stream.")
                    yield entry, content

                process.stdin.close()
                return_code = process.wait()
                completed = True
                if return_code != 0:
                    stderr_buffer.seek(0)
                    message = stderr_buffer.read().decode("utf-8", "replace").strip()
                    raise GitError(f"git cat-file failed.\n{message}")
            finally:
                if not completed and process.poll() is None:
                    process.kill()
                    process.wait()
        finally:
            stderr_buffer.close()


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    read = stream.read
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = read(remaining)
        if not chunk:
            raise GitError("Unexpected end of git cat-file stream.")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


@contextmanager
def open_repository(source: str) -> Iterator[GitRepository]:
    """Open a local repository or make a temporary bare clone of a remote one."""
    if shutil.which("git") is None:
        raise GitError("Git is required but was not found on PATH.")

    local_path = Path(source).expanduser()
    if local_path.exists():
        if not local_path.is_dir():
            raise GitError(f"Repository path is not a directory: {local_path}")
        yield GitRepository(local_path.resolve(), _safe_repository_label(source))
        return

    with tempfile.TemporaryDirectory(prefix="repo-riposte-") as temporary_directory:
        target = Path(temporary_directory) / "repository.git"
        safe_source = _safe_repository_label(source)

        # Snapshot construction needs blob sizes and contents. A filtered clone
        # only defers that traffic and can fragment it into later promisor fetches.
        command = [
            "git",
            "clone",
            "--bare",
            "--quiet",
            "--",
            source,
            str(target),
        ]
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env=_git_environment(),
        )
        if result.returncode != 0:
            clone_error = result.stderr.decode("utf-8", "replace").strip()
            clone_error = clone_error.replace(source, safe_source)
            raise GitError(f"Could not clone repository {safe_source!r}.\n{clone_error}")

        yield GitRepository(target, safe_source)
