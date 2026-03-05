import json
from urllib.parse import quote

import requests

from lazyfrog_app.models import Artifact


class ArtifactoryClient:
    def __init__(self, base_url: str, user: str, api_key: str, timeout: int = 20):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.auth = (user, api_key)

    def aql_search(self, repository: str, query: str | None, max_results: int) -> list[Artifact]:
        # Keep server-side filtering strict to a single repository and files only.
        criteria: dict = {"repo": {"$eq": repository}, "type": {"$eq": "file"}}
        if query:
            wildcard = f"*{query}*"
            criteria["$or"] = [
                {"name": {"$match": wildcard}},
                {"path": {"$match": wildcard}},
            ]

        aql = {
            "find": criteria,
            "include": ["repo", "path", "name", "size", "modified"],
            "sort": {"$desc": ["modified"]},
            "limit": max_results,
        }

        payload = self._to_aql_payload(aql)
        response = self.session.post(
            f"{self.base_url}/api/search/aql",
            data=payload,
            headers={"Content-Type": "text/plain"},
            timeout=self.timeout,
        )
        response.raise_for_status()

        parsed = response.json()
        results = parsed.get("results", [])
        return [
            Artifact(
                repo=item.get("repo", ""),
                path=item.get("path", "."),
                name=item.get("name", ""),
                size=self._to_int(item.get("size")),
                modified=item.get("modified"),
            )
            for item in results
            if item.get("repo") and item.get("name")
        ]

    def list_repositories(self) -> list[str]:
        response = self.session.get(
            f"{self.base_url}/api/repositories",
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        repos: list[str] = []
        for item in data:
            if isinstance(item, dict):
                key = item.get("key")
                if isinstance(key, str) and key.strip():
                    repos.append(key.strip())

        # Deduplicate while preserving order from API.
        seen: set[str] = set()
        unique = []
        for repo in repos:
            if repo not in seen:
                seen.add(repo)
                unique.append(repo)
        return unique

    def delete_artifact(self, artifact: Artifact) -> requests.Response:
        # Encode each segment so paths containing spaces/special chars are deleted reliably.
        encoded_repo = quote(artifact.repo, safe="")
        encoded_segments = [quote(segment, safe="") for segment in artifact.relative_path.split("/")]
        artifact_path = "/".join(encoded_segments)
        url = f"{self.base_url}/{encoded_repo}/{artifact_path}"
        return self.session.delete(url, timeout=self.timeout)

    @staticmethod
    def _to_int(value) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_aql_payload(aql: dict) -> str:
        # Build compact AQL DSL text expected by Artifactory's /api/search/aql endpoint.
        find = json.dumps(aql["find"], separators=(",", ":"))
        include = ",".join(f'"{field}"' for field in aql["include"])
        sort = json.dumps(aql["sort"], separators=(",", ":"))
        limit = int(aql["limit"])
        return (
            f"items.find({find})"
            f".include({include})"
            f".sort({sort})"
            f".limit({limit})"
        )
