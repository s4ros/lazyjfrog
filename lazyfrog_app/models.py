from dataclasses import dataclass


@dataclass(frozen=True)
class Artifact:
    repo: str
    path: str
    name: str
    size: int | None
    modified: str | None

    @property
    def relative_path(self) -> str:
        return self.name if self.path == "." else f"{self.path}/{self.name}"

    @property
    def display_name(self) -> str:
        return f"{self.repo}/{self.relative_path}"

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.repo, self.path, self.name)


@dataclass
class SearchConfig:
    repository: str
    query: str | None
    max_results: int
    min_score: float
