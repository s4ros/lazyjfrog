#!/usr/bin/env python3

import argparse
import curses
import json
import os
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher
from urllib.parse import quote

import requests
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm, Prompt
from rich.table import Table

console = Console()

MIN_PYTHON = (3, 14)

if sys.version_info < MIN_PYTHON:
    required = ".".join(str(part) for part in MIN_PYTHON)
    current = ".".join(str(part) for part in sys.version_info[:3])
    console.print(
        Panel.fit(
            f"[red]Python {required}+ is required.[/red]\nCurrent interpreter: {current}",
            title="Version Error",
        )
    )
    sys.exit(2)


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
            f'.include({include})'
            f".sort({sort})"
            f".limit({limit})"
        )


def add_common_flags(parser: argparse.ArgumentParser, repository_required: bool) -> None:
    parser.add_argument(
        "--repository",
        required=repository_required,
        help="Repository name (required for search scope safety).",
    )
    parser.add_argument(
        "--query",
        help="Search phrase used for server-side filtering and fuzzy ranking.",
    )
    parser.add_argument(
        "--max-results",
        default=200,
        type=int,
        help="Maximum number of artifacts fetched from Artifactory (default: 200).",
    )
    parser.add_argument(
        "--min-score",
        default=35.0,
        type=float,
        help="Minimum fuzzy score (0-100) required to display a result (default: 35).",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="JFrog Artifact Manager: interactive search and safe deletion.",
        epilog=(
            "Required env: ARTIFACTORY_BASE_URL, ARTIFACTORY_USER, ARTIFACTORY_API_KEY. "
            "Optional env: ARTIFACTORY_TIMEOUT (default: 20)."
        ),
    )

    subparsers = parser.add_subparsers(dest="command")

    tui_parser = subparsers.add_parser(
        "tui",
        help="Interactive TUI workflow (default command when omitted).",
    )
    add_common_flags(tui_parser, repository_required=False)
    tui_parser.add_argument("--yes", action="store_true", help="Skip final confirmation prompts.")
    tui_parser.add_argument("--dry-run", action="store_true", help="Preview deletions only.")

    search_parser = subparsers.add_parser("search", help="Search artifacts in a repository.")
    add_common_flags(search_parser, repository_required=True)

    delete_parser = subparsers.add_parser(
        "delete", help="Search artifacts and delete selected results."
    )
    add_common_flags(delete_parser, repository_required=True)
    delete_parser.add_argument(
        "--select",
        required=True,
        help='Selection expression, for example: "1,2,6" or "1-4,9".',
    )
    delete_parser.add_argument("--yes", action="store_true", help="Skip final confirmation prompts.")
    delete_parser.add_argument("--dry-run", action="store_true", help="Preview deletions only.")

    args = parser.parse_args()
    if args.command is None:
        args.command = "tui"
        if not hasattr(args, "repository"):
            args.repository = None
            args.query = None
            args.max_results = 200
            args.min_score = 35.0
            args.yes = False
            args.dry_run = False
    return args


def validate_repository(value: str | None) -> str:
    repo = (value or "").strip()
    if not repo:
        raise ValueError("repository cannot be empty")
    if "/" in repo or ".." in repo:
        raise ValueError("repository contains invalid characters")
    return repo


def validate_query(value: str | None) -> str | None:
    if value is None:
        return None
    query = value.strip()
    return query or None


def validate_max_results(value: int) -> int:
    if value <= 0 or value > 5000:
        raise ValueError("max-results must be in range 1-5000")
    return value


def validate_min_score(value: float) -> float:
    if value < 0 or value > 100:
        raise ValueError("min-score must be in range 0-100")
    return value


def get_env_or_exit(name: str) -> str:
    value = os.getenv(name)
    if not value:
        console.print(
            Panel.fit(
                f"[red]Missing required environment variable:[/red] {name}",
                title="Configuration Error",
            )
        )
        sys.exit(2)
    return value


