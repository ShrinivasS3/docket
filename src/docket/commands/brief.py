"""docket brief <project>: a ~200-token plain-text digest assembled from files.

No model call, no network, no writes. Every field degrades on its own: a repo
with no NORTH_STAR.md, no ledger and no ideas still emits a valid brief with
the fields it has. The text is fitted to BUDGET_CHARS (about 250 tokens)
because it is injected into every session start, where anything longer is a
tax rather than a service.

This module has no write path: it imports no write helper, reads files through
Path.read_text, and asks git only through the read-only helpers in gitinfo.
tests/test_brief.py asserts it.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from docket import frontmatter as fm
from docket import gitinfo
from docket.blocking import registered_dirs
from docket.commands.dash import deadline_status, load_deadlines
from docket.config import Config, DocketError
from docket.notes import Record, is_stub, load_records, project_id, to_date, today
from docket.stem import stem

BUDGET_CHARS = 1000  # ~250 tokens at four characters per token
NORTH_STAR = ("NORTH_STAR.md", "docs/NORTH_STAR.md")
LEDGERS = ("experiments/RESULTS.tsv", "docs/RESULTS.tsv", "RESULTS.tsv")
LEDGER_COLUMNS = ("run_id", "run", "idea_id", "idea", "metric", "value")
LABEL_WIDTH = 16
_TOKEN = re.compile(r"[a-z0-9]+")
_RULE = re.compile(r"^(-{3,}|\*{3,}|_{3,})$")  # horizontal rules are not prose

# (claim chars, title chars, list items): tried in order until the text fits.
_FITS = ((220, 48, 3), (120, 36, 2), (60, 24, 1))


def _clip(text: str, width: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1].rstrip() + "…"


def _stems(text: str) -> set[str]:
    return {stem(tok) for tok in _TOKEN.findall(text.lower())}


def resolve_project(cfg: Config, name: str) -> tuple[Path, str]:
    """(repo path, project_id) for a directory name or a project_id."""
    repo = cfg.projects / name
    if repo.is_dir():
        return repo, project_id(repo)
    wanted = name.lower()
    for registered in registered_dirs(cfg):
        if wanted in (registered.name.lower(), project_id(registered).lower()):
            return registered, project_id(registered)
    raise DocketError(f"no project named {name} under {cfg.projects}")


def _short_id(record: Record, pid: str) -> str:
    did = record.docket_id or record.path.stem
    prefix = f"{pid.lower()}-"
    return did[len(prefix) :] if did.lower().startswith(prefix) else did


def standing_claim(repo: Path, width: int) -> str | None:
    """First paragraph of NORTH_STAR.md: frontmatter, headings, comments,
    blockquote asides, horizontal rules and blank lines skipped; wrapped
    lines joined."""
    for rel in NORTH_STAR:
        path = repo / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            _, body = fm.split(text)
        except fm.MalformedFrontmatter:
            body = text
        paragraph: list[str] = []
        for line in body.splitlines():
            stripped = line.strip()
            if (
                not stripped
                or stripped.startswith(("#", "<!--", ">"))
                or _RULE.match(stripped)
            ):
                if paragraph:
                    break
                continue
            paragraph.append(stripped)
        if paragraph:
            return _clip(" ".join(paragraph), width)
    return None


def branch_line(repo: Path) -> str:
    if not gitinfo.has_git(repo):
        return "no git repository"
    try:
        branch = gitinfo.run_git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    except DocketError:
        return "git repository, no commits yet"
    if branch == "HEAD":
        branch = "detached HEAD"
    if not gitinfo.has_remote(repo):
        return f"{branch} · no remote"
    ahead = len(
        gitinfo.run_git(repo, "rev-list", "HEAD", "--not", "--remotes", "--").split()
    )
    pushed = gitinfo.run_git(
        repo, "log", "-1", "--format=%cs", "--remotes", "--"
    ).strip()
    noun = "commit" if ahead == 1 else "commits"
    if not pushed:
        return f"{branch} · {ahead} {noun}, nothing pushed yet"
    return f"{branch} · {ahead} {noun} since last push ({pushed})"


def _ideas(records: list[Record]) -> list[Record]:
    return [r for r in records if r.category == "Ideas"]


def active_idea(records: list[Record], pid: str, branch: str | None, width: int) -> str:
    ideas = _ideas(records)
    pick = None
    if branch:
        pick = next(
            (r for r in ideas if fm.get_field(r.fields, "branch") == branch), None
        )
    if pick is None:
        in_progress = [r for r in ideas if r.status == "In Progress"]
        in_progress.sort(
            key=lambda r: (
                to_date(r.fields.get("last_commit")) or dt.date.min,
                r.docket_id or "",
            ),
            reverse=True,
        )
        pick = in_progress[0] if in_progress else None
    if pick is None:
        return "none"
    gate_date = to_date(pick.fields.get("gate_date"))
    if gate_date:
        gate = f"Gate {gate_date.isoformat()}"
    elif fm.get_field(pick.fields, "gate"):
        gate = "Gate set, no date"
    else:
        gate = "Gate none set"
    verdict = fm.get_field(pick.fields, "verdict")
    tail = f", verdict {verdict}" if verdict and verdict != "pending" else ""
    status = pick.status
    state = f" ({status})" if status and status != "In Progress" else ""
    return f"{_short_id(pick, pid)} — {_clip(pick.title, width)}{state}. {gate}{tail}."


def runs_line(repo: Path, width: int) -> str:
    for rel in LEDGERS:
        path = repo / rel
        if not path.is_file():
            continue
        rows = [
            r
            for r in path.read_text(encoding="utf-8", errors="replace").splitlines()
            if r.strip() and not r.lstrip().startswith("#")  # comment rows
        ]
        if len(rows) < 2:
            return "ledger empty"
        header = [h.strip().lower() for h in rows[0].split("\t")]
        cols = [i for i, h in enumerate(header) if h in LEDGER_COLUMNS] or list(
            range(min(4, len(header)))
        )
        shown = []
        for row in rows[-3:]:
            cells = row.split("\t")
            shown.append(
                _clip(" ".join(cells[i].strip() for i in cols if i < len(cells)), width)
            )
        return "; ".join(shown)
    return "no ledger"


def falsified_line(records: list[Record], pid: str, width: int, limit: int) -> str:
    ideas = _ideas(records)
    items = [r for r in ideas if r.status == "Falsified"]
    items.sort(key=lambda r: r.docket_id or "", reverse=True)
    if not items:
        # "none" would read as "nothing was ever refuted"; say what is unjudged
        stubs = sum(1 for r in ideas if is_stub(r))
        return f"none marked ({stubs} stubs)"
    shown = [f"{_short_id(r, pid)} {_clip(r.title, width)}" for r in items[:limit]]
    more = len(items) - limit
    return "; ".join(shown) + (f"; +{more} more" if more > 0 else "")


def gotcha_line(
    all_records: list[Record], mine: list[Record], pid: str, limit: int
) -> str:
    """Gotchas filed under this project, then gotchas whose scope tags all
    appear in this project's vocabulary (ids, titles, branches, scope tags)."""
    vocab = _stems(pid)
    for record in mine:
        vocab |= _stems(record.title)
        vocab |= _stems(fm.get_field(record.fields, "branch") or "")
        vocab |= _stems(" ".join(str(s) for s in record.fields.get("scope") or []))
    hits: list[tuple[int, str, str]] = []
    for record in all_records:
        if record.category != "Gotchas":
            continue
        did = record.docket_id or record.path.stem
        if (record.project or "").lower() == pid.lower():
            hits.append((0, did, "this project"))
            continue
        scope = record.fields.get("scope") or []
        tags = [str(t) for t in (scope if isinstance(scope, list) else [scope])]
        overlap = [t for t in tags if _stems(t) and _stems(t) <= vocab]
        if overlap:
            hits.append((1, did, ", ".join(overlap[:2])))
    hits.sort()
    if not hits:
        return "none"
    shown = [f"{did} ({why})" for _, did, why in hits[:limit]]
    more = len(hits) - limit
    return "; ".join(shown) + (f"; +{more} more" if more > 0 else "")


