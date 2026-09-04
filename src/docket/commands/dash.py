"""docket dash: regenerate the focus block in Dashboard.md and age the scratch lines."""

from __future__ import annotations

import datetime as dt

import yaml

from docket.blocking import all_blocking, idle_repos, resolve_repos
from docket.commands.capture import BULLET, format_bullet
from docket.config import Config, DocketError
from docket.fsio import read_text, write_text
from docket.markers import Doc, begin_marker, end_marker
from docket.notes import to_date, today

FOCUS = "focus"
SCRATCH = "scratch"
IDLE_AFTER_DAYS = 2
DEADLINES_FILE = "deadlines.yaml"


def load_deadlines(cfg: Config) -> list[dict]:
    path = cfg.context / DEADLINES_FILE
    if not path.is_file():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise DocketError(f"{path} is not valid YAML: {exc}") from exc
    if isinstance(data, dict):
        data = data.get("deadlines", [])
    if data is None:
        return []
    if not isinstance(data, list):
        raise DocketError(f"{path}: expected a list of deadlines")
    return [entry for entry in data if isinstance(entry, dict)]


DEADLINE_STATUSES = ("pending", "done", "slipped", "cancelled")


def _deadline_status(entry: dict, venue: str) -> str:
    raw = entry.get("status")
    status = "pending" if raw is None else str(raw).strip().lower()
    if status not in DEADLINE_STATUSES:
        raise DocketError(
            f"{DEADLINES_FILE}: {venue!r} has unknown status {raw!r} "
            f"(expected one of: {', '.join(DEADLINE_STATUSES)})"
        )
    return status


def _deadline_lines(entries: list[dict], now: dt.date) -> list[str]:
    """One line per open (status: pending) deadline, in date order.

    A pending deadline whose date has passed is NOT dropped: it renders as
    OVERDUE, because a hard date that silently vanishes is the one thing this
    list must never hide. Entries marked done, slipped or cancelled are closed
    and never render, whatever their date.
    """
    dated, undated = [], []
    for entry in entries:
        venue = str(entry.get("venue") or entry.get("name") or "?")
        if _deadline_status(entry, venue) != "pending":
            continue
        projects = entry.get("for") or []
        if not isinstance(projects, list):
            projects = [projects]
        suffix = " · ".join(str(p) for p in projects)
        if entry.get("confirmed") is False:
            suffix = f"{suffix} · unconfirmed" if suffix else "unconfirmed"
        when = to_date(entry.get("date"))
        if when is None:
            undated.append((venue, suffix))
            continue
        dated.append(((when - now).days, venue, suffix))
    lines = []
    for days, venue, suffix in sorted(dated):
        stamp = f"`OVERDUE {-days}d`" if days < 0 else f"`{days}d`"
        lines.append(f"{stamp} {venue}" + (f" · {suffix}" if suffix else ""))
    lines.extend(
        f"`?` {venue}" + (f" · {suffix}" if suffix else "") + " · date unknown"
        for venue, suffix in undated
    )
    return lines


def build_focus(cfg: Config, now: dt.date | None = None) -> list[str]:
    now = now or today()
    repos = resolve_repos(cfg)
    blocking = all_blocking(cfg, now, repos=repos)
    idle = idle_repos(cfg, now, repos, after_days=IDLE_AFTER_DAYS)

    lines: list[str] = []
    if blocking:
        cap = cfg.dash.max_blocking
        shown, overflow = blocking[:cap], len(blocking) - min(cap, len(blocking))
        lines.append("> [!danger] Blocking")
        lines.extend(f"> - {item.message}" for item in shown)
        if overflow:
            lines.append(f"> - +{overflow} more — run `docket check`")
    else:
        lines.append("> [!success] Nothing blocking")
    lines.append("")
    lines.append("**Next up**")
    deadlines = _deadline_lines(load_deadlines(cfg), now)
    lines.extend(deadlines or [f"_(no upcoming deadlines in {DEADLINES_FILE})_"])
    lines.append("")
    lines.append("**Idle**")
    cap = cfg.dash.max_idle
    lines.extend(f"`{days}d` {name}" for days, name in idle[:cap])
    if len(idle) > cap:
        lines.append(f"+{len(idle) - cap} more — run `docket check`")
    if not idle:
        lines.append("_(nothing idle)_")
    lines.append("")
    lines.append(f"<sub>generated {now.isoformat()} · `docket dash --md`</sub>")
    return lines


def annotate_scratch(lines: list[str], now: dt.date) -> list[str]:
    """Add or refresh ` · Nd` on every scratch bullet. Order and count unchanged."""
    out = []
    for line in lines:
        match = BULLET.match(line)
        if not match:
            out.append(line)
            continue
        stamp = to_date(match.group(1))
        age = (now - stamp).days if stamp else None
        out.append(format_bullet(match.group(1), match.group(2), age))
    return out


def run_dash(cfg: Config, *, md: bool = False, dry_run: bool = False) -> str:
    now = today()
    focus = build_focus(cfg, now)
    if not md:
        return "\n".join(focus)

    path = cfg.dashboard
    if not path.is_file():
        raise DocketError(f"dashboard not found: {path}")
    doc = Doc.from_text(read_text(path))
    messages = []
    if not doc.replace_block(FOCUS, focus):
        messages.append(
            f"focus block skipped: add {begin_marker(FOCUS)} and "
            f"{end_marker(FOCUS)} to {path.name} to enable it"
        )
    scratch = doc.block_lines(SCRATCH)
    if scratch is not None:
        doc.replace_block(SCRATCH, annotate_scratch(scratch, now))
    changed = write_text(cfg, path, doc.to_text(), dry_run=dry_run)
    prefix = "[dry-run] " if dry_run else ""
    verb = "updated" if changed else "unchanged"
    messages.insert(0, f"{prefix}{verb}  {path.name}")
    if dry_run:
        messages.append("--- focus block ---")
        messages.extend(focus)
    return "\n".join(messages)
