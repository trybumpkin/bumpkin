from __future__ import annotations


def iter_json_object_slices(text: str) -> list[str]:
    """Return balanced JSON object candidates without interpreting their fields."""
    candidates: list[str] = []
    for start in (idx for idx, ch in enumerate(text) if ch == "{"):
        depth = 0
        in_string = False
        escaped = False
        for idx in range(start, len(text)):
            ch = text[idx]
            if in_string:
                if escaped:
                    escaped = False
                    continue
                if ch == "\\":
                    escaped = True
                    continue
                if ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
                continue
            if ch == "{":
                depth += 1
                continue
            if ch == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start : idx + 1])
                    break
    return candidates
