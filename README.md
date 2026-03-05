# lazyjfrog

`lazyfrog.py` is a terminal tool for browsing and deleting JFrog Artifactory artifacts.
It supports:

- interactive TUI workflow (`tui`, default)
- non-interactive search (`search`)
- non-interactive delete with explicit selection (`delete`)

## Requirements

- Python `3.14+`
- Python packages:
  - `requests`
  - `rich`

## Configuration (Environment Variables)

All connection/authentication settings are provided through environment variables:

- `ARTIFACTORY_BASE_URL` (required), e.g. `https://example.jfrog.io/artifactory`
- `ARTIFACTORY_USER` (required)
- `ARTIFACTORY_API_KEY` (required)
- `ARTIFACTORY_TIMEOUT` (optional, default: `20`)

## Usage

Run TUI (default mode):

```bash
./lazyfrog.py
```

Run explicit TUI:

```bash
./lazyfrog.py tui
```

Search in a repository:

```bash
./lazyfrog.py search --repository my-repo --query app --max-results 300 --min-score 40
```

Delete selected results:

```bash
./lazyfrog.py delete --repository my-repo --query app --select "1-3,8" --dry-run
```

Selection syntax supports comma-separated indexes/ranges and `all`:

- `1,2,9`
- `1-4,8`
- `all`

## Safety

- search and deletion are always scoped to one repository
- delete flow shows a plan before sending requests
- confirmation is required unless `--yes` is provided
- `--dry-run` previews deletions without deleting anything
