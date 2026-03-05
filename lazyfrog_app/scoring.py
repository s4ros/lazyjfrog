from collections.abc import Iterable
from difflib import SequenceMatcher

from lazyfrog_app.models import Artifact


def fuzzy_score(query: str | None, artifact: Artifact) -> float:
    if not query:
        return 100.0

    target = f"{artifact.path}/{artifact.name}" if artifact.path != "." else artifact.name
    query_lower = query.lower()
    target_lower = target.lower()
    filename_lower = artifact.name.lower()

    # Exact containment should always win over fuzzy ratio to keep results intuitive.
    contains_bonus = 100.0 if query_lower in target_lower else 0.0

    filename_ratio = SequenceMatcher(None, query_lower, filename_lower).ratio() * 100
    path_ratio = SequenceMatcher(None, query_lower, target_lower).ratio() * 100
    score = max(filename_ratio * 0.7 + path_ratio * 0.3, contains_bonus)
    return round(score, 2)


def fuzzy_score_text(query: str | None, value: str) -> float:
    if not query:
        return 100.0
    query_lower = query.lower()
    value_lower = value.lower()
    contains_bonus = 100.0 if query_lower in value_lower else 0.0
    ratio = SequenceMatcher(None, query_lower, value_lower).ratio() * 100
    return round(max(ratio, contains_bonus), 2)


def rank_artifacts(
    artifacts: Iterable[Artifact],
    query: str | None,
    min_score: float,
) -> list[tuple[Artifact, float]]:
    if not query:
        # Preserve Artifactory order (modified desc: newest -> oldest) with no fuzzy filter.
        return [(artifact, 100.0) for artifact in artifacts if 100.0 >= min_score]

    scored = [(artifact, fuzzy_score(query, artifact)) for artifact in artifacts]
    filtered = [(artifact, score) for artifact, score in scored if score >= min_score]
    filtered.sort(key=lambda row: (-row[1], row[0].display_name))
    return filtered


def rank_repositories(repositories: Iterable[str], query: str | None) -> list[tuple[str, float]]:
    if not query:
        return [(repo, 100.0) for repo in repositories]
    scored = [(repo, fuzzy_score_text(query, repo)) for repo in repositories]
    filtered = [(repo, score) for repo, score in scored if score >= 35.0]
    filtered.sort(key=lambda row: (-row[1], row[0]))
    return filtered
