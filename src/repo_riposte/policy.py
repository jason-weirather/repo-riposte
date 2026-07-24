from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import PurePosixPath

from repo_riposte.models import GitFile


_LANGUAGE_BY_SUFFIX = {
    ".bash": "bash",
    ".c": "c",
    ".cc": "cpp",
    ".cfg": "ini",
    ".clj": "clojure",
    ".cljs": "clojure",
    ".cmake": "cmake",
    ".cpp": "cpp",
    ".cs": "csharp",
    ".css": "css",
    ".csv": "csv",
    ".cxx": "cpp",
    ".dart": "dart",
    ".dockerfile": "dockerfile",
    ".el": "elisp",
    ".ex": "elixir",
    ".exs": "elixir",
    ".fs": "fsharp",
    ".fsx": "fsharp",
    ".go": "go",
    ".graphql": "graphql",
    ".gql": "graphql",
    ".h": "c",
    ".hpp": "cpp",
    ".hs": "haskell",
    ".html": "html",
    ".ini": "ini",
    ".java": "java",
    ".jl": "julia",
    ".js": "javascript",
    ".json": "json",
    ".json5": "json5",
    ".jsx": "jsx",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".less": "less",
    ".lua": "lua",
    ".md": "markdown",
    ".mdx": "mdx",
    ".mjs": "javascript",
    ".mk": "makefile",
    ".php": "php",
    ".pl": "perl",
    ".proto": "protobuf",
    ".ps1": "powershell",
    ".py": "python",
    ".pyi": "python",
    ".r": "r",
    ".rb": "ruby",
    ".rs": "rust",
    ".rst": "rst",
    ".sass": "sass",
    ".scala": "scala",
    ".scss": "scss",
    ".sh": "bash",
    ".sol": "solidity",
    ".sql": "sql",
    ".svelte": "svelte",
    ".swift": "swift",
    ".tex": "latex",
    ".tf": "hcl",
    ".toml": "toml",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".txt": "text",
    ".vue": "vue",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".zig": "zig",
    ".zsh": "zsh",
}

_LANGUAGE_BY_FILENAME = {
    "cmakelists.txt": "cmake",
    "containerfile": "dockerfile",
    "dockerfile": "dockerfile",
    "gemfile": "ruby",
    "justfile": "makefile",
    "makefile": "makefile",
    "procfile": "text",
    "rakefile": "ruby",
}

_CODE_SUFFIXES = {
    suffix
    for suffix, language in _LANGUAGE_BY_SUFFIX.items()
    if language not in {"csv", "latex", "markdown", "mdx", "rst", "text"}
}

_STRUCTURED_FILENAMES = {
    ".editorconfig",
    ".gitattributes",
    ".gitignore",
    ".pre-commit-config.yaml",
    "cargo.toml",
    "composer.json",
    "go.mod",
    "go.sum",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "setup.cfg",
    "setup.py",
}

_PROJECT_METADATA_ORDER = {
    "pyproject.toml": 0,
    "setup.cfg": 1,
    "setup.py": 2,
    "package.json": 3,
    "cargo.toml": 4,
    "go.mod": 5,
    "composer.json": 6,
    "requirements.txt": 7,
    ".gitignore": 8,
    ".gitattributes": 9,
    "license": 10,
    "license.md": 11,
    "license.txt": 12,
}

_SAFE_ENV_EXAMPLE = ".env.example"
_SENSITIVE_KEY_SUFFIXES = {".key", ".pem"}
SAFETY_REASON_PREFIX = "excluded by default sensitive-file policy"


@dataclass(frozen=True, slots=True)
class InclusionPolicy:
    max_file_bytes: int = 1024 * 1024
    max_noncode_bytes: int = 256 * 1024
    max_total_bytes: int | None = None
    max_included_files: int | None = None
    exclude_patterns: tuple[str, ...] = ()
    exclude_sensitive: bool = True

    def preflight_omission_reason(self, entry: GitFile) -> str | None:
        if entry.object_type != "blob" or entry.mode == "160000":
            return "submodule or non-blob Git object"

        if self.exclude_sensitive:
            safety_reason = sensitive_path_omission_reason(entry.path)
            if safety_reason is not None:
                return safety_reason

        for pattern in self.exclude_patterns:
            if fnmatch.fnmatchcase(entry.path, pattern):
                return f"excluded by pattern {pattern!r}"

        if entry.size_bytes is None:
            return "Git did not report a blob size"
        if entry.size_bytes > self.max_file_bytes:
            return f"exceeds the {self.max_file_bytes // 1024:,} KiB file limit"
        if (
            not is_code_like(entry.path)
            and not is_root_readme(entry.path)
            and entry.size_bytes > self.max_noncode_bytes
        ):
            return f"exceeds the {self.max_noncode_bytes // 1024:,} KiB non-code limit"
        return None


def sensitive_path_omission_reason(path: str) -> str | None:
    """Return a safety-policy reason for paths likely to contain credentials."""
    name = PurePosixPath(path).name.casefold()

    if name == _SAFE_ENV_EXAMPLE:
        return None
    if name == ".env" or name.startswith(".env.") or name.endswith(".env"):
        return (
            f"{SAFETY_REASON_PREFIX} "
            "(.env-style file; .env.example is allowed)"
        )
    suffix = PurePosixPath(name).suffix
    if suffix in _SENSITIVE_KEY_SUFFIXES:
        return f"{SAFETY_REASON_PREFIX} (*{suffix})"
    return None


def inspect_text(data: bytes) -> tuple[str | None, str | None]:
    sample = data[:8192]
    if b"\x00" in data:
        return None, "binary content (NUL byte detected)"

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None, "content is not valid UTF-8 text"

    if sample:
        disallowed_controls = sum(
            byte < 32 and byte not in {9, 10, 12, 13} for byte in sample
        )
        if disallowed_controls / len(sample) > 0.02:
            return None, "binary-like control characters detected"

    return text, None


def count_lines(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def language_for_path(path: str) -> str:
    name = PurePosixPath(path).name.casefold()
    if name in _LANGUAGE_BY_FILENAME:
        return _LANGUAGE_BY_FILENAME[name]

    lower_path = path.casefold()
    for suffix, language in sorted(
        _LANGUAGE_BY_SUFFIX.items(), key=lambda item: len(item[0]), reverse=True
    ):
        if lower_path.endswith(suffix):
            return language
    return "text"


def is_code_like(path: str) -> bool:
    name = PurePosixPath(path).name.casefold()
    if name in _LANGUAGE_BY_FILENAME or name in _STRUCTURED_FILENAMES:
        return True
    return any(path.casefold().endswith(suffix) for suffix in _CODE_SUFFIXES)


def is_root_readme(path: str) -> bool:
    parsed = PurePosixPath(path)
    if len(parsed.parts) != 1:
        return False
    name = parsed.name.casefold()
    return name == "readme" or name.startswith("readme.")


def content_sort_key(path: str) -> tuple[object, ...]:
    parsed = PurePosixPath(path)
    name = parsed.name.casefold()

    if is_root_readme(path):
        extension_rank = {
            "readme.md": 0,
            "readme.rst": 1,
            "readme.txt": 2,
            "readme": 3,
        }.get(name, 4)
        return (0, extension_rank, path.casefold())

    if len(parsed.parts) == 1 and name in _PROJECT_METADATA_ORDER:
        return (1, _PROJECT_METADATA_ORDER[name], path.casefold())

    return (10, tuple(part.casefold() for part in parsed.parts), path)
