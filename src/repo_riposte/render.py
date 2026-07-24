from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from repo_riposte._meta import SNAPSHOT_FORMAT_VERSION
from repo_riposte._version import __version__
from repo_riposte.models import GitFile, IncludedFile, Snapshot
from repo_riposte.policy import SAFETY_REASON_PREFIX


@dataclass(slots=True)
class _TreeNode:
    directories: dict[str, "_TreeNode"] = field(default_factory=dict)
    files: set[str] = field(default_factory=set)


def render_snapshot(
    snapshot: Snapshot,
    *,
    tree_max_children: int = 40,
    omitted_details_limit: int = 200,
) -> str:
    included_bytes = sum(item.entry.size_bytes or 0 for item in snapshot.included_files)
    included_lines = sum(item.line_count for item in snapshot.included_files)

    parts = [
        f"# Repository snapshot: {_inline_code(snapshot.repository_name)}\n\n",
        "This document is an exact text rendering of one Git commit. "
        "Files omitted by policy are reported at the end.\n\n",
        "| Field | Value |\n",
        "|---|---|\n",
        f"| Generator | {_inline_code(f'repo-riposte {__version__}')} |\n",
        f"| Format version | {_inline_code(SNAPSHOT_FORMAT_VERSION)} |\n",
        f"| Source | {_table_cell(snapshot.source_label)} |\n",
    ]

    if snapshot.origin_url and snapshot.origin_url != snapshot.source_label:
        parts.append(f"| Origin | {_table_cell(snapshot.origin_url)} |\n")
    if snapshot.requested_branch:
        parts.append(f"| Branch | {_table_cell(snapshot.requested_branch)} |\n")
    if snapshot.requested_commit:
        parts.append(f"| Requested commit | {_table_cell(snapshot.requested_commit)} |\n")

    parts.extend(
        [
            f"| Resolved commit | {_inline_code(snapshot.commit.sha)} |\n",
            f"| Commit subject | {_table_cell(snapshot.commit.subject)} |\n",
            f"| Commit author | {_table_cell(snapshot.commit.author_name)} |\n",
            f"| Commit authored | {_table_cell(snapshot.commit.authored_at)} |\n",
            f"| Tracked files | {len(snapshot.tracked_files):,} |\n",
            f"| Included files | {len(snapshot.included_files):,} |\n",
            f"| Omitted files | {len(snapshot.omitted_files):,} |\n",
            f"| Included size | {_format_kib(included_bytes)} |\n",
            f"| Included lines | {included_lines:,} |\n\n",
            "## Directory tree\n\n",
            "```text\n",
            render_tree(
                (entry.path for entry in snapshot.tracked_files),
                root_name=snapshot.repository_name,
                max_children=tree_max_children,
            ),
            "\n```\n\n",
            "## Repository files\n\n",
        ]
    )

    for item in snapshot.included_files:
        parts.append(_render_file(item))

    parts.append(
        _render_omissions(snapshot, omitted_details_limit=omitted_details_limit)
    )
    return "".join(parts)


def _render_file(item: IncludedFile) -> str:
    path = _display_text(item.entry.path)
    size = item.entry.size_bytes or 0
    final_newline = "yes" if item.ends_with_newline else "no"
    kind = _kind_for_mode(item.entry.mode)
    fence = _code_fence(item.text)
    language = item.language if re.fullmatch(r"[A-Za-z0-9_+-]+", item.language) else "text"

    pieces = [
        f"### {_inline_code(path)}\n\n",
        f"**Path:** {_inline_code(path)} · "
        f"**Size:** {_format_kib(size)} ({size:,} bytes) · "
        f"**Lines:** {item.line_count:,} · "
        f"**Language:** {_inline_code(language)} · "
        f"**Kind:** {kind} · "
        f"**Final newline:** {final_newline}\n\n",
        f"{fence}{language}\n",
        item.text,
    ]
    if not item.text.endswith("\n"):
        pieces.append("\n")
    pieces.extend([f"{fence}\n\n"])
    return "".join(pieces)