def get_env_int_or_default(name: str, default_value: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default_value
    try:
        value = int(raw)
    except ValueError:
        console.print(
            Panel.fit(
                f"[red]Invalid integer in environment variable:[/red] {name}={raw!r}",
                title="Configuration Error",
            )
        )
        sys.exit(2)
    if value <= 0:
        console.print(
            Panel.fit(
                f"[red]Environment variable must be > 0:[/red] {name}={value}",
                title="Configuration Error",
            )
        )
        sys.exit(2)
    return value


def validate_base_url(value: str) -> str:
    base_url = value.strip().rstrip("/")
    if not base_url:
        raise ValueError("ARTIFACTORY_BASE_URL cannot be empty")
    if not (base_url.startswith("http://") or base_url.startswith("https://")):
        raise ValueError("ARTIFACTORY_BASE_URL must start with http:// or https://")
    return base_url


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
        # Preserve Artifactory order (modified desc: newest -> oldest) when no fuzzy filter is active.
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


def render_header(config: SearchConfig) -> None:
    console.print(
        Panel.fit(
            "[bold bright_magenta]JFrog Artifact Manager[/bold bright_magenta]  ✨\n"
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


def parse_selection(value: str, limit: int) -> list[int]:
    expression = value.strip().lower()
    if not expression:
        raise ValueError("selection is empty")
    if expression == "all":
        return list(range(1, limit + 1))

    # Preserve user order while deduplicating repeated indexes/ranges.
    indexes: list[int] = []
    seen: set[int] = set()
    chunks = [item.strip() for item in expression.split(",") if item.strip()]
    for chunk in chunks:
        if "-" in chunk:
            parts = [part.strip() for part in chunk.split("-", maxsplit=1)]
            if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
                raise ValueError(f'invalid range "{chunk}"')
            start, end = int(parts[0]), int(parts[1])
            if start > end:
                start, end = end, start
            if start < 1 or end > limit:
                raise ValueError(f'range "{chunk}" out of bounds 1-{limit}')
            for idx in range(start, end + 1):
                if idx not in seen:
                    seen.add(idx)
                    indexes.append(idx)
            continue

        if not chunk.isdigit():
            raise ValueError(f'invalid index "{chunk}"')
        idx = int(chunk)
        if idx < 1 or idx > limit:
            raise ValueError(f"index {idx} out of range 1-{limit}")
        if idx not in seen:
            seen.add(idx)
            indexes.append(idx)
    return indexes


def open_fuzzy_browser(
    artifacts: list[Artifact],
    initial_query: str | None,
    min_score: float,
) -> tuple[str | None, list[Artifact], str]:
    if not artifacts:
        return initial_query, [], "exit"
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return initial_query, [], "exit"

    def _run(stdscr: curses.window) -> tuple[str | None, list[Artifact], str]:
        curses.curs_set(0)
        stdscr.keypad(True)
        has_colors = curses.has_colors()
        if has_colors:
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_CYAN, -1)
            curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_CYAN)
            curses.init_pair(3, curses.COLOR_GREEN, -1)
            curses.init_pair(4, curses.COLOR_YELLOW, -1)
            curses.init_pair(5, curses.COLOR_MAGENTA, -1)

        def cp(pair: int) -> int:
            return curses.color_pair(pair) if has_colors else curses.A_NORMAL

        def draw_help_line(y: int, items: list[tuple[str, str]]) -> None:
            x = 0
            max_w = max(0, width - 1)
            for idx, (token, desc) in enumerate(items):
                if x >= max_w:
                    break
                token_text = f"[{token}]"
                stdscr.addnstr(y, x, token_text, max_w - x, cp(1) | curses.A_BOLD)
                x += len(token_text)
                if x >= max_w:
                    break
                stdscr.addnstr(y, x, f" {desc}", max_w - x, cp(4))
                x += 1 + len(desc)
                if idx < len(items) - 1 and x < max_w:
                    sep = " | "
                    stdscr.addnstr(y, x, sep, max_w - x, cp(5))
                    x += len(sep)

        query = initial_query or ""
        search_mode = False
        # Track selection by stable artifact identity so filtering/reordering is safe.
        selected_keys: set[tuple[str, str, str]] = set()
        cursor = 0
        offset = 0

        def current_rows() -> list[tuple[Artifact, float]]:
            return rank_artifacts(artifacts=artifacts, query=query or None, min_score=min_score)

        rows = current_rows()

        while True:
            rows = current_rows()
            if cursor >= len(rows):
                cursor = max(0, len(rows) - 1)
            if cursor < offset:
                offset = cursor

            stdscr.erase()
            height, width = stdscr.getmaxyx()
            list_start = 3
            list_rows = max(4, height - 6)

            if cursor >= offset + list_rows:
                offset = cursor - list_rows + 1
            if offset < 0:
                offset = 0

            header = (
                f"✨ JFrog Browser  📦 {artifacts[0].repo}  "
                f"📄 {len(rows)}/{len(artifacts)}  ✅ {len(selected_keys)} selected"
            )
            stdscr.addnstr(0, 0, header, max(0, width - 1), cp(1) | curses.A_BOLD)
            stdscr.addnstr(
                1,
                0,
                f"🔎 Filter: {query or '*'}  {'[SEARCH MODE]' if search_mode else ''}",
                max(0, width - 1),
                cp(5) | curses.A_BOLD,
            )
            draw_help_line(
                2,
                [
                    ("↑/↓,J/K", "Move"),
                    ("Space", "Mark"),
                    ("A", "Toggle Filtered"),
                    ("/", "Search"),
                    ("D", "Delete"),
                    ("R", "Refresh"),
                    ("P", "Repo Picker"),
                    ("Q", "Exit"),
                ],
            )

            end = min(len(rows), offset + list_rows)
            for screen_row, row_idx in enumerate(range(offset, end), start=list_start):
                artifact, score = rows[row_idx]
                marker = "[x]" if artifact.key in selected_keys else "[ ]"
                cursor_mark = ">" if row_idx == cursor else " "
                line = f"{cursor_mark} {row_idx + 1:>4} {marker} {score:6.2f}  {artifact.relative_path}"
                if row_idx == cursor:
                    attr = cp(2) | curses.A_BOLD
                elif artifact.key in selected_keys:
                    attr = cp(3) | curses.A_BOLD
                else:
                    attr = curses.A_NORMAL
                stdscr.addnstr(screen_row, 0, line, max(0, width - 1), attr)

            if search_mode:
                footer = "⌨️  SEARCH MODE: type to filter, Backspace delete, Enter/Esc exit search mode."
            else:
                footer = "⌨️  Press / to start fuzzy finding. Deletion is available only via d."
            stdscr.addnstr(height - 1, 0, footer, max(0, width - 1), cp(1))
            stdscr.refresh()

            key = stdscr.getch()

            if search_mode:
                if key in (10, 13, curses.KEY_ENTER, 27):
                    search_mode = False
                    continue
                if key in (curses.KEY_BACKSPACE, 127, 8):
                    if query:
                        query = query[:-1]
                        cursor = 0
                        offset = 0
                    continue
                if 32 <= key <= 126 and chr(key) != "/":
                    query += chr(key)
                    cursor = 0
                    offset = 0
                continue

            if key in (curses.KEY_UP, ord("k")):
                cursor = max(0, cursor - 1)
                continue
            if key in (curses.KEY_DOWN, ord("j")):
                cursor = min(max(0, len(rows) - 1), cursor + 1)
                continue
            if key == curses.KEY_PPAGE:
                cursor = max(0, cursor - list_rows)
                continue
            if key == curses.KEY_NPAGE:
                cursor = min(max(0, len(rows) - 1), cursor + list_rows)
                continue
            if key == curses.KEY_HOME:
                cursor = 0
                continue
            if key == curses.KEY_END:
                cursor = max(0, len(rows) - 1)
                continue
            if key == ord(" "):
                if rows:
                    item_key = rows[cursor][0].key
                    if item_key in selected_keys:
                        selected_keys.remove(item_key)
                    else:
                        selected_keys.add(item_key)
                continue
            if key in (ord("a"), ord("A")):
                filtered_keys = {artifact.key for artifact, _ in rows}
                if filtered_keys and filtered_keys.issubset(selected_keys):
                    selected_keys -= filtered_keys
                else:
                    selected_keys |= filtered_keys
                continue
            if key == ord("/"):
                search_mode = True
                continue
            if key in (ord("d"), ord("D")):
                selected = [artifact for artifact in artifacts if artifact.key in selected_keys]
                return (query or None), selected, "delete"
            if key in (ord("r"), ord("R")):
                return (query or None), [], "refresh"
            if key in (ord("p"), ord("P")):
                return (query or None), [], "repo"
            if key in (ord("q"), ord("Q"), 27):
                return (query or None), [], "exit"

    try:
        return curses.wrapper(_run)
    except curses.error:
        return initial_query, [], "exit"


def open_repository_picker(
    repositories: list[str],
    initial_filter: str | None,
) -> tuple[str | None, str | None]:
    if not repositories:
        return None, initial_filter
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        # Non-interactive fallback keeps behavior predictable for scripts/CI usage.
        if initial_filter and initial_filter in repositories:
            return initial_filter, initial_filter
        return repositories[0], initial_filter

    def _run(stdscr: curses.window) -> tuple[str | None, str | None]:
        curses.curs_set(0)
        stdscr.keypad(True)
        has_colors = curses.has_colors()
        if has_colors:
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_CYAN, -1)
            curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_CYAN)
            curses.init_pair(3, curses.COLOR_YELLOW, -1)
            curses.init_pair(4, curses.COLOR_MAGENTA, -1)

        def cp(pair: int) -> int:
            return curses.color_pair(pair) if has_colors else curses.A_NORMAL

        def draw_help_line(y: int, items: list[tuple[str, str]]) -> None:
            x = 0
            max_w = max(0, width - 1)
            for idx, (token, desc) in enumerate(items):
                if x >= max_w:
                    break
                token_text = f"[{token}]"
                stdscr.addnstr(y, x, token_text, max_w - x, cp(1) | curses.A_BOLD)
                x += len(token_text)
                if x >= max_w:
                    break
                stdscr.addnstr(y, x, f" {desc}", max_w - x, cp(3))
                x += 1 + len(desc)
                if idx < len(items) - 1 and x < max_w:
                    sep = " | "
                    stdscr.addnstr(y, x, sep, max_w - x, cp(4))
                    x += len(sep)

        query = initial_filter or ""
        search_mode = False
        cursor = 0
        offset = 0

        while True:
            rows = rank_repositories(repositories, query or None)
            if cursor >= len(rows):
                cursor = max(0, len(rows) - 1)
            if cursor < offset:
                offset = cursor

            stdscr.erase()
            height, width = stdscr.getmaxyx()
            list_start = 3
            list_rows = max(4, height - 6)

            if cursor >= offset + list_rows:
                offset = cursor - list_rows + 1
            if offset < 0:
                offset = 0

            header = f"🗂️ Repository Picker  📦 {len(rows)}/{len(repositories)} visible"
            stdscr.addnstr(0, 0, header, max(0, width - 1), cp(1) | curses.A_BOLD)
            stdscr.addnstr(
                1,
                0,
                f"🔎 Filter: {query or '*'}  {'[SEARCH MODE]' if search_mode else ''}",
                max(0, width - 1),
                cp(4) | curses.A_BOLD,
            )
            draw_help_line(
                2,
                [
                    ("↑/↓,J/K", "Move"),
                    ("Enter", "Select"),
                    ("/", "Search"),
                    ("Backspace", "Edit"),
                    ("Esc/Q", "Exit"),
                ],
            )

            end = min(len(rows), offset + list_rows)
            for screen_row, row_idx in enumerate(range(offset, end), start=list_start):
                repo, score = rows[row_idx]
                cursor_mark = ">" if row_idx == cursor else " "
                line = f"{cursor_mark} {row_idx + 1:>4} {score:6.2f}  {repo}"
                attr = (cp(2) | curses.A_BOLD) if row_idx == cursor else curses.A_NORMAL
                stdscr.addnstr(screen_row, 0, line, max(0, width - 1), attr)

            footer = "Pick repository first. Search starts only after pressing /."
            stdscr.addnstr(height - 1, 0, footer, max(0, width - 1), cp(1))
            stdscr.refresh()

            key = stdscr.getch()
            if search_mode:
                if key in (10, 13, curses.KEY_ENTER, 27):
                    search_mode = False
                    continue
                if key in (curses.KEY_BACKSPACE, 127, 8):
                    if query:
                        query = query[:-1]
                        cursor = 0
                        offset = 0
                    continue
                if 32 <= key <= 126 and chr(key) != "/":
                    query += chr(key)
                    cursor = 0
                    offset = 0
                continue

            if key in (curses.KEY_UP, ord("k")):
                cursor = max(0, cursor - 1)
                continue
            if key in (curses.KEY_DOWN, ord("j")):
                cursor = min(max(0, len(rows) - 1), cursor + 1)
                continue
            if key in (10, 13, curses.KEY_ENTER):
                if not rows:
                    continue
                return rows[cursor][0], (query or None)
            if key == ord("/"):
                search_mode = True
                continue
            if key in (ord("q"), ord("Q"), 27):
                return None, (query or None)

    try:
        return curses.wrapper(_run)
    except curses.error:
        if initial_filter and initial_filter in repositories:
            return initial_filter, initial_filter
        return repositories[0], initial_filter


