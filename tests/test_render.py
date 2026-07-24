from __future__ import annotations

from repo_riposte.render import _code_fence, render_tree


def test_code_fence_grows_past_fences_inside_markdown() -> None:
    assert _code_fence("before\n```python\npass\n```\nafter") == "````"


def test_tree_abbreviates_each_wide_branch() -> None:
    tree = render_tree(
        ["src/a.py", "src/b.py", "src/c.py", "README.md"],
        root_name="demo",
        max_children=2,
    )
    assert "demo/" in tree
    assert "src/" in tree
    assert "… (1 more entries)" in tree


def test_remote_credentials_are_redacted() -> None:
    from repo_riposte.git import _safe_repository_label

    assert (
        _safe_repository_label(
            "https://token:secret@example.com/owner/repo.git?access_token=also-secret"
        )
        == "https://example.com/owner/repo.git"
    )
