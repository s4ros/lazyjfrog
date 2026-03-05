import argparse

import requests
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm, Prompt

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
from lazyfrog_app.prompts import (
    ask_for_max_results,
    ask_for_min_score,
    ask_for_query,
    ask_for_repository,
)
from lazyfrog_app.rendering import render_header
from lazyfrog_app.tui.browser import open_fuzzy_browser
from lazyfrog_app.tui.repository_picker import open_repository_picker


def run_tui(client: ArtifactoryClient, args: argparse.Namespace) -> int:
    console.print(Panel.fit("[bold cyan]Loading repositories from Artifactory...[/bold cyan]"))
    try:
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as progress:
            task = progress.add_task("Fetching repository list...", total=None)
            repositories = client.list_repositories()
            progress.update(task, completed=True)
    except requests.HTTPError as exc:
        response = exc.response
        status = response.status_code if response is not None else "?"
        body = response.text.strip() if response is not None else str(exc)
        console.print(Panel.fit(f"[red]Failed to fetch repositories.[/red]\\nStatus: {status}\\nResponse: {body}", title="API Error"))
        return 1
    except requests.RequestException as exc:
        console.print(Panel.fit(f"[red]Network/API error:[/red] {exc}", title="Request Error"))
        return 1

    if not repositories:
        console.print(Panel.fit("[red]No repositories returned by Artifactory.[/red]", title="Repository Error"))
        return 1

    initial_repo_filter = args.repository if args.repository else None
    picked_repo, _picked_filter = open_repository_picker(repositories, initial_repo_filter)
    if not picked_repo:
        console.print("[yellow]No repository selected. Exiting.[/yellow]")
        return 0
    repository = validate_repository(picked_repo)

    config = SearchConfig(
        repository=repository,
        # Repository picker filter is only for selecting repository names.
        # Artifact query must be controlled independently.
        query=validate_query(args.query),
        max_results=validate_max_results(args.max_results),
        min_score=validate_min_score(float(args.min_score)),
    )

    while True:
        console.clear()
        render_header(config)

        try:
            with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as progress:
                task = progress.add_task("Fetching artifacts from Artifactory...", total=None)
                artifacts = client.aql_search(
                    repository=config.repository,
                    query=None,
                    max_results=config.max_results,
                )
                progress.update(task, completed=True)
        except requests.HTTPError as exc:
            response = exc.response
            status = response.status_code if response is not None else "?"
            body = response.text.strip() if response is not None else str(exc)
            console.print(Panel.fit(f"[red]Search failed.[/red]\\nStatus: {status}\\nResponse: {body}", title="API Error"))
            action = Prompt.ask("Action: [c]onfigure, [r]etry, [x]exit", default="c").strip().lower()
            if action == "x":
                return 1
            if action == "c":
                config.repository = ask_for_repository(config.repository)
                config.max_results = ask_for_max_results(config.max_results)
                config.min_score = ask_for_min_score(config.min_score)
                config.query = ask_for_query(config.query)
            continue
        except requests.RequestException as exc:
            console.print(Panel.fit(f"[red]Network/API error:[/red] {exc}", title="Request Error"))
            if Prompt.ask("Continue? [y/N]", default="n").strip().lower() != "y":
                return 1
            continue

        if not artifacts:
            console.print("[yellow]No artifacts found in this repository.[/yellow]")
            action = Prompt.ask(
                "Action: [r]epository, [q]uery, [f]ilters, [x]exit, [enter] refresh",
                default="",
                show_default=False,
            ).strip().lower()
            if action in ("x", "exit"):
                return 0
            if action in ("r", "repo", "repository"):
                config.repository = ask_for_repository(config.repository)
            elif action in ("q", "query"):
                config.query = ask_for_query(config.query)
            elif action in ("f", "filters"):
                config.max_results = ask_for_max_results(config.max_results)
                config.min_score = ask_for_min_score(config.min_score)
            continue

        query_after, selected_artifacts, browser_action = open_fuzzy_browser(
            artifacts=artifacts,
            initial_query=config.query,
            min_score=config.min_score,
        )
        config.query = query_after

        if browser_action == "exit":
            return 0
        if browser_action == "refresh":
            continue
        if browser_action == "repo":
            picked_repo, _picked_filter = open_repository_picker(repositories, config.repository)
            if picked_repo:
                config.repository = validate_repository(picked_repo)
            continue
        if browser_action != "delete":
            continue

        if not selected_artifacts:
            console.print("[yellow]No artifacts selected.[/yellow]")
            Prompt.ask("Press Enter to continue", default="", show_default=False)
            continue

        if not args.yes and not Confirm.ask(
            f"[bold red]Delete {len(selected_artifacts)} selected artifact(s)?[/bold red]",
            default=False,
        ):
            console.print("[yellow]Deletion cancelled.[/yellow]")
            Prompt.ask("Press Enter to continue", default="", show_default=False)
            continue

        try:
            rc = delete_selected(client=client, selected=selected_artifacts, dry_run=args.dry_run)
        except requests.RequestException as exc:
            console.print(Panel.fit(f"[red]Delete request error:[/red] {exc}", title="Request Error"))
            rc = 1

        Prompt.ask("Press Enter to continue", default="", show_default=False)
        if rc != 0:
            return rc
