from rich.panel import Panel
from rich.table import Table

from lazyfrog_app.console import console
from lazyfrog_app.models import Artifact, SearchConfig


def render_header(config: SearchConfig) -> None:
    console.print(
        Panel.fit(
            "[bold bright_magenta]JFrog Artifact Manager[/bold bright_magenta]  ✨\\n"
            f"📦 Repo: [bold cyan]{config.repository}[/bold cyan]   "
            f"🔎 Query: [bold green]{config.query or '*'}[/bold green]   "
            f"📊 max: [bold yellow]{config.max_results}[/bold yellow]   "
            f"🎯 min-score: [bold yellow]{config.min_score}[/bold yellow]",
            title="🧭 Interactive TUI",
            subtitle="🔒 Scope is always limited to one repository",
            border_style="bright_blue",
        )
    )


def print_results(
    results: list[tuple[Artifact, float]],
    max_results: int,
    view_limit: int = 100,
) -> None:
    shown_results = results[:view_limit]
    table = Table(title=f"Search Results ({len(results)} found)")
    table.add_column("#", justify="right", style="cyan", no_wrap=True)
    table.add_column("Score", justify="right", style="magenta")
    table.add_column("Path", style="white")
    table.add_column("Name", style="bold")
    table.add_column("Size", justify="right", style="green")
    table.add_column("Modified", style="yellow")

    for idx, (artifact, score) in enumerate(shown_results, start=1):
        table.add_row(
            str(idx),
            f"{score:.2f}",
            artifact.path,
            artifact.name,
            "-" if artifact.size is None else str(artifact.size),
            artifact.modified or "-",
        )
    console.print(table)

    if len(results) > view_limit:
        console.print(
            f"[yellow]Displayed first {view_limit} entries. "
            "Use a narrower query to reduce the list.[/yellow]"
        )
    if len(results) >= max_results:
        console.print(
            "[yellow]Result set reached --max-results. "
            "Refine query or increase limit if needed.[/yellow]"
        )
