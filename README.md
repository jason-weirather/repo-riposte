# repo-riposte

`repo-riposte` renders one exact Git commit as a single Markdown document designed for review, archival, and LLM context.

The snapshot contains:

1. Repository and commit metadata.
2. A bounded, `tree`-style directory listing.
3. The root README near the front, followed by project metadata and the remaining text files.
4. A compact path, size, and line-count preamble before every included file.
5. A syntax-labelled, collision-safe fenced code block containing each included file.
6. An explicit appendix for sensitive, binary, oversized, excluded, and otherwise omitted files.

The working tree is never used as the source of truth. Files are enumerated and read directly from Git's object database, so untracked files and uncommitted edits cannot leak into the document.

## Install for development

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
repo-riposte --version
```

This installs the `repo-riposte` command through the package entry point. After replacing an older editable checkout, rerun the install command so the entry point and package metadata are refreshed.

## Default output filename

No output option is required:

```bash
repo-riposte .
```

The command resolves the selected commit and writes:

```text
REPOSITORY-SEVENSHA.md
```

For example, running against this repository at commit `2294c1f...` writes:

```text
repo-riposte-2294c1f.md
```

The repository name comes from `remote.origin.url` when available. Otherwise, a working tree uses its Git top-level directory name, even when the command is run from a nested subdirectory. A bare repository falls back to its repository directory name.

Both common GitHub URL forms produce the same output name:

```bash
repo-riposte https://github.com/jason-weirather/repo-riposte.git
repo-riposte git@github.com:jason-weirather/repo-riposte.git
```

Use a custom path with `--output`:

```bash
repo-riposte . --output snapshots/main.md
```

Use standard output explicitly with `--output -`:

```bash
repo-riposte . --output -
```

## Selecting a branch or commit

Render the tip of a branch:

```bash
repo-riposte . --branch main
```

Render an exact commit, tag, or other commit-ish:

```bash
repo-riposte . --commit 0123456789abcdef
```

When both are supplied, the commit is rendered only after Git verifies that it is reachable from the branch:

```bash
repo-riposte . \
  --branch main \
  --commit 0123456789abcdef \
  --output repository.md
```

The same options work for HTTPS URLs, SSH URLs, local working trees, nested directories inside a working tree, and bare repositories.

## Sensitive-file defaults

Before any candidate blob is read, the default policy omits:

- `.env`, `.env.*`, and `*.env` files, except the exact filename `.env.example`;
- files ending in `.pem`;
- files ending in `.key`.

The generated Markdown ends with an omission report containing each omitted path, its size, and the policy reason. The directory tree still shows the path, making the exclusion visible without exposing its content.

For a deliberate local-only snapshot, the filename safety policy can be disabled:

```bash
repo-riposte . --include-sensitive-files
```

That flag only disables these filename-based exclusions. Binary detection, size limits, explicit `--exclude` patterns, and document limits still apply. It is not a content-aware secret scanner, so review tracked files before sending a generated snapshot to another system.

## Other inclusion controls

Exclude low-value tracked paths with repeatable shell-style globs:

```bash
repo-riposte . \
  --exclude 'vendor/*' \
  --exclude '*.min.js' \
  --exclude '*.map'
```

Bound a very large repository while preserving README-first priority:

```bash
repo-riposte . \
  --max-total-kb 20000 \
  --max-files 5000
```

By default, the command also:

- includes valid UTF-8 text tracked by the selected commit;
- rejects blobs containing NUL bytes or a suspicious density of control characters;
- omits any file larger than 1 MiB;
- applies a lower 256 KiB limit to prose and other non-code files, while allowing a root README up to the global limit;
- reports submodules rather than pretending their contents are part of the parent commit;
- removes URL user-info credentials from rendered source metadata and clone errors;
- leaves total document size and file count unlimited unless `--max-total-kb` or `--max-files` is set;
- shows at most 40 immediate children in each directory-tree branch before abbreviating it.

Run `repo-riposte --help` for the complete option set.

## Development

```bash
pytest
ruff check src tests
```

The tests create temporary Git repositories and verify exact-commit rendering, README-first ordering, default output naming, branch and commit selection, sensitive-file omissions, collision-safe Markdown fences, and origin-name parsing for HTTPS and SSH remotes.
