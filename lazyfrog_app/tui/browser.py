import curses
import sys

from lazyfrog_app.models import Artifact
from lazyfrog_app.scoring import rank_artifacts


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
