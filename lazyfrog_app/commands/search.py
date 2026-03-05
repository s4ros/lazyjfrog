import requests
from rich.panel import Panel

from lazyfrog_app.client import ArtifactoryClient
from lazyfrog_app.console import console
from lazyfrog_app.models import SearchConfig
from lazyfrog_app.rendering import print_results
from lazyfrog_app.search_ops import search_with_feedback


def run_search_command(client: ArtifactoryClient, config: SearchConfig) -> int:
    console.print(
        Panel.fit(
            "[bold yellow]JFrog Artifact Manager[/bold yellow]\\n"
            "[white]Mode: search[/white]",
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
    return 0
