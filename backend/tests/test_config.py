from __future__ import annotations

from pathlib import Path

from pytest import MonkeyPatch

from app.config import Settings, resolve_env_files


def test_resolve_env_files_contains_backend_and_repo_root() -> None:
    env_files = resolve_env_files()
    assert env_files[0].endswith("backend/.env")
    assert env_files[1].endswith(".env")
    assert env_files[0] != env_files[1]


def test_settings_reads_from_dotenv_file(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    backend_env, repo_env = (Path(path) for path in resolve_env_files())
    backend_original = backend_env.read_text(encoding="utf-8") if backend_env.exists() else None
    repo_original = repo_env.read_text(encoding="utf-8") if repo_env.exists() else None

    try:
        payload = "OPENROUTER_API_KEY=test-from-dotenv\n"
        backend_env.write_text(payload, encoding="utf-8")
        repo_env.write_text(payload, encoding="utf-8")

        settings = Settings()
        assert settings.openrouter_api_key == "test-from-dotenv"
    finally:
        if backend_original is None:
            backend_env.unlink(missing_ok=True)
        else:
            backend_env.write_text(backend_original, encoding="utf-8")

        if repo_original is None:
            repo_env.unlink(missing_ok=True)
        else:
            repo_env.write_text(repo_original, encoding="utf-8")
