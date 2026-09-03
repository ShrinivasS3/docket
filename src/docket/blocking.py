"""What is blocking, in severity order. Shared by `dash` (triaged, capped) and
`check` (exhaustive, uncapped). Scoped to repos that carry a .docket.toml.

Severity:
  0  gate_date passed, verdict still pending
  1  commits unpushed for > unpushed_days, or no remote configured
  2  uncommitted paths whose oldest modification is > stale_days old
  3  no git repository at all
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from docket import gitinfo
from docket.config import Config, DocketError
from docket.notes import Record, load_records, overdue_gate, to_date

GATE, UNPUSHED, STALE, NO_GIT = 0, 1, 2, 3


@dataclass(frozen=True, order=True)
class Blocking:
    severity: int
    key: str
    message: str


REGISTRATION_DEPTH = 2  # how far below the projects root a .docket.toml may sit
NESTED_DEPTH = 3  # how far below a registered directory to look for repos
SKIP_DIRS = {
    "node_modules",
    "venv",
    "env",
    "__pycache__",
    "site-packages",
    "build",
    "dist",
    "cdk.out",
}


@dataclass(frozen=True)
class Repo:
    """A resolved repository (or a registered directory with no repo at all)."""

    name: str  # path relative to the projects root, e.g. QuadisPD/QuadisPD-AWS
    path: Path
    has_git: bool


def _children(path: Path) -> list[Path]:
    try:
        return sorted(
            p
            for p in path.iterdir()
            if p.is_dir() and not p.name.startswith(".") and p.name not in SKIP_DIRS
        )
    except OSError:
        return []


def registered_dirs(cfg: Config) -> list[Path]:
    """Directories carrying a .docket.toml, up to REGISTRATION_DEPTH deep."""
    if not cfg.projects.is_dir():
        raise DocketError(f"projects root not found: {cfg.projects}")
    found: list[Path] = []

    def walk(base: Path, depth: int) -> None:
        for child in _children(base):
            if (child / ".docket.toml").is_file():
                found.append(child)
            if depth < REGISTRATION_DEPTH:
                walk(child, depth + 1)

    walk(cfg.projects, 1)
    return found


def _nested_repos(base: Path, depth: int = 1) -> list[Path]:
    """Repos below `base`, not descending into a repo once found."""
    found: list[Path] = []
    for child in _children(base):
        if gitinfo.has_git(child):
            found.append(child)
        elif depth < NESTED_DEPTH:
            found.extend(_nested_repos(child, depth + 1))
    return found


def _name(cfg: Config, path: Path) -> str:
    return path.relative_to(cfg.projects).as_posix()


def _resolve(cfg: Config, registered: Path) -> list[Repo]:
    """Nearest repo root(s) for a registered directory: itself, else the closest
    ancestor below the projects root, else every repo nested beneath it."""
    if gitinfo.has_git(registered):
        return [Repo(_name(cfg, registered), registered, True)]
    parent = registered.parent
    while parent != cfg.projects and parent.is_relative_to(cfg.projects):
        if gitinfo.has_git(parent):
            return [Repo(_name(cfg, parent), parent, True)]
        parent = parent.parent
    nested = _nested_repos(registered)
    if nested:
        return [Repo(_name(cfg, p), p, True) for p in nested]
    return [Repo(_name(cfg, registered), registered, False)]


def resolve_repos(cfg: Config) -> list[Repo]:
    """Every distinct repo reachable from a .docket.toml, sorted by name."""
    seen: dict[Path, Repo] = {}
    for registered in registered_dirs(cfg):
        for repo in _resolve(cfg, registered):
            seen.setdefault(repo.path, repo)
    return sorted(seen.values(), key=lambda r: r.name.lower())


def idle_repos(
    cfg: Config, now: dt.date, repos: list[Repo] | None = None, after_days: int = 2
) -> list[tuple[int, str]]:
    """(days idle, name) for repos quiet for more than `after_days`, most idle first."""
    idle = []
    for repo in repos if repos is not None else resolve_repos(cfg):
        if not repo.has_git:
            continue
        last = gitinfo.last_commit_date(repo.path)
        if last is None:
            continue
        days = (now - last).days
        if days > after_days:
            idle.append((days, repo.name))
    idle.sort(key=lambda item: (-item[0], item[1].lower()))
    return idle


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def repo_blocking(cfg: Config, repo: Repo, now: dt.date) -> list[Blocking]:
    name = repo.name
    key = name.lower()
    if not repo.has_git:
        return [Blocking(NO_GIT, key, f"{name} — no git repository")]
    found: list[Blocking] = []
    repo = repo.path  # type: ignore[assignment]

    if not gitinfo.has_remote(repo):
        found.append(Blocking(UNPUSHED, key, f"{name} — no remote configured"))
    else:
        dates = gitinfo.unpushed_commit_dates(repo)
        if dates:
            age = (now - min(dates)).days
            if age > cfg.dash.unpushed_days:
                found.append(
                    Blocking(
                        UNPUSHED,
                        key,
                        f"{name} — {_plural(len(dates), 'unpushed commit')}, "
                        f"oldest {age}d",
                    )
                )

    paths = gitinfo.dirty_paths(repo)
    oldest = gitinfo.oldest_mtime(repo, paths)
    if oldest is not None:
        age = (now - oldest).days
        if age > cfg.dash.stale_days:
            found.append(
                Blocking(
                    STALE,
                    key,
                    f"{name} — {_plural(len(paths), 'uncommitted path')}, "
                    f"oldest {age}d",
                )
            )
    return found


def gate_blocking(records: list[Record], now: dt.date) -> list[Blocking]:
    found = []
    for record in records:
        days = overdue_gate(record, now)
        if days is None:
            continue
        label = record.docket_id or record.path.stem
        gate_date = to_date(record.fields.get("gate_date"))
        found.append(
            Blocking(
                GATE,
                label.lower(),
                f"{label} — gate {gate_date} passed {days}d ago, verdict pending",
            )
        )
    return found


def all_blocking(
    cfg: Config,
    now: dt.date,
    records: list[Record] | None = None,
    repos: list[Repo] | None = None,
) -> list[Blocking]:
    if records is None:
        records, _ = load_records(cfg.context)
    if repos is None:
        repos = resolve_repos(cfg)
    found = gate_blocking(records, now)
    for repo in repos:
        found.extend(repo_blocking(cfg, repo, now))
    return sorted(found)
