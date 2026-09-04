"""docket gotcha: write gotcha-X<NNNN>-<slug>.md into the context vault."""

from __future__ import annotations

import re
import sys

from docket import frontmatter as fm
from docket.config import Config, DocketError
from docket.fsio import write_text
from docket.notes import anchor_index, load_records, next_number, slugify, today

CATEGORY = "Gotchas"
ID_PREFIX = "X"


def normalize_note(note: str | None) -> str | None:
    """Collapse whitespace inside paragraphs, keep paragraph breaks. None if empty."""
    if note is None:
        return None
    paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", note.strip())]
    return "\n\n".join(p for p in paragraphs if p) or None


def render_gotcha(fields: dict, note: str | None = None) -> str:
    """Frontmatter plus the generated body: title, Cause, Fix, then an optional
    Note section. The note lives in the body only."""
    body = (
        f"\n# {fields['symptom']}\n\n**Cause.** {fields['cause']}\n\n"
        f"**Fix.** {fields['fix']}\n"
    )
    if note:
        body += f"\n**Note.** {note}\n"
    return fm.render(fields) + body


def run_gotcha(
    cfg: Config,
    *,
    symptom: str,
    cause: str,
    fix: str,
    scope: str,
    project: str,
    note: str | None = None,
    dry_run: bool = False,
) -> str:
    symptom, cause, fix = (" ".join(s.split()) for s in (symptom, cause, fix))
    note = normalize_note(note)
    project = project.strip()
    if not symptom:
        raise DocketError("--symptom is required and cannot be empty")
    if not project:
        raise DocketError("--project is required and cannot be empty")
    scope_list = [item.strip() for item in scope.split(",") if item.strip()]

    vault = cfg.context
    records, _ = load_records(vault)
    for record in records:
        if (
            record.category == CATEGORY
            and record.project == project
            and fm.get_field(record.fields, "symptom") == symptom
        ):
            return f"unchanged  {record.path.name}: gotcha already recorded"

    anchors = anchor_index(vault)
    for name in (CATEGORY, project):
        if name not in anchors:
            print(
                f"warning: anchor note {name}.md does not exist in {vault}; "
                "docket check will flag this note until it is created",
                file=sys.stderr,
            )

    docket_id = f"{ID_PREFIX}{next_number(records, ID_PREFIX):04d}"
    fields = {
        "categories": fm.wikilink(CATEGORY),
        "type": fm.wikilink(project),
        "docket_id": docket_id,
        "symptom": symptom,
        "cause": cause,
        "fix": fix,
        "scope": scope_list,
        "created": today(),
    }
    path = vault / f"gotcha-{docket_id}-{slugify(symptom, 50)}.md"
    prefix = "[dry-run] " if dry_run else ""
    write_text(cfg, path, render_gotcha(fields, note), dry_run=dry_run)
    return f"{prefix}created  {path.name}"
