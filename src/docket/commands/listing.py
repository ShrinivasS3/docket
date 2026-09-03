"""docket list: tabulate records in the context vault with optional filters."""

from __future__ import annotations

from docket import frontmatter as fm
from docket.config import Config
from docket.notes import load_records

COLUMNS = ("docket_id", "category", "project", "status", "title")


def _norm(value: str | None) -> str:
    return fm.link_name(value).lower() if value else ""


def run_list(
    cfg: Config,
    *,
    category: str | None = None,
    status: str | None = None,
    project: str | None = None,
) -> str:
    records, _ = load_records(cfg.context)
    rows = []
    for record in records:
        if record.docket_id is None:
            continue
        if category and _norm(record.category) != _norm(category):
            continue
        if status and _norm(record.status) != _norm(status):
            continue
        if project and _norm(record.project) != _norm(project):
            continue
        rows.append(
            (
                record.docket_id,
                record.category or "",
                record.project or "",
                record.status or "",
                record.title,
            )
        )
    rows.sort(key=lambda row: row[0].lower())
    if not rows:
        return "(no records)"
    widths = [
        max(len(str(row[i])) for row in (COLUMNS, *rows)) for i in range(len(COLUMNS))
    ]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    lines = [fmt.format(*COLUMNS).rstrip()]
    lines.extend(fmt.format(*row).rstrip() for row in rows)
    return "\n".join(lines)
