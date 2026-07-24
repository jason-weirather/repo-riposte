from __future__ import annotations

from repo_riposte.policy import sensitive_path_omission_reason


def test_env_example_is_allowed() -> None:
    assert sensitive_path_omission_reason("config/.env.example") is None


def test_environment_and_key_names_are_protected_case_insensitively() -> None:
    protected = [
        ".env",
        "config/.env.local",
        "production.env",
        "certificates/server.PEM",
        "keys/private.KEY",
    ]
    assert all(sensitive_path_omission_reason(path) is not None for path in protected)
