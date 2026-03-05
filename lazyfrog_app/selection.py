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
