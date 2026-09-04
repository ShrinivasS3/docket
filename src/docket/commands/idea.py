"""docket idea import: one idea note per git branch, idempotent by docket_id.

Every non-protected branch line names the [branches] pattern that classified it,
and a dry run ends with the list of branches that reached only the "*" fallback:
those carry no namespace meaning and may need a type assigned by hand.
"""

from __future__ import annotations

import datetime as dt
import fnmatch
import re
from dataclasses import dataclass, field
from pathlib import Path

from docket import frontmatter as fm
from docket import gitinfo
from docket.commands.capture import BLOCK as SCRATCH
from docket.commands.capture import BULLET
from docket.config import Config, DocketError
from docket.fsio import read_text, write_text
from docket.markers import Doc, begin_marker
from docket.notes import (
    MANAGED_STATUSES,
    Record,
    is_container,
    load_records,
    next_number,
    project_id,
    resolve_repo,
    slugify,
    titleize,
    to_date,
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


def import_ideas(
    cfg: Config, repo_name: str, *, unattended: bool = False, dry_run: bool = False
) -> ImportResult:
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
                **cfg.identity.fields(unattended),
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


def run_idea_import(
    cfg: Config, repo_name: str, *, unattended: bool = False, dry_run: bool = False
) -> str:
    result = import_ideas(cfg, repo_name, unattended=unattended, dry_run=dry_run)
    lines = [plan.line(dry_run) for plan in result.plans]
    prefix = "[dry-run] " if dry_run else ""
    lines.append(prefix + result.summary())
    if dry_run:
        lines.append(prefix + result.fallback_summary())
    return "\n".join(lines)


# --------------------------------------------------------------------------
# docket idea new
# --------------------------------------------------------------------------

KIND_CHOICES = ("exploratory", "scaffold")

NO_GATE = """no gate and no decide-by date — refusing to write the record.

  a hypothesis      --gate "<the result that would refute it>"
  exploratory work  --decide-by <YYYY-MM-DD>

Ask for it; do not pick one.
A gate docket invented is not a gate you committed to, and `docket check` would
wave it through on the day it was supposed to bite."""

# The promotion stub written back over a scratch line: the bullet, then two
# sub-bullets. Matched again on re-run so promoting twice rewrites rather than
# stacks.
_ARROW = re.compile(r"\s*→\s*\[\[[^\]]+\]\]\s*$")
_STUB_PROMOTED = re.compile(r"^\s+- promoted \d{4}-\d{2}-\d{2} · ")
_STUB_SUB = re.compile(r"^\s+- ")


@dataclass
class NewPlan:
    """The outcome of one `idea new`: one record, optionally one scratch line."""

    action: str  # create | update | unchanged
    filename: str
    status: str
    branch: str
    pattern: str
    docket_id: str
    promoted: str = ""
    notes: list[str] = field(default_factory=list)

    def lines(self, dry_run: bool) -> list[str]:
        prefix = "[dry-run] " if dry_run else ""
        out = [
            f"{prefix}{self.action:<9}  {self.filename}  [[{self.status}]]"
            f"  {self.branch}  pattern={self.pattern}"
        ]
        if self.promoted:
            out.append(f"{prefix}promoted   Dashboard.md scratch: {self.promoted}")
        out.extend(f"note: {note}" for note in self.notes)
        return out


def _repo_from_cwd(cfg: Config, start: Path | None = None) -> Path:
    """The repo the idea belongs to: the nearest directory at or above cwd that
    git or docket recognises. `idea new` rides `git checkout -b`, so cwd is the
    only thing that can say which project without asking again."""
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / ".docket.toml").is_file() or (candidate / ".git").exists():
            if is_container(candidate):
                raise DocketError(
                    f"{candidate.name} is a container (container = true in "
                    ".docket.toml): cd into the repo the work is in"
                )
            return candidate
    raise DocketError(
        f"no repository at or above {here} — run `docket idea new` inside the "
        "repo whose branch the idea belongs to"
    )


def _parse_decide_by(value: str | None) -> dt.date | None:
    if value is None:
        return None
    try:
        return dt.date.fromisoformat(value.strip())
    except ValueError as exc:
        raise DocketError(f"--decide-by {value!r} is not a YYYY-MM-DD date") from exc


def _parse_inherits(value: str | None) -> list[str]:
    if value is None:
        return []
    ids = [item.strip() for item in value.split(",") if item.strip()]
    bad = [item for item in ids if not re.fullmatch(r"G\d+", item)]
    if bad:
        raise DocketError(
            f"--inherits takes finding ids like G0004, not: {', '.join(bad)}"
        )
    if not ids:
        raise DocketError("--inherits is empty")
    return ids


