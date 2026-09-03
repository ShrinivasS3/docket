"""docket capture: append a dated bullet to the scratch block of Dashboard.md."""

from __future__ import annotations

import re

from docket.config import Config, DocketError
from docket.fsio import read_text, write_text
from docket.markers import Doc
from docket.notes import today

BLOCK = "scratch"
# `- 2026-09-03: text` with an optional age annotation ` · 3d` added by dash.
BULLET = re.compile(r"^- (\d{4}-\d{2}-\d{2}): (.*?)(?: · (\d+)d)?$")


def format_bullet(date_text: str, text: str, age: int | None = None) -> str:
    line = f"- {date_text}: {text}"
    return f"{line} · {age}d" if age is not None else line


def run_capture(cfg: Config, text: str, *, dry_run: bool = False) -> str:
    text = " ".join(text.split())
    if not text:
        raise DocketError("capture text is empty")
    path = cfg.dashboard
    if not path.is_file():
        raise DocketError(f"dashboard not found: {path}")

    doc = Doc.from_text(read_text(path))
    created = doc.ensure_block_after_rule(BLOCK)
    stamp = today().isoformat()
    for line in doc.block_lines(BLOCK) or []:
        match = BULLET.match(line)
        if match and (match.group(1), match.group(2)) == (stamp, text):
            return f"unchanged  {path.name}: already captured today"
    doc.append_to_block(BLOCK, [format_bullet(stamp, text)])

    prefix = "[dry-run] " if dry_run else ""
    write_text(cfg, path, doc.to_text(), dry_run=dry_run)
    note = " (created scratch markers)" if created else ""
    return f"{prefix}captured  {path.name}: {format_bullet(stamp, text)}{note}"
