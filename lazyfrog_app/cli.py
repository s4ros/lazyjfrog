import argparse


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
