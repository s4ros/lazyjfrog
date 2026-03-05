from rich.prompt import Prompt

from lazyfrog_app.config import (
    validate_max_results,
    validate_min_score,
    validate_repository,
)
from lazyfrog_app.console import console


def ask_for_repository(default_value: str | None) -> str:
    while True:
        repository_raw = Prompt.ask("Repository (required, e.g. helm-local)", default=default_value or "").strip()
        try:
            return validate_repository(repository_raw)
        except ValueError as exc:
            console.print(f"[red]Invalid repository:[/red] {exc}")


def ask_for_query(default_value: str | None) -> str | None:
    value = Prompt.ask("Query (optional, leave empty for all)", default=default_value or "", show_default=False).strip()
    return value or None


def ask_for_max_results(default_value: int) -> int:
    while True:
        raw = Prompt.ask("Max results", default=str(default_value))
        try:
            return validate_max_results(int(raw))
        except (ValueError, TypeError):
            console.print("[red]Invalid value. Use integer in range 1-5000.[/red]")


def ask_for_min_score(default_value: float) -> float:
    while True:
        raw = Prompt.ask("Minimum fuzzy score (0-100)", default=str(default_value))
        try:
            return validate_min_score(float(raw))
        except (ValueError, TypeError):
            console.print("[red]Invalid value. Use number in range 0-100.[/red]")
