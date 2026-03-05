import argparse
import sys

from lazyfrog_app.cli import parse_args
from lazyfrog_app.client import ArtifactoryClient
from lazyfrog_app.commands import (
    build_search_config_from_args,
    run_delete_command,
    run_search_command,
)
from lazyfrog_app.config import (
    ensure_python_version,
    get_env_int_or_default,
    get_env_or_exit,
    validate_base_url,
)
from lazyfrog_app.console import console
from lazyfrog_app.tui import run_tui


def build_client_from_env() -> ArtifactoryClient:
    base_url = validate_base_url(get_env_or_exit("ARTIFACTORY_BASE_URL"))
    user = get_env_or_exit("ARTIFACTORY_USER")
    api_key = get_env_or_exit("ARTIFACTORY_API_KEY")
    timeout = get_env_int_or_default("ARTIFACTORY_TIMEOUT", default_value=20)
    return ArtifactoryClient(base_url, user, api_key, timeout=timeout)


def run(args: argparse.Namespace) -> int:
    client = build_client_from_env()
    if args.command == "search":
        config = build_search_config_from_args(args)
        return run_search_command(client, config)
    if args.command == "delete":
        return run_delete_command(client, args)
    return run_tui(client, args)


def main() -> int:
    ensure_python_version()
    args = parse_args()
    try:
        return run(args)
    except ValueError as exc:
        console.print(f"[red]Input error:[/red] {exc}")
        return 1


def main_with_exit() -> None:
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation interrupted.[/yellow]")
        sys.exit(130)
