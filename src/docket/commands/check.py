"""docket check: validate the context vault; exit 1 on any problem."""

from __future__ import annotations

from collections import defaultdict

from docket import frontmatter as fm
from docket import gitinfo
from docket.blocking import GATE, Blocking, idle_repos, repo_blocking, resolve_repos
from docket.config import Config
from docket.notes import (
    Problem,
    anchor_index,
    has_no_gate,
    is_scaffold,
    is_unjudged,
    load_records,
    overdue_gate,
    project_id,
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


def triage_warnings(cfg: Config) -> list[str]:
    """Two classes of record that need a human, each a WARN and never a FAIL:
    unjudged (Completed, verdict still pending) and no gate (In Progress, gate
    empty). Records with `kind: scaffold` are in neither class.
    """
    records, _ = load_records(cfg.context)
    unjudged = sum(1 for record in records if is_unjudged(record))
    no_gate = sum(1 for record in records if has_no_gate(record))
    lines = []
    if unjudged:
        lines.append(f"{unjudged} records unjudged — Completed, verdict still pending")
    if no_gate:
        lines.append(f"{no_gate} records have no gate — In Progress, gate empty")
    return lines


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def uncommitted_work_warnings(cfg: Config) -> list[str]:
    """A Completed record whose branch is checked out in a repo with uncommitted
    paths. `idea import` marks a record Completed when its branch tip is
    contained in main, which is also what a branch that never received a commit
    looks like: the record's actual work may be sitting uncommitted in the tree.
    Repo-wide dirt says nothing about a record whose branch is not checked out,
    so only the checked-out branch's record can fire. Scaffold records are
    skipped. Never a FAIL.
    """
    records, _ = load_records(cfg.context)
    lines = []
    for repo in resolve_repos(cfg):
        if not repo.has_git:
            continue
        head = gitinfo.current_branch(repo.path)
        if head is None:
            continue
        pid = project_id(repo.path)
        owner = next(
            (
                r
                for r in records
                if r.status == "Completed"
                and r.project == pid
                and r.docket_id
                and not is_scaffold(r)
                and fm.get_field(r.fields, "branch") == head
            ),
            None,
        )
        if owner is None:
            continue
        paths = gitinfo.dirty_paths(repo.path)
        if not paths:
            continue
        lines.append(
            f"{repo.name} — {owner.docket_id} is Completed but its branch {head} "
            f"is checked out with {_plural(len(paths), 'path')} uncommitted"
        )
    return lines


def run_check(cfg: Config) -> tuple[str, int]:
    problems, count = find_problems(cfg)
    warnings = [w.message for w in find_warnings(cfg)]
    warnings = triage_warnings(cfg) + uncommitted_work_warnings(cfg) + warnings
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