def _scratch_text(line: str) -> tuple[str, str] | None:
    """(date, text) of a scratch bullet with the age suffix and any previous
    promotion arrow stripped, or None when the line is not a bullet."""
    match = BULLET.match(line)
    if match is None:
        return None
    return match.group(1), _ARROW.sub("", match.group(2)).rstrip()


def _find_scratch_line(lines: list[str], query: str) -> int:
    """Index of the one scratch bullet `query` names. Exact text first, then a
    unique case-insensitive substring; anything else is an error, because
    promoting the wrong line edits a file the user did not look at."""
    needle = " ".join(query.split())
    exact, partial = [], []
    for idx, line in enumerate(lines):
        found = _scratch_text(line)
        if found is None:
            continue
        text = found[1]
        if text == needle:
            exact.append(idx)
        elif needle.lower() in text.lower():
            partial.append(idx)
    hits = exact or partial
    if not hits:
        raise DocketError(
            f"no scratch line matching {needle!r} in the Dashboard scratch block"
        )
    if len(hits) > 1:
        shown = "\n".join(f"  {lines[i].strip()}" for i in hits)
        raise DocketError(
            f"{len(hits)} scratch lines match {needle!r} — be more specific:\n{shown}"
        )
    return hits[0]


def _stub(
    date_text: str,
    text: str,
    *,
    filename: str,
    docket_id: str,
    branch: str,
    gate: str,
    gate_date: dt.date | None,
    now: dt.date,
) -> list[str]:
    """The three lines a promoted scratch line becomes: the original bullet with
    a link appended, then who it became and what would settle it."""
    detail = f"gate: {gate}" if gate else ""
    if gate_date is not None:
        stamp = f"decide by: {gate_date.isoformat()}"
        detail = f"{detail} · {stamp}" if detail else stamp
    return [
        f"- {date_text}: {text} → [[{Path(filename).stem}]]",
        f"  - promoted {now.isoformat()} · {docket_id} · {branch}",
        f"  - {detail}".rstrip(),
    ]


@dataclass
class Scratch:
    """A located scratch line, held open so the record can quote it before the
    stub is written back. Marker region only: the block's lines are the only
    thing read, and the only thing rewritten."""

    doc: Doc
    lines: list[str]
    index: int
    date_text: str
    text: str


def _locate_scratch(cfg: Config, query: str) -> Scratch:
    """Find the line to promote. Read-only, and run before any write, so a query
    that names nothing refuses without having created a record first."""
    path = cfg.dashboard
    if not path.is_file():
        raise DocketError(f"dashboard not found: {path}")
    doc = Doc.from_text(read_text(path))
    lines = doc.block_lines(SCRATCH)
    if lines is None:
        raise DocketError(
            f"no {begin_marker(SCRATCH)} block in {path.name} — nothing to promote"
        )
    idx = _find_scratch_line(lines, query)
    date_text, text = _scratch_text(lines[idx])  # type: ignore[misc]
    return Scratch(doc, lines, idx, date_text, text)


def _apply_stub(
    scratch: Scratch,
    *,
    filename: str,
    docket_id: str,
    branch: str,
    gate: str,
    gate_date: dt.date | None,
    now: dt.date,
) -> str:
    """Swap the located line (and any stub it already carries) for a fresh stub.
    Returns its first line. Re-running rewrites the stub rather than stacking."""
    # Consume the previous stub's tail, and only that: it is anchored on the
    # `promoted` line, so hand-written sub-bullets under a line that was never
    # promoted are never eaten.
    end = scratch.index + 1
    if end < len(scratch.lines) and _STUB_PROMOTED.match(scratch.lines[end]):
        end += 1
        if end < len(scratch.lines) and _STUB_SUB.match(scratch.lines[end]):
            end += 1
    stub = _stub(
        scratch.date_text,
        scratch.text,
        filename=filename,
        docket_id=docket_id,
        branch=branch,
        gate=gate,
        gate_date=gate_date,
        now=now,
    )
    scratch.lines[scratch.index : end] = stub
    scratch.doc.replace_block(SCRATCH, scratch.lines)
    return stub[0]


QUOTE_HEAD = "From the Dashboard scratch block, captured "


def _quote_block(date_text: str, text: str) -> list[str]:
    return ["", f"{QUOTE_HEAD}{date_text}:", "", f"> {text}"]


