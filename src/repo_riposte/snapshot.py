from __future__ import annotations

from repo_riposte.git import GitRepository
from repo_riposte.models import IncludedFile, OmittedFile, Snapshot
from repo_riposte.policy import (
    InclusionPolicy,
    content_sort_key,
    count_lines,
    inspect_text,
    language_for_path,
)


def build_snapshot(
    repository: GitRepository,
    *,
    branch: str | None,
    commit_ref: str | None,
    policy: InclusionPolicy,
) -> Snapshot:
    commit_sha = repository.resolve_commit(branch, commit_ref)
    commit = repository.commit_info(commit_sha)
    tracked_files = repository.list_files(commit_sha)

    candidates = []
    omitted: list[OmittedFile] = []

    for entry in tracked_files:
        reason = policy.preflight_omission_reason(entry)
        if reason:
            omitted.append(OmittedFile(entry=entry, reason=reason))
        else:
            candidates.append(entry)

    # Root README first, then root project metadata, then normal path order.
    # This ordering also determines which files survive a total document budget.
    candidates.sort(key=lambda entry: content_sort_key(entry.path))

    included: list[IncludedFile] = []
    included_bytes = 0

    for entry, data in repository.iter_blobs(candidates):
        text, reason = inspect_text(data)
        if reason is not None or text is None:
            omitted.append(
                OmittedFile(entry=entry, reason=reason or "not text")
            )
            continue

        size_bytes = entry.size_bytes or 0

        if (
            policy.max_included_files is not None
            and len(included) >= policy.max_included_files
        ):
            omitted.append(
                OmittedFile(
                    entry=entry,
                    reason=(
                        f"exceeds the "
                        f"{policy.max_included_files:,}-file document limit"
                    ),
                )
            )
            continue

        if (
            policy.max_total_bytes is not None
            and included_bytes + size_bytes > policy.max_total_bytes
        ):
            omitted.append(
                OmittedFile(
                    entry=entry,
                    reason=(
                        f"would exceed the "
                        f"{policy.max_total_bytes // 1024:,} KiB "
                        "document limit"
                    ),
                )
            )
            continue

        included.append(
            IncludedFile(
                entry=entry,
                text=text,
                line_count=count_lines(text),
                language=(
                    "text"
                    if entry.mode == "120000"
                    else language_for_path(entry.path)
                ),
                ends_with_newline=text.endswith("\n"),
            )
        )
        included_bytes += size_bytes

    included.sort(key=lambda item: content_sort_key(item.entry.path))
    omitted.sort(key=lambda item: item.entry.path.casefold())

    return Snapshot(
        repository_name=repository.repository_name,
        source_label=repository.source_label,
        origin_url=repository.origin_url,
        requested_branch=branch,
        requested_commit=commit_ref,
        commit=commit,
        tracked_files=tracked_files,
        included_files=tuple(included),
        omitted_files=tuple(omitted),
    )
