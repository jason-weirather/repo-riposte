import re

from repo_riposte.models import IncludedFile


def render_file(item: IncludedFile) -> str:
    path = display_text(item.entry.path)
    size = item.entry.size_bytes or 0
    language = (
        item.language
        if re.fullmatch(r"[A-Za-z0-9_+-]+", item.language)
        else "text"
    )
    final_newline = "yes" if item.ends_with_newline else "no"
    fence = code_fence(item.text)

    if item.entry.mode == "120000":
        kind = "symlink"
    elif item.entry.mode == "100755":
        kind = "executable file"
    else:
        kind = "file"

    pieces = [
        f"### {inline_code(path)}\n\n",
        f"**Path:** {inline_code(path)} · "
        f"**Size:** {size / 1024:.2f} KiB ({size:,} bytes) · "
        f"**Lines:** {item.line_count:,} · "
        f"**Language:** {inline_code(language)} · "
        f"**Kind:** {kind} · "
        f"**Final newline:** {final_newline}\n\n",
        f"{fence}{language}\n",
        item.text,
    ]

    # The source's missing final newline is recorded in metadata, but Markdown
    # still needs a newline before the closing fence.
    if not item.text.endswith("\n"):
        pieces.append("\n")

    pieces.append(f"{fence}\n\n")
    return "".join(pieces)


def code_fence(text: str) -> str:
    longest_run = max(
        (len(match.group(0)) for match in re.finditer(r"`+", text)),
        default=0,
    )
    return "`" * max(3, longest_run + 1)


def inline_code(value: str) -> str:
    value = display_text(value)
    longest_run = max(
        (len(match.group(0)) for match in re.finditer(r"`+", value)),
        default=0,
    )
    fence = "`" * max(1, longest_run + 1)
    padding = " " if value.startswith("`") or value.endswith("`") else ""
    return f"{fence}{padding}{value}{padding}{fence}"


def display_text(value: str) -> str:
    return (
        value
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
