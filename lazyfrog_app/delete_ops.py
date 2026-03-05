from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from lazyfrog_app.client import ArtifactoryClient
from lazyfrog_app.console import console
from lazyfrog_app.models import Artifact


def delete_selected(
    client: ArtifactoryClient,
    selected: list[Artifact],
    dry_run: bool,
) -> int:
    if not selected:
        console.print("[yellow]No artifacts selected for deletion.[/yellow]")
        return 0

    summary = Table(title=f"Deletion Plan ({len(selected)} artifacts)")
    summary.add_column("Repository", style="white")
    summary.add_column("Relative Path", style="bold")
    for artifact in selected:
        summary.add_row(artifact.repo, artifact.relative_path)
    console.print(summary)

    if dry_run:
        console.print(Panel.fit("[yellow]Dry-run mode enabled. No deletion requests were sent.[/yellow]"))
        return 0

    failures = 0
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as progress:
        task = progress.add_task("Deleting selected artifacts...", total=None)
        for artifact in selected:
            response = client.delete_artifact(artifact)
            if response.status_code in (200, 202, 204):
                console.print(f"[green]Deleted:[/green] {artifact.display_name}")
            else:
                failures += 1
                console.print(
                    f"[red]Failed ({response.status_code}):[/red] {artifact.display_name}\\n"
                    f"[red]Response:[/red] {response.text.strip() or '-'}"
                )
        progress.update(task, completed=True)

    if failures:
        console.print(Panel.fit(f"[red]Deletion finished with {failures} failure(s).[/red]", title="Result"))
        return 1

    console.print(Panel.fit("[bold green]Deletion completed successfully.[/bold green]"))
    return 0