def _seed_branch(cfg: Config, repo: Path, branch: str | None) -> tuple[str, str]:
    """(branch, matched [branches] pattern). The branch name is the seed for the
    title, the slug and the namespace, so everything else follows from it."""
    if branch is None:
        branch = gitinfo.current_branch(repo)
        if branch is None:
            raise DocketError(
                f"no branch checked out in {repo.name} (detached HEAD or no "
                "commits): pass --branch"
            )
    if _is_protected(branch):
        raise DocketError(
            f"{branch} is a protected branch — an idea earns its own branch. "
            "Create one, or pass --branch."
        )
    match = cfg.branch_match(branch)
    if match is None:
        raise DocketError(
            f"no [branches] pattern in {cfg.path} matches {branch} — add one "
            f'with `docket init --namespace "<pattern>"`'
        )
    pattern, kind = match
    if kind != "idea":
        raise DocketError(
            f"{branch} matches {pattern!r} = {kind!r}, not an idea"
            + (" — use `docket gotcha`" if kind == "gotcha" else "")
        )
    return branch, pattern


def _raw(record: Record | None, key: str) -> object:
    return None if record is None else record.fields.get(key)


def _field(record: Record | None, key: str) -> str:
    return "" if record is None else (fm.get_field(record.fields, key) or "")


def _has_gate(record: Record | None) -> bool:
    """A gate already committed to: gate text or a date to decide by."""
    if record is None:
        return False
    return bool(fm.get_field(record.fields, "gate") or record.fields.get("gate_date"))


def new_idea(
    cfg: Config,
    *,
    branch: str | None = None,
    gate: str | None = None,
    decide_by: str | None = None,
    parent: str | None = None,
    inherits: str | None = None,
    from_scratch: str | None = None,
    kind: str | None = None,
    unattended: bool = False,
    cwd: Path | None = None,
    dry_run: bool = False,
) -> NewPlan:
    """File one idea against the branch it lives on. Idempotent by docket_id: a
    second run finds the record by branch and edits it rather than adding one.
    """
    gate_text = " ".join((gate or "").split())
    gate_date = _parse_decide_by(decide_by)
    inherit_ids = _parse_inherits(inherits)
    if kind is not None and kind not in KIND_CHOICES:
        raise DocketError(f"--kind must be one of: {', '.join(KIND_CHOICES)}")

    repo = _repo_from_cwd(cfg, cwd)
    branch, pattern = _seed_branch(cfg, repo, branch)
    pid = project_id(repo)
    now = today()

    # `idea new` files an idea; it does not adjudicate one. Branch-derived state
    # — status, merged — belongs to `idea import`, which reads whole branch
    # histories. A branch cut a second ago has no commits of its own and is
    # therefore indistinguishable from a fast-forward-merged one, so deriving
    # status here would file every new idea as already Completed.
    notes: list[str] = []
    branches = gitinfo.list_branches(repo) if gitinfo.has_git(repo) else {}
    ref = branches.get(branch)
    last_commit = gitinfo.commit_date(repo, ref) if ref is not None else None
    if ref is None:
        notes.append(f"{branch} does not exist in {repo.name} yet")

    records, _ = load_records(cfg.context)
    if parent and not any(r.docket_id == parent for r in records):
        notes.append(f"parent {parent} is not a record in the context vault")
    for finding in inherit_ids:
        if not any(r.docket_id == finding for r in records):
            notes.append(f"inherits {finding} is not a record in the context vault")

    # Located before any write: a --from-scratch that names nothing must refuse
    # without having left a record behind.
    scratch = _locate_scratch(cfg, from_scratch) if from_scratch else None

    record = _existing_by_branch(records, pid).get(branch)
    if not gate_text and gate_date is None and not _has_gate(record):
        # Checked here, not at parse time, so a re-run can inherit the gate the
        # record already carries — but an import stub, whose gate is "", cannot.
        raise DocketError(NO_GATE)
    if record is None:
        plan = _create(
            cfg,
            pid=pid,
            branch=branch,
            pattern=pattern,
            last_commit=last_commit,
            gate_text=gate_text,
            gate_date=gate_date,
            parent=parent,
            inherit_ids=inherit_ids,
            kind=kind,
            scratch=scratch,
            unattended=unattended,
            records=records,
            now=now,
            dry_run=dry_run,
        )
    else:
        plan = _update(
            cfg,
            record,
            branch=branch,
            pattern=pattern,
            gate_text=gate_text,
            gate_date=gate_date,
            parent=parent,
            inherit_ids=inherit_ids,
            kind=kind,
            scratch=scratch,
            unattended=unattended,
            dry_run=dry_run,
        )
    plan.notes = notes

    if scratch is not None:
        # The stub names the gate the record ends up with, not just the one this
        # run typed: a re-run that inherits an existing gate still has to say
        # what would settle the line it is replacing.
        plan.promoted = _apply_stub(
            scratch,
            filename=plan.filename,
            docket_id=plan.docket_id,
            branch=branch,
            gate=gate_text or _field(record, "gate"),
            gate_date=gate_date or to_date(_raw(record, "gate_date")),
            now=now,
        )
        write_text(cfg, cfg.dashboard, scratch.doc.to_text(), dry_run=dry_run)
    return plan


