"""docket check: validate the context vault; exit 1 on any problem."""

from __future__ import annotations

from collections import defaultdict

from docket import frontmatter as fm
from docket.blocking import GATE, Blocking, idle_repos, repo_blocking, resolve_repos
from docket.config import Config
from docket.notes import (
    Problem,
    anchor_index,
    is_stub,
    load_records,
    overdue_gate,
    today,
)

ANCHOR_KEYS = ("categories", "type", "status")


def find_problems(cfg: Config) -> tuple[list[Problem], int]:
    vault = cfg.context
    records, problems = load_records(vault)
    anchors = anchor_index(vault)
    now = today()
    by_id: dict[str, list] = defaultdict(list)

    for record in records:
        for key in ANCHOR_KEYS:
            for name in fm.link_names(record.fields.get(key)):
                if name not in anchors:
                    problems.append(
                        Problem(
                            record.path, f"{key} references missing anchor [[{name}]]"
                        )
                    )
        days = overdue_gate(record, now)
        if days is not None:
            problems.append(
                Problem(
                    record.path,
                    f"gate_date {record.fields.get('gate_date')} passed {days}d ago "
                    "with verdict pending",
                )
            )
        if record.docket_id is not None:
            by_id[record.docket_id].append(record.path)

    for docket_id, paths in sorted(by_id.items()):
        if len(paths) > 1:
            names = ", ".join(p.name for p in paths)
            problems.append(
                Problem(paths[0], f"docket_id {docket_id} collides: {names}")
            )
    return problems, len(records)


def find_warnings(cfg: Config) -> list[Blocking]:
    """Repo-level blockers (unpushed, stale, no git), uncapped. Gate overdue is a
    FAIL already, so it is excluded here. These never change the exit code: a
    pre-push hook that failed because commits are unpushed would be circular.
    """
    now = today()
    found: list[Blocking] = []
    for repo in resolve_repos(cfg):
        found.extend(b for b in repo_blocking(cfg, repo, now) if b.severity != GATE)
    return sorted(found)


def stub_warning(cfg: Config) -> str | None:
    """Import stubs (verdict pending, no gate) are legitimate: a WARN, never a FAIL."""
    records, _ = load_records(cfg.context)
    n = sum(1 for record in records if is_stub(record))
    return f"{n} records are import stubs — title only, no gate" if n else None


def run_check(cfg: Config) -> tuple[str, int]:
    problems, count = find_problems(cfg)
    warnings = [w.message for w in find_warnings(cfg)]
    stubs = stub_warning(cfg)
    if stubs:
        warnings.insert(0, stubs)
    idle = idle_repos(cfg, today())
    lines = [f"FAIL  {p.path.name}: {p.message}" for p in problems]
    lines.extend(f"WARN  {w}" for w in warnings)
    lines.extend(f"IDLE  {name} — {days}d since last commit" for days, name in idle)
    extras = []
    if warnings:
        extras.append(f"{len(warnings)} warning(s)")
    if idle:
        extras.append(f"{len(idle)} idle")
    tail = ", ".join(extras)
    if not problems:
        summary = f"docket check: ok ({count} records)"
        lines.append(f"{summary}, {tail}" if tail else summary)
        return "\n".join(lines), 0
    summary = f"docket check: {len(problems)} problem(s)"
    if tail:
        summary += f", {tail}"
    lines.append(f"{summary} in {count} records")
    return "\n".join(lines), 1
