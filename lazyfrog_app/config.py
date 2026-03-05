import os
import sys

from rich.panel import Panel

from lazyfrog_app.console import console


MIN_PYTHON = (3, 14)


def ensure_python_version() -> None:
    if sys.version_info < MIN_PYTHON:
        required = ".".join(str(part) for part in MIN_PYTHON)
        current = ".".join(str(part) for part in sys.version_info[:3])
        console.print(
            Panel.fit(
                f"[red]Python {required}+ is required.[/red]\\nCurrent interpreter: {current}",
                title="Version Error",
            )
        )
        sys.exit(2)


def validate_repository(value: str | None) -> str:
    repo = (value or "").strip()
    if not repo:
        raise ValueError("repository cannot be empty")
    if "/" in repo or ".." in repo:
        raise ValueError("repository contains invalid characters")
    return repo


def validate_query(value: str | None) -> str | None:
    if value is None:
        return None
    query = value.strip()
    return query or None


def validate_max_results(value: int) -> int:
    if value <= 0 or value > 5000:
        raise ValueError("max-results must be in range 1-5000")
    return value


def validate_min_score(value: float) -> float:
    if value < 0 or value > 100:
        raise ValueError("min-score must be in range 0-100")
    return value


def validate_base_url(value: str) -> str:
    base_url = value.strip().rstrip("/")
    if not base_url:
        raise ValueError("ARTIFACTORY_BASE_URL cannot be empty")
    if not (base_url.startswith("http://") or base_url.startswith("https://")):
        raise ValueError("ARTIFACTORY_BASE_URL must start with http:// or https://")
    return base_url


def get_env_or_exit(name: str) -> str:
    value = os.getenv(name)
    if not value:
        console.print(
            Panel.fit(
                f"[red]Missing required environment variable:[/red] {name}",
                title="Configuration Error",
            )
        )
        sys.exit(2)
    return value


def get_env_int_or_default(name: str, default_value: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default_value
    try:
        value = int(raw)
    except ValueError:
        console.print(
            Panel.fit(
                f"[red]Invalid integer in environment variable:[/red] {name}={raw!r}",
                title="Configuration Error",
            )
        )
        sys.exit(2)
    if value <= 0:
        console.print(
            Panel.fit(
                f"[red]Environment variable must be > 0:[/red] {name}={value}",
                title="Configuration Error",
            )
        )
        sys.exit(2)
    return value