def _create(
    cfg: Config,
    *,
    pid: str,
    branch: str,
    pattern: str,
    last_commit: dt.date | None,
    gate_text: str,
    gate_date: dt.date | None,
    parent: str | None,
    inherit_ids: list[str],
    kind: str | None,
    scratch: Scratch | None,
    unattended: bool,
    records: list[Record],
    now: dt.date,
    dry_run: bool,
) -> NewPlan:
    status = "In Progress"  # an idea you are filing is one you are about to work
    prefix = f"{pid.lower()}-"
    docket_id = f"{prefix}{next_number(records, prefix):04d}"
    slug = slugify(branch.rsplit("/", 1)[-1])
    title = titleize(slug)
    fields = {
        "categories": fm.wikilink(CATEGORY),
        "type": fm.wikilink(pid),
        "status": fm.wikilink(status),
        "docket_id": docket_id,
        "title": title,
        "branch": branch,
        "created": now,
        "last_commit": last_commit if last_commit else "",
        "merged": False,
        "gate": gate_text,
    }
    if gate_date is not None:
        fields["gate_date"] = gate_date
    fields["verdict"] = "pending"
    if kind is not None:
        fields["kind"] = kind
    if parent:
        fields["parent"] = parent
    if inherit_ids:
        fields["inherits"] = inherit_ids
    fields.update(cfg.identity.fields(unattended))

    body = [f"# {title}"]
    if scratch is not None:
        body.extend(_quote_block(scratch.date_text, scratch.text))
    path = cfg.context / f"idea-{docket_id}-{slug}.md"
    text = fm.render(fields) + "\n" + "\n".join(body) + "\n"
    write_text(cfg, path, text, dry_run=dry_run)
    return NewPlan("create", path.name, status, branch, pattern, docket_id)


def _update(
    cfg: Config,
    record: Record,
    *,
    branch: str,
    pattern: str,
    gate_text: str,
    gate_date: dt.date | None,
    parent: str | None,
    inherit_ids: list[str],
    kind: str | None,
    scratch: Scratch | None,
    unattended: bool,
    dry_run: bool,
) -> NewPlan:
    """Re-run against an existing record: only what was supplied this run moves.
    Status, merged and last_commit are `idea import`'s to move, so no status —
    hand-set or managed — is ever overwritten here."""
    fm_text = record.fm_text
    status = record.status or "In Progress"
    if gate_text:
        fm_text = fm.set_field(fm_text, "gate", gate_text)
    if gate_date is not None:
        fm_text = fm.set_field(fm_text, "gate_date", gate_date)
    if kind is not None:
        fm_text = fm.set_field(fm_text, "kind", kind)
    if parent:
        fm_text = fm.set_field(fm_text, "parent", parent)
    if inherit_ids:
        fm_text = fm.set_field(fm_text, "inherits", inherit_ids)
    for key, value in cfg.identity.fields(unattended).items():
        if key not in record.fields:  # the device that wrote it keeps the credit
            fm_text = fm.set_field(fm_text, key, value)

    if scratch is not None and QUOTE_HEAD not in record.body:
        quote = "\n".join(_quote_block(scratch.date_text, scratch.text))
        record.body = record.body.rstrip("\n") + "\n" + quote + "\n"
    changed = write_text(
        cfg, record.path, record.with_frontmatter(fm_text), dry_run=dry_run
    )
    action = "update" if changed else "unchanged"
    docket_id = record.docket_id or ""
    return NewPlan(action, record.path.name, status, branch, pattern, docket_id)


def run_idea_new(cfg: Config, *, dry_run: bool = False, **kwargs) -> str:
    plan = new_idea(cfg, dry_run=dry_run, **kwargs)
    return "\n".join(plan.lines(dry_run))