def deadline_line(cfg: Config, names: set[str], now: dt.date) -> str:
    best: tuple[int, str, dt.date] | None = None
    best_key: tuple[int, int] = (2, 0)
    for entry in load_deadlines(cfg):
        venue = str(entry.get("venue") or entry.get("name") or "?")
        if deadline_status(entry, venue) != "pending":
            continue
        projects = entry.get("for") or []
        projects = projects if isinstance(projects, list) else [projects]
        if not names & {str(p).lower() for p in projects}:
            continue
        when = to_date(entry.get("date"))
        if when is None:
            continue
        days = (when - now).days
        # nearest upcoming wins; failing that, the most recently missed
        key = (0, days) if days >= 0 else (1, -days)
        if key < best_key:
            best, best_key = (days, venue, when), key
    if best is None:
        return "none"
    days, venue, when = best
    if days == 0:
        return f"{venue} today ({when})"
    if days < 0:
        return f"{venue} {-days}d overdue ({when})"
    return f"{venue} in {days}d ({when})"


def _render(
    cfg: Config, repo: Path, pid: str, now: dt.date, fit: tuple[int, int, int]
) -> str:
    claim_w, title_w, limit = fit
    all_records, _ = load_records(cfg.context)
    mine = [r for r in all_records if (r.project or "").lower() == pid.lower()]
    branch = None
    if gitinfo.has_git(repo):
        try:
            branch = gitinfo.run_git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
        except DocketError:
            branch = None
    rows: list[tuple[str, str | None]] = [
        ("Standing claim:", standing_claim(repo, claim_w)),
        ("Branch:", branch_line(repo)),
        ("Active idea:", active_idea(mine, pid, branch, title_w)),
        ("Last 3 runs:", runs_line(repo, title_w)),
        ("Falsified here:", falsified_line(mine, pid, title_w, limit)),
        ("Gotchas:", gotcha_line(all_records, mine, pid, limit)),
        ("Deadline:", deadline_line(cfg, {pid.lower(), repo.name.lower()}, now)),
    ]
    lines = [f"# {pid} — brief, {now.isoformat()}"]
    lines.extend(
        f"{label:<{LABEL_WIDTH}}{value}" for label, value in rows if value is not None
    )
    return "\n".join(lines)


def run_brief(cfg: Config, name: str, budget: int = BUDGET_CHARS) -> str:
    repo, pid = resolve_project(cfg, name)
    now = today()
    text = ""
    for fit in _FITS:
        text = _render(cfg, repo, pid, now, fit)
        if len(text) <= budget:
            return text
    return text[: budget - 1].rstrip() + "…"
