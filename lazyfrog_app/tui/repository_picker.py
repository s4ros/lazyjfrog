import curses
import sys

from lazyfrog_app.scoring import rank_repositories


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