def _render_omissions(snapshot: Snapshot, *, omitted_details_limit: int) -> str:
    if not snapshot.omitted_files:
        return "## Omitted files\n\nNone.\n"

    reason_counts = Counter(item.reason for item in snapshot.omitted_files)
    parts = [
        "## Omitted files\n\n",
        "Omissions are explicit so the snapshot never quietly pretends to be complete.\n\n",
    ]

    if any(
        item.reason.startswith(SAFETY_REASON_PREFIX)
        for item in snapshot.omitted_files
    ):
        parts.append(
            "> **Security note:** Paths marked as default sensitive-file "
            "exclusions were omitted before their blobs were read. "
            "`.env.example` remains eligible for inclusion. "
            "`--include-sensitive-files` can override this, but may expose "
            "credentials or private keys.\n\n"
        )

    parts.append("### Summary\n\n")
    for reason, count in sorted(reason_counts.items(), key=lambda item: (-item[1], item[0])):
        parts.append(f"- {count:,} × {reason}\n")

    parts.extend(
        [
            "\n### Details\n\n",
            "| Path | Size | Reason |\n",
            "|---|---:|---|\n",
        ]
    )
    for omitted in snapshot.omitted_files[:omitted_details_limit]:
        size = (
            _format_kib(omitted.entry.size_bytes)
            if omitted.entry.size_bytes is not None
            else "n/a"
        )
        parts.append(
            f"| {_table_cell(_inline_code(_display_text(omitted.entry.path)))} | {size} | "
            f"{_table_cell(omitted.reason)} |\n"
        )

    hidden_count = len(snapshot.omitted_files) - omitted_details_limit
    if hidden_count > 0:
        parts.append(
            f"\n{hidden_count:,} additional omitted file(s) are not listed; "
            "raise `--omitted-details-limit` to show more.\n"
        )
    return "".join(parts)


def render_tree(paths: Iterable[str], *, root_name: str, max_children: int) -> str:
    root = _TreeNode()
    for path in paths:
        parts = str(path).split("/")
        node = root
        for directory in parts[:-1]:
            node = node.directories.setdefault(directory, _TreeNode())
        if parts and parts[-1]:
            node.files.add(parts[-1])

    lines = [f"{_display_text(root_name)}/"]

    def walk(node: _TreeNode, prefix: str) -> None:
        children: list[tuple[str, bool, _TreeNode | None]] = [
            (name, True, child)
            for name, child in sorted(
                node.directories.items(), key=lambda item: item[0].casefold()
            )
        ]
        children.extend(
            (name, False, None) for name in sorted(node.files, key=str.casefold)
        )

        if len(children) > max_children:
            omitted = len(children) - max_children
            children = children[:max_children] + [
                (f"… ({omitted:,} more entries)", False, None)
            ]

        for index, (name, is_directory, child) in enumerate(children):
            is_last = index == len(children) - 1
            connector = "└── " if is_last else "├── "
            suffix = "/" if is_directory else ""
            lines.append(f"{prefix}{connector}{_display_text(name)}{suffix}")
            if is_directory and child is not None:
                walk(child, prefix + ("    " if is_last else "│   "))

    walk(root, "")
    return "\n".join(lines)


def _kind_for_mode(mode: str) -> str:
    if mode == "120000":
        return "symlink"
    if mode == "100755":
        return "executable file"
    return "file"


def _code_fence(text: str) -> str:
    longest_run = max((len(match.group(0)) for match in re.finditer(r"`+", text)), default=0)
    return "`" * max(3, longest_run + 1)


def _inline_code(value: str) -> str:
    value = _display_text(value)
    longest_run = max((len(match.group(0)) for match in re.finditer(r"`+", value)), default=0)
    fence = "`" * max(1, longest_run + 1)
    padding = " " if value.startswith("`") or value.endswith("`") else ""
    return f"{fence}{padding}{value}{padding}{fence}"


def _display_text(value: str) -> str:
    return value.replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")


def _table_cell(value: str) -> str:
    return _display_text(value).replace("|", "\\|")


def _format_kib(size_bytes: int) -> str:
    return f"{size_bytes / 1024:.2f} KiB"
