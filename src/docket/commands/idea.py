"""docket idea import: one idea note per git branch, idempotent by docket_id.

Every non-protected branch line names the [branches] pattern that classified it,
and a dry run ends with the list of branches that reached only the "*" fallback:
those carry no namespace meaning and may need a type assigned by hand.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field

from docket import frontmatter as fm
from docket import gitinfo
from docket.config import Config, DocketError
from docket.fsio import write_text
from docket.notes import (
    MANAGED_STATUSES,
    Record,
    load_records,
    next_number,
    project_id,
    resolve_repo,
    slugify,
    titleize,
    today,
)

CATEGORY = "Ideas"
PROTECTED = ("main", "master")
PROTECTED_GLOBS = ("worktree-agent-*",)
PARKED_AFTER_DAYS = 90
FALLBACK = "*"


def status_for(merged: bool, age_days: int) -> str:
    if merged:
        return "Completed"
    return "In Progress" if age_days < PARKED_AFTER_DAYS else "Parked"


@dataclass
class Plan:
    branch: str
    action: str  # create | update | unchanged | skip
    filename: str = ""
    status: str = ""
    reason: str = ""
    pattern: str = ""  # the [branches] pattern that matched; "" when protected

    def line(self, dry_run: bool) -> str:
        prefix = "[dry-run] " if dry_run and self.action != "skip" else ""
        if self.action == "skip":
            head = f"skip       {self.branch}  ({self.reason})"
        else:
            head = (
                f"{prefix}{self.action:<9}  {self.filename}"
                f"  [[{self.status}]]  {self.branch}"
            )
        return f"{head}  pattern={self.pattern}" if self.pattern else head


@dataclass
class ImportResult:
    project: str
    branches: int
    plans: list[Plan] = field(default_factory=list)

    @property
    def notes(self) -> int:
        return sum(1 for p in self.plans if p.action != "skip")

    def count(self, action: str) -> int:
        return sum(1 for p in self.plans if p.action == action)

    def summary(self) -> str:
        return (
            f"{self.project}: {self.branches} branches -> {self.notes} notes "
            f"({self.count('create')} create, {self.count('update')} update, "
            f"{self.count('unchanged')} unchanged, {self.count('skip')} skipped)"
        )

    @property
    def fallback(self) -> list[str]:
        """Branches classified only by the "*" fallback: no namespace meaning."""
        return [p.branch for p in self.plans if p.pattern == FALLBACK]

    def fallback_summary(self) -> str:
        names = self.fallback
        if not names:
            return 'fallback "*": none'
        noun = "branch" if len(names) == 1 else "branches"
        return (
            f'fallback "*" ({len(names)} {noun}, no namespace meaning, '
            f"may need a type by hand): {', '.join(names)}"
        )


def _is_protected(name: str) -> bool:
    return name in PROTECTED or any(
        fnmatch.fnmatchcase(name, glob) for glob in PROTECTED_GLOBS
    )


def _existing_by_branch(records: list[Record], pid: str) -> dict[str, Record]:
    found: dict[str, Record] = {}
    for record in records:
        branch = fm.get_field(record.fields, "branch")
        if record.category == CATEGORY and record.project == pid and branch:
            found.setdefault(branch, record)
    return found


def import_ideas(cfg: Config, repo_name: str, *, dry_run: bool = False) -> ImportResult:
    repo = resolve_repo(cfg, repo_name)
    if not gitinfo.has_git(repo):
        raise DocketError(f"{repo} is not a git repository")
    pid = project_id(repo)
    prefix = f"{pid.lower()}-"

    branches = gitinfo.list_branches(repo)
    main = gitinfo.main_ref(repo, branches)
    merged = gitinfo.merged_branches(repo, main)
    records, _ = load_records(cfg.context)
    existing = _existing_by_branch(records, pid)
    now = today()
    result = ImportResult(project=pid, branches=len(branches))

    candidates = []
    for name, ref in branches.items():
        if _is_protected(name):
            result.plans.append(Plan(name, "skip", reason="protected"))
            continue
        match = cfg.branch_match(name)
        if match is None:
            result.plans.append(Plan(name, "skip", reason="no [branches] pattern"))
            continue
        pattern, kind = match
        if kind != "idea":
            result.plans.append(
                Plan(name, "skip", reason=f"kind={kind}", pattern=pattern)
            )
            continue
        candidates.append((gitinfo.commit_date(repo, ref), name, pattern))
    candidates.sort()  # oldest branch gets the lowest number on first import

    number = next_number(records, prefix)
    for last_commit, name, pattern in candidates:
        is_merged = name in merged
        status = status_for(is_merged, (now - last_commit).days)
        record = existing.get(name)
        if record is None:
            docket_id = f"{prefix}{number:04d}"
            number += 1
            slug = slugify(name.rsplit("/", 1)[-1])
            fields = {
                "categories": fm.wikilink(CATEGORY),
                "type": fm.wikilink(pid),
                "status": fm.wikilink(status),
                "docket_id": docket_id,
                "title": titleize(slug),
                "branch": name,
                "created": now,
                "last_commit": last_commit,
                "merged": is_merged,
                "gate": "",
                "verdict": "pending",
            }
            path = cfg.context / f"idea-{docket_id}-{slug}.md"
            text = fm.render(fields) + f"\n# {fields['title']}\n"
            write_text(cfg, path, text, dry_run=dry_run)
            result.plans.append(
                Plan(name, "create", path.name, status, pattern=pattern)
            )
            continue

        fm_text = record.fm_text
        current = record.status
        if current is None or current in MANAGED_STATUSES:
            fm_text = fm.set_field(fm_text, "status", fm.wikilink(status))
        else:
            status = current  # a hand-set status (Falsified, ...) is never clobbered
        fm_text = fm.set_field(fm_text, "merged", is_merged)
        fm_text = fm.set_field(fm_text, "last_commit", last_commit)
        text = record.with_frontmatter(fm_text)
        changed = write_text(cfg, record.path, text, dry_run=dry_run)
        action = "update" if changed else "unchanged"
        result.plans.append(
            Plan(name, action, record.path.name, status, pattern=pattern)
        )
    return result


def run_idea_import(cfg: Config, repo_name: str, *, dry_run: bool = False) -> str:
    result = import_ideas(cfg, repo_name, dry_run=dry_run)
    lines = [plan.line(dry_run) for plan in result.plans]
    prefix = "[dry-run] " if dry_run else ""
    lines.append(prefix + result.summary())
    if dry_run:
        lines.append(prefix + result.fallback_summary())
    return "\n".join(lines)
