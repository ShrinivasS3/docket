"""Thin, read-only git helpers. docket never mutates a repository."""

from __future__ import annotations

import datetime as dt
import os
import subprocess
from pathlib import Path

from docket.config import DocketError


def run_git(repo: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:  # pragma: no cover - git missing entirely
        raise DocketError("git executable not found") from exc
    if proc.returncode != 0:
        raise DocketError(
            f"git {' '.join(args)} failed in {repo}: {proc.stderr.strip()}"
        )
    return proc.stdout


def has_git(path: Path) -> bool:
    return (path / ".git").exists()


def _parse_branch_lines(output: str) -> dict[str, str]:
    """Map branch name -> ref from `git branch -a` output. Local refs win over
    remote ones for the same name. Symbolic refs (HEAD -> x) are dropped.
    """
    names: dict[str, str] = {}
    remote_only: dict[str, str] = {}
    for raw in output.splitlines():
        line = raw[2:] if raw[:2] in ("* ", "+ ", "  ") else raw.strip()
        line = line.strip()
        if not line or " -> " in line or line.startswith("("):
            continue
        if line.startswith("remotes/"):
            parts = line.split("/", 2)
            if len(parts) < 3:
                continue
            remote_only.setdefault(parts[2], f"{parts[1]}/{parts[2]}")
        else:
            names[line] = line
    for name, ref in remote_only.items():
        names.setdefault(name, ref)
    return names


def list_branches(repo: Path) -> dict[str, str]:
    return _parse_branch_lines(run_git(repo, "branch", "-a", "--no-color"))


def main_ref(repo: Path, branches: dict[str, str]) -> str:
    for candidate in ("main", "master"):
        if candidate in branches:
            return branches[candidate]
    raise DocketError(f"no main or master branch in {repo}")


def merged_branches(repo: Path, main: str) -> set[str]:
    output = run_git(repo, "branch", "-a", "--no-color", "--merged", main)
    return set(_parse_branch_lines(output))


def commit_date(repo: Path, ref: str) -> dt.date:
    # Trailing `--` keeps a branch that shares its name with a working-tree path
    # (experiments/foo is both) from being rejected as ambiguous.
    stamp = run_git(repo, "log", "-1", "--format=%ct", ref, "--").strip()
    return dt.datetime.fromtimestamp(int(stamp), tz=dt.UTC).date()


def last_commit_date(repo: Path) -> dt.date | None:
    try:
        return commit_date(repo, "HEAD")
    except DocketError:
        return None


def current_branch(repo: Path) -> str | None:
    """Name of the checked-out branch, or None when HEAD is detached or unborn."""
    try:
        name = run_git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    except DocketError:
        return None
    return None if name in ("", "HEAD") else name


def has_remote(repo: Path) -> bool:
    return bool(run_git(repo, "remote").strip())


def unpushed_commit_dates(repo: Path) -> list[dt.date]:
    """Commit dates reachable from any local branch but from no remote ref."""
    try:
        output = run_git(
            repo, "log", "--format=%ct", "--branches", "--not", "--remotes", "--"
        )
    except DocketError:
        return []  # no commits yet
    return [
        dt.datetime.fromtimestamp(int(stamp), tz=dt.UTC).date()
        for stamp in output.split()
    ]


def dirty_paths(repo: Path) -> list[str]:
    """Every uncommitted path (modified, staged, or untracked), repo-relative."""
    output = run_git(repo, "status", "--porcelain", "-z", "--untracked-files=all")
    entries = output.split("\0")
    paths: list[str] = []
    idx = 0
    while idx < len(entries):
        entry = entries[idx]
        idx += 1
        if len(entry) < 4:
            continue
        paths.append(entry[3:])
        if entry[0] in "RC":  # rename/copy: the next entry is the source path
            idx += 1
    return paths


def oldest_mtime(repo: Path, paths: list[str]) -> dt.date | None:
    """Date of the oldest modification among `paths`; deleted paths are ignored."""
    oldest: dt.date | None = None
    for rel in paths:
        try:
            stamp = os.lstat(repo / rel).st_mtime
        except OSError:
            continue
        when = dt.date.fromtimestamp(stamp)
        if oldest is None or when < oldest:
            oldest = when
    return oldest
