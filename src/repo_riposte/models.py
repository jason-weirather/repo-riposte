from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GitFile:
    path: str
    mode: str
    object_type: str
    oid: str
    size_bytes: int | None


@dataclass(frozen=True, slots=True)
class CommitInfo:
    sha: str
    short_sha: str
    subject: str
    author_name: str
    authored_at: str


@dataclass(frozen=True, slots=True)
class IncludedFile:
    entry: GitFile
    text: str
    line_count: int
    language: str
    ends_with_newline: bool


@dataclass(frozen=True, slots=True)
class OmittedFile:
    entry: GitFile
    reason: str


@dataclass(frozen=True, slots=True)
class Snapshot:
    repository_name: str
    source_label: str
    origin_url: str | None
    requested_branch: str | None
    requested_commit: str | None
    commit: CommitInfo
    tracked_files: tuple[GitFile, ...]
    included_files: tuple[IncludedFile, ...]
    omitted_files: tuple[OmittedFile, ...]
