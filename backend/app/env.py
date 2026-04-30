"""Application environment loading."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv


def load_app_env(env_path: Path | None = None) -> None:
    """Load backend `.env` without expanding `$` inside secret values."""
    backend_root = Path(__file__).resolve().parents[1]
    target = env_path or backend_root / ".env"
    if not target.exists():
        return

    load_dotenv(target, override=False, interpolate=False)