def search_with_feedback(
    client: ArtifactoryClient,
    config: SearchConfig,
) -> tuple[list[tuple[Artifact, float]], int]:
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as progress:
        task = progress.add_task("Searching artifacts...", total=None)
        artifacts = client.aql_search(
            repository=config.repository,
            query=config.query,
            max_results=config.max_results,
        )
        progress.update(task, completed=True)
    return rank_artifacts(artifacts, query=config.query, min_score=config.min_score), len(artifacts)


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
                    f"[red]Failed ({response.status_code}):[/red] {artifact.display_name}\n"
                    f"[red]Response:[/red] {response.text.strip() or '-'}"
                )
        progress.update(task, completed=True)

    if failures:
        console.print(Panel.fit(f"[red]Deletion finished with {failures} failure(s).[/red]", title="Result"))
        return 1

    console.print(Panel.fit("[bold green]Deletion completed successfully.[/bold green]"))
    return 0


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
        console.print(Panel.fit(f"[red]Failed to fetch repositories.[/red]\nStatus: {status}\nResponse: {body}", title="API Error"))
        return 1
    except requests.RequestException as exc:
        console.print(Panel.fit(f"[red]Network/API error:[/red] {exc}", title="Request Error"))
        return 1

    if not repositories:
        console.print(Panel.fit("[red]No repositories returned by Artifactory.[/red]", title="Repository Error"))
        return 1

    initial_repo_filter = args.repository if args.repository else None
    picked_repo, picked_filter = open_repository_picker(repositories, initial_repo_filter)
    if not picked_repo:
        console.print("[yellow]No repository selected. Exiting.[/yellow]")
        return 0
    repository = validate_repository(picked_repo)

    config = SearchConfig(
        repository=repository,
        query=validate_query(args.query) or validate_query(picked_filter),
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
            console.print(Panel.fit(f"[red]Search failed.[/red]\nStatus: {status}\nResponse: {body}", title="API Error"))
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
            picked_repo, picked_filter = open_repository_picker(repositories, config.repository)
            if picked_repo:
                config.repository = validate_repository(picked_repo)
                config.query = validate_query(picked_filter)
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


def build_search_config_from_args(args: argparse.Namespace) -> SearchConfig:
    return SearchConfig(
        repository=validate_repository(args.repository),
        query=validate_query(args.query),
        max_results=validate_max_results(args.max_results),
        min_score=validate_min_score(float(args.min_score)),
    )


def run_search_command(client: ArtifactoryClient, config: SearchConfig) -> int:
    console.print(
        Panel.fit(
            "[bold yellow]JFrog Artifact Manager[/bold yellow]\n"
            "[white]Mode: search[/white]",
        )
    )
    try:
        results, _ = search_with_feedback(client, config)
    except requests.HTTPError as exc:
        response = exc.response
        status = response.status_code if response is not None else "?"
        body = response.text.strip() if response is not None else str(exc)
        console.print(Panel.fit(f"[red]Search failed.[/red]\nStatus: {status}\nResponse: {body}", title="API Error"))
        return 1
    except requests.RequestException as exc:
        console.print(Panel.fit(f"[red]Network/API error:[/red] {exc}", title="Request Error"))
        return 1

    print_results(results=results, max_results=config.max_results)
    return 0


def run_delete_command(client: ArtifactoryClient, args: argparse.Namespace) -> int:
    config = build_search_config_from_args(args)
    console.print(
        Panel.fit(
            "[bold yellow]JFrog Artifact Manager[/bold yellow]\n"
            "[white]Mode: delete[/white]",
        )
    )
    try:
        results, _ = search_with_feedback(client, config)
    except requests.HTTPError as exc:
        response = exc.response
        status = response.status_code if response is not None else "?"
        body = response.text.strip() if response is not None else str(exc)
        console.print(Panel.fit(f"[red]Search failed.[/red]\nStatus: {status}\nResponse: {body}", title="API Error"))
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


def main() -> int:
    args = parse_args()
    base_url = validate_base_url(get_env_or_exit("ARTIFACTORY_BASE_URL"))
    user = get_env_or_exit("ARTIFACTORY_USER")
    api_key = get_env_or_exit("ARTIFACTORY_API_KEY")
    timeout = get_env_int_or_default("ARTIFACTORY_TIMEOUT", default_value=20)
    client = ArtifactoryClient(base_url, user, api_key, timeout=timeout)

    try:
        if args.command == "search":
            config = build_search_config_from_args(args)
            return run_search_command(client, config)
        if args.command == "delete":
            return run_delete_command(client, args)
        return run_tui(client, args)
    except ValueError as exc:
        console.print(f"[red]Input error:[/red] {exc}")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation interrupted.[/yellow]")
        sys.exit(130)
