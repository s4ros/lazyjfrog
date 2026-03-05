import argparse

import requests
from rich.panel import Panel
from rich.prompt import Confirm

from lazyfrog_app.client import ArtifactoryClient
from lazyfrog_app.config import (
    validate_max_results,
    validate_min_score,
    validate_query,
    validate_repository,
)
from lazyfrog_app.console import console
from lazyfrog_app.delete_ops import delete_selected
from lazyfrog_app.models import SearchConfig
from lazyfrog_app.rendering import print_results
from lazyfrog_app.search_ops import search_with_feedback
from lazyfrog_app.selection import parse_selection


def build_search_config_from_args(args: argparse.Namespace) -> SearchConfig:
    return SearchConfig(
        repository=validate_repository(args.repository),
        query=validate_query(args.query),
        max_results=validate_max_results(args.max_results),
        min_score=validate_min_score(float(args.min_score)),
    )


def run_delete_command(client: ArtifactoryClient, args: argparse.Namespace) -> int:
    config = build_search_config_from_args(args)
    console.print(
        Panel.fit(
            "[bold yellow]JFrog Artifact Manager[/bold yellow]\\n"
            "[white]Mode: delete[/white]",
        )
    )
    try:
        results, _ = search_with_feedback(client, config)
    except requests.HTTPError as exc:
        response = exc.response
        status = response.status_code if response is not None else "?"
        body = response.text.strip() if response is not None else str(exc)
        console.print(Panel.fit(f"[red]Search failed.[/red]\\nStatus: {status}\\nResponse: {body}", title="API Error"))
        return 1
    except requests.RequestException as exc:
        console.print(Panel.fit(f"[red]Network/API error:[/red] {exc}", title="Request Error"))
        return 1

    print_results(results=results, max_results=config.max_results)
    if not results:
        console.print("[yellow]No matching artifacts found. Nothing to delete.[/yellow]")
        return 0

    try:
        indexes = parse_selection(args.select, len(results))
    except ValueError as exc:
        console.print(f"[red]Invalid --select value:[/red] {exc}")
        return 1

    selected_artifacts = [results[i - 1][0] for i in indexes]
    if not args.yes and not Confirm.ask(
        f"[bold red]Delete {len(selected_artifacts)} selected artifact(s)?[/bold red]",
        default=False,
    ):
        console.print("[yellow]Deletion cancelled by user.[/yellow]")
        return 0

    try:
        return delete_selected(client=client, selected=selected_artifacts, dry_run=args.dry_run)
    except requests.RequestException as exc:
        console.print(Panel.fit(f"[red]Delete request error:[/red] {exc}", title="Request Error"))
        return 1
