from __future__ import annotations

from collections import OrderedDict

from bumpkin.integrations.github.persistence import ReleaseBacklogItem

_SECTION_BY_LABEL = {
    "MAJOR": "Breaking Changes",
    "MINOR": "Features",
    "PATCH": "Fixes",
    "NO_BUMP": "Maintenance",
}
_SECTION_ORDER = ("Breaking Changes", "Features", "Fixes", "Maintenance")


def _normalize_label(label: str) -> str | None:
    normalized = label.strip().upper().replace("-", "_").replace(" ", "_")
    if normalized == "NOBUMP":
        normalized = "NO_BUMP"
    return normalized if normalized in _SECTION_BY_LABEL else None


def _section_for_item(item: ReleaseBacklogItem) -> str:
    normalized = _normalize_label(item.recommended_label)
    return _SECTION_BY_LABEL.get(normalized or "", "Maintenance")


def _format_author(author_login: str | None) -> str:
    normalized = (author_login or "").strip()
    return f"@{normalized}" if normalized else "unknown author"


def _format_item_title(item: ReleaseBacklogItem) -> str:
    title = (item.pull_request_title or "").strip()
    if title:
        return title.rstrip(".")
    summary = (item.release_summary or "").strip()
    if summary:
        return summary.rstrip(".")
    return f"Release item from PR #{item.pull_request_number}"


def _format_item_link(item: ReleaseBacklogItem) -> str:
    url = (item.pull_request_url or "").strip()
    if not url:
        return f"PR #{item.pull_request_number}"
    return f"[PR #{item.pull_request_number}]({url})"


def render_release_notes(
    *,
    tag_name: str,
    items: list[ReleaseBacklogItem],
    current_version: str | None = None,
    next_version: str | None = None,
    release_label: str | None = None,
) -> str:
    normalized_tag = tag_name.strip() or "release"
    grouped: OrderedDict[str, list[ReleaseBacklogItem]] = OrderedDict(
        (section, []) for section in _SECTION_ORDER
    )
    contributors: list[str] = []
    seen_contributors: set[str] = set()

    for item in items:
        section = _section_for_item(item)
        grouped.setdefault(section, []).append(item)
        author = (item.pull_request_author_login or "").strip()
        if author and author not in seen_contributors:
            seen_contributors.add(author)
            contributors.append(author)

    lines: list[str] = [f"# {normalized_tag}"]
    if release_label:
        lines.append("")
        lines.append(f"Release type: {release_label.upper()}")
    if current_version and next_version:
        lines.append(f"Base version: v{current_version}")
        lines.append(f"Next version: v{next_version}")
    lines.append(f"Included PRs: {len(items)}")

    for section in _SECTION_ORDER:
        section_items = grouped.get(section, [])
        if not section_items:
            continue
        lines.extend(["", f"## {section}"])
        for item in section_items:
            link = _format_item_link(item)
            author = _format_author(item.pull_request_author_login)
            title = _format_item_title(item)
            lines.append(f"- {link} by {author}: {title}")

    if contributors:
        lines.extend(["", "## Contributors"])
        lines.append(", ".join(f"@{author}" for author in contributors))

    return "\n".join(lines).strip() + "\n"


__all__ = ["render_release_notes"]
