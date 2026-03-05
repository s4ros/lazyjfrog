from rich.progress import Progress, SpinnerColumn, TextColumn

from lazyfrog_app.client import ArtifactoryClient
from lazyfrog_app.models import SearchConfig
from lazyfrog_app.scoring import rank_artifacts


def search_with_feedback(
    client: ArtifactoryClient,
    config: SearchConfig,
) -> tuple[list, int]:
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as progress:
        task = progress.add_task("Searching artifacts...", total=None)
        artifacts = client.aql_search(
            repository=config.repository,
            query=config.query,
            max_results=config.max_results,
        )
        progress.update(task, completed=True)
    return rank_artifacts(artifacts, query=config.query, min_score=config.min_score), len(artifacts)
