"""docket init: wire one repo into docket, and `--check`, which only reports.

Every step is idempotent and independently skipped when it is already correct,
so running init on a hand-wired repo is a no-op rather than a rewrite. The two
modes share one list of steps: `--check` runs each step with `write=False`, and
a step in that mode may not touch the filesystem, git, or config.toml. That is
what keeps the report from drifting away from what init would actually do.

The blob audit runs before the remote step on purpose. GitHub hard-blocks a
100 MB file and the fix after the fact is history surgery, so a repo carrying a
file over the limit is refused a remote rather than pushed and repaired.

Set DOCKET_NO_REMOTE=1 to keep the remote step from calling `gh` at all.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from docket import gitinfo, templates
from docket.blocking import registered_dirs
from docket.config import Config, DocketError, insert_branch_pattern
from docket.fsio import read_text, write_config, write_text
from docket.notes import is_container, project_id

LIMIT_MB = 50
LIMIT_BYTES = LIMIT_MB * 1024 * 1024
BLOB_REPORT = 5
HOOKS_DIR = ".githooks"
DEFAULT_BRANCH = "main"
STANZA_HEADING = "## Research log"
CLAUDE_IMPORT = "@AGENTS.md"
HOOK_COMMAND = "docket brief $(basename $PWD)"
FALLBACK = "*"


@dataclass
class Outcome:
    """What one step found, and what it did about it.

    `missing` is the phrase `--check` prints and is what makes a repo
    incomplete. `note` is advisory and never does. `failed` marks a step that
    could not be applied safely, which is an error rather than a gap.
    """

    key: str
    missing: str | None = None
    action: str | None = None
    note: str | None = None
    failed: bool = False


@dataclass
class Blob:
    size: int
    path: str
    where: str  # history | worktree

    @property
    def megabytes(self) -> float:
        return self.size / (1024 * 1024)

    def line(self) -> str:
        return f"  {self.megabytes:8.1f} MB  {self.path} ({self.where})"


@dataclass
class Target:
    """The repo being wired, plus state shared between steps."""

    cfg: Config
    path: Path
    name: str
    project_id: str
    namespace: str | None = None
    blobs: list[Blob] = field(default_factory=list)

    @property
    def has_git(self) -> bool:
        return (self.path / ".git").exists()


# --- git and gh, isolated so tests can stub every mutation -------------------


def git_write(repo: Path, *args: str) -> str:
    """A git call that changes the repository. init makes exactly these."""
    return gitinfo.run_git(repo, *args)


def git_config(repo: Path, key: str) -> str | None:
    try:
        return gitinfo.run_git(repo, "config", "--get", key).strip() or None
    except DocketError:
        return None


def create_remote(repo: Path, name: str) -> str:
    """Create a private GitHub repo and push. `gh repo create --source` rejects
    a repo whose .git is a pointer file, so the remote is added by hand.
    """
    try:
        proc = subprocess.run(
            ["gh", "repo", "create", name, "--private"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise DocketError("gh not found; create the remote by hand") from exc
    if proc.returncode != 0:
        raise DocketError(f"gh repo create failed: {proc.stderr.strip()}")
    url = next(
        (line.strip() for line in reversed(proc.stdout.splitlines()) if line.strip()),
        "",
    )
    if not url.startswith("http"):
        raise DocketError(f"gh repo create printed no URL: {proc.stdout.strip()}")
    git_write(repo, "remote", "add", "origin", url)
    git_write(repo, "push", "-u", "origin", "HEAD")
    return url


# --- the blob audit ----------------------------------------------------------


def _history_blobs(repo: Path) -> list[Blob]:
    try:
        listing = gitinfo.run_git(repo, "rev-list", "--objects", "--all")
    except DocketError:
        return []  # no commits yet
    names: dict[str, str] = {}
    for line in listing.splitlines():
        sha, _, path = line.partition(" ")
        if path:
            names.setdefault(sha, path)
    sizes = gitinfo.run_git(
        repo,
        "cat-file",
        "--batch-all-objects",
        "--batch-check=%(objecttype) %(objectname) %(objectsize)",
    )
    found: list[Blob] = []
    for line in sizes.splitlines():
        parts = line.split()
        if len(parts) != 3 or parts[0] != "blob":
            continue
        path = names.get(parts[1])
        if path is not None:
            found.append(Blob(int(parts[2]), path, "history"))
    return found


def _worktree_blobs(repo: Path) -> list[Blob]:
    """Tracked and untracked files that are not ignored: what a first push
    would carry even though it is not in history yet."""
    listing = gitinfo.run_git(
        repo, "ls-files", "-z", "--cached", "--others", "--exclude-standard"
    )
    found = []
    for rel in listing.split("\0"):
        if not rel:
            continue
        try:
            size = os.lstat(repo / rel).st_size
        except OSError:
            continue
        found.append(Blob(size, rel, "worktree"))
    return found


def largest_blobs(repo: Path, limit: int = BLOB_REPORT) -> list[Blob]:
    """The `limit` biggest files a push would carry, history and worktree, one
    entry per path at its largest observed size."""
    biggest: dict[str, Blob] = {}
    for blob in _history_blobs(repo) + _worktree_blobs(repo):
        current = biggest.get(blob.path)
        if current is None or blob.size > current.size:
            biggest[blob.path] = blob
    ranked = sorted(biggest.values(), key=lambda b: (-b.size, b.path))
    return ranked[:limit]


# --- the steps ---------------------------------------------------------------


def step_git(target: Target, *, write: bool) -> Outcome:
    if target.has_git:
        return Outcome("git")
    if not write:
        return Outcome("git", missing="no git repository")
    git_write(target.path, "init", "-q", "-b", DEFAULT_BRANCH)
    return Outcome("git", action=f"git init on {DEFAULT_BRANCH}")


def step_gitignore(target: Target, *, write: bool) -> Outcome:
    path = target.path / ".gitignore"
    if path.exists():
        return Outcome("gitignore")
    if not write:
        return Outcome("gitignore", missing="no .gitignore")
    write_text(target.cfg, path, templates.gitignore())
    return Outcome("gitignore", action="wrote .gitignore")


def step_hooks(target: Target, *, write: bool) -> Outcome:
    hook = target.path / HOOKS_DIR / "pre-commit"
    gaps = []
    if not hook.is_file():
        gaps.append(f"no {HOOKS_DIR}/pre-commit")
    elif not os.access(hook, os.X_OK):
        gaps.append(f"{HOOKS_DIR}/pre-commit not executable")
    if not target.has_git or git_config(target.path, "core.hooksPath") != HOOKS_DIR:
        gaps.append("core.hooksPath not set")
    if not gaps:
        return Outcome("hooks")
    if not write:
        return Outcome("hooks", missing=", ".join(gaps))
    done = []
    if not hook.is_file():
        write_text(target.cfg, hook, templates.pre_commit_hook())
        done.append(f"wrote {HOOKS_DIR}/pre-commit")
    if not os.access(hook, os.X_OK):
        hook.chmod(hook.stat().st_mode | 0o111)
        done.append("made it executable")
    if git_config(target.path, "core.hooksPath") != HOOKS_DIR:
        git_write(target.path, "config", "core.hooksPath", HOOKS_DIR)
        done.append(f"set core.hooksPath={HOOKS_DIR}")
    return Outcome("hooks", action=f"{LIMIT_MB} MB guard: " + ", ".join(done))


def step_blobs(target: Target, *, write: bool) -> Outcome:
    """Read-only in both modes: this reports, and the remote step refuses."""
    if not target.has_git:
        return Outcome("blobs")
    target.blobs = largest_blobs(target.path)
    over = [b for b in target.blobs if b.size > LIMIT_BYTES]
    if not over:
        return Outcome("blobs")
    worst = over[0]
    return Outcome(
        "blobs",
        missing=(
            f"{len(over)} file(s) over {LIMIT_MB} MB, largest "
            f"{worst.path} at {worst.megabytes:.0f} MB"
        ),
    )


def step_remote(target: Target, *, write: bool) -> Outcome:
    if not target.has_git:
        return Outcome("remote", missing="no remote")
    if gitinfo.has_remote(target.path):
        return Outcome("remote")
    if not write:
        return Outcome("remote", missing="no remote")
    over = [b for b in target.blobs if b.size > LIMIT_BYTES]
    if over:
        return Outcome(
            "remote",
            failed=True,
            action=(
                f"refusing to publish: {over[0].path} is "
                f"{over[0].megabytes:.0f} MB, over the {LIMIT_MB} MB limit. "
                "GitHub blocks 100 MB outright and the fix afterwards is "
                "history surgery — remove it from history first"
            ),
        )
    if os.environ.get("DOCKET_NO_REMOTE"):
        return Outcome("remote", missing="no remote (DOCKET_NO_REMOTE set)")
    url = create_remote(target.path, target.path.name)
    return Outcome("remote", action=f"created private remote {url} and pushed")


def step_docket_toml(target: Target, *, write: bool) -> Outcome:
    path = target.path / ".docket.toml"
    line = f'project_id = "{target.project_id}"\n'
    text = read_text(path) if path.is_file() else None
    if text is not None:
        current = project_id(target.path)
        if "project_id" in text and current == target.project_id:
            return Outcome("docket.toml")
        gap = (
            ".docket.toml has no project_id"
            if "project_id" not in text
            else f".docket.toml says project_id {current}"
        )
        if not write:
            return Outcome("docket.toml", missing=gap)
        if "project_id" not in text:
            body = text if text.endswith("\n") or not text else text + "\n"
            write_text(target.cfg, path, body + line)
            return Outcome(
                "docket.toml", action=f"added project_id {target.project_id}"
            )
        kept = [
            ln for ln in text.split("\n") if not ln.strip().startswith("project_id")
        ]
        write_text(target.cfg, path, line + "\n".join(kept).lstrip("\n"))
        return Outcome("docket.toml", action=f"set project_id {target.project_id}")
    if not write:
        return Outcome("docket.toml", missing="no .docket.toml")
    write_text(target.cfg, path, line)
    return Outcome("docket.toml", action=f"wrote .docket.toml ({target.project_id})")


def _with_newline(text: str, sample: str) -> str:
    return text.replace("\n", "\r\n") if "\r\n" in sample else text


def step_agents(target: Target, *, write: bool) -> Outcome:
    path = target.path / "AGENTS.md"
    stanza = templates.agents_stanza()
    if path.is_file():
        text = read_text(path)
        if STANZA_HEADING in text:
            return Outcome("agents")
        if not write:
            return Outcome("agents", missing="AGENTS.md has no research-log stanza")
        body = text.rstrip("\r\n")
        joined = body + "\n\n" + _with_newline(stanza, text)
        write_text(target.cfg, path, _with_newline(joined, text))
        return Outcome("agents", action="appended the research-log stanza")
    if not write:
        return Outcome("agents", missing="no AGENTS.md")
    write_text(target.cfg, path, stanza)
    return Outcome("agents", action="wrote AGENTS.md")


def step_claude(target: Target, *, write: bool) -> Outcome:
    """Three cases: no file at all, a real file, a real file that already
    imports. A symlink is left alone whatever it points at — the user made it."""
    path = target.path / "CLAUDE.md"
    if path.is_symlink():
        dest = os.readlink(path)
        if dest != "AGENTS.md":
            return Outcome("claude", note=f"CLAUDE.md links to {dest}")
        return Outcome("claude")
    if path.is_file():
        text = read_text(path)
        if CLAUDE_IMPORT in text:
            return Outcome("claude")
        if not write:
            return Outcome(
                "claude", missing=f"CLAUDE.md does not import {CLAUDE_IMPORT}"
            )
        write_text(target.cfg, path, _with_newline(f"{CLAUDE_IMPORT}\n\n", text) + text)
        return Outcome("claude", action=f"prepended {CLAUDE_IMPORT} to CLAUDE.md")
    if not write:
        return Outcome("claude", missing="no CLAUDE.md")
    target.cfg.assert_inside_roots(path)
    os.symlink("AGENTS.md", path)
    return Outcome("claude", action="symlinked CLAUDE.md -> AGENTS.md")


def _session_start_groups(data: dict) -> list:
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return []
    groups = hooks.get("SessionStart")
    return groups if isinstance(groups, list) else []


def _has_brief_hook(data: dict) -> bool:
    for group in _session_start_groups(data):
        entries = group.get("hooks") if isinstance(group, dict) else None
        for entry in entries or []:
            command = entry.get("command", "") if isinstance(entry, dict) else ""
            if "docket brief" in command:
                return True
    return False


def step_settings(target: Target, *, write: bool) -> Outcome:
    """Merge the hook into whatever is there. The file is never replaced: a
    settings.json holding permissions and other hooks is the normal case."""
    path = target.path / ".claude" / "settings.json"
    data: dict = {}
    if path.is_file():
        try:
            loaded = json.loads(read_text(path) or "{}")
        except json.JSONDecodeError as exc:
            return Outcome(
                "settings",
                missing=f".claude/settings.json is not valid JSON ({exc.msg})",
                failed=write,
            )
        if not isinstance(loaded, dict):
            return Outcome(
                "settings",
                missing=".claude/settings.json is not a JSON object",
                failed=write,
            )
        data = loaded
        if _has_brief_hook(data):
            return Outcome("settings")
    if not write:
        return Outcome("settings", missing="no SessionStart docket brief hook")
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        return Outcome("settings", missing="hooks is not an object", failed=True)
    groups = hooks.setdefault("SessionStart", [])
    if not isinstance(groups, list):
        return Outcome("settings", missing="SessionStart is not a list", failed=True)
    groups.append({"hooks": [{"type": "command", "command": HOOK_COMMAND}]})
    write_text(target.cfg, path, json.dumps(data, indent=2) + "\n")
    return Outcome("settings", action="merged the SessionStart brief hook")


def step_anchor(target: Target, *, write: bool) -> Outcome:
    """The zero-byte type anchor. It must exist before any record links to it,
    or the backlink silently goes nowhere and the group is unqueryable."""
    path = target.cfg.context / f"{target.project_id}.md"
    if path.exists():
        return Outcome("anchor")
    if not write:
        return Outcome("anchor", missing=f"no {path.name} anchor in the context vault")
    write_text(target.cfg, path, "")
    return Outcome("anchor", action=f"wrote the {path.name} anchor")


def fallback_branches(target: Target) -> list[str]:
    """Branches that reached only the "*" fallback: no namespace meaning. main,
    master and worktree-agent-* are protected, so the importer never classifies
    them and they are not evidence of a missing namespace."""
    from docket.commands.idea import _is_protected

    if not target.has_git:
        return []
    try:
        branches = gitinfo.list_branches(target.path)
    except DocketError:
        return []
    found = []
    for name in branches:
        if _is_protected(name):
            continue
        match = target.cfg.branch_match(name)
        if match is not None and match[0] == FALLBACK:
            found.append(name)
    return sorted(found)


def step_namespace(target: Target, *, write: bool) -> Outcome:
    """Add the repo's branch namespace to the global [branches] table. There is
    no per-repo answer to check, so `--check` reports the fallback count as a
    note instead: a repo whose branches all land on "*" has no namespace."""
    if not write:
        stray = fallback_branches(target)
        if not stray:
            return Outcome("namespace")
        noun = "branch" if len(stray) == 1 else "branches"
        return Outcome("namespace", note=f'{len(stray)} {noun} on "*"')
    if target.namespace is None:
        return Outcome("namespace")
    updated = insert_branch_pattern(read_text(target.cfg.path), target.namespace)
    if updated is None:
        return Outcome("namespace")
    write_config(target.cfg, updated)
    return Outcome(
        "namespace", action=f'added "{target.namespace}" before the "*" fallback'
    )


STEPS = (
    step_git,
    step_gitignore,
    step_hooks,
    step_blobs,
    step_remote,
    step_docket_toml,
    step_agents,
    step_claude,
    step_settings,
    step_anchor,
    step_namespace,
)


# --- running them ------------------------------------------------------------


def resolve_target(
    cfg: Config,
    name: str | None,
    *,
    namespace: str | None = None,
    override_id: str | None = None,
) -> Target:
    """A repo by directory name under the projects root, or the current
    directory when no name is given. Refuses anything outside the root: every
    write below assumes it is inside one, and the guard would fail late."""
    path = (cfg.projects / name) if name else Path.cwd()
    path = path.expanduser()
    if not path.is_dir():
        raise DocketError(f"not a directory: {path}")
    resolved = path.resolve()
    root = cfg.projects.expanduser().resolve()
    if not resolved.is_relative_to(root):
        raise DocketError(f"{resolved} is not under the projects root {root}")
    return Target(
        cfg=cfg,
        path=resolved,
        name=resolved.relative_to(root).as_posix(),
        project_id=override_id or project_id(resolved),
        namespace=namespace,
    )


def refuse_container(target: Target) -> None:
    """A container holds other repos. `git init` inside one would make a repo
    that swallows them, which is the opposite of what the flag records."""
    if is_container(target.path):
        raise DocketError(
            f"{target.name} is marked container = true in .docket.toml; "
            "wire the repos inside it instead"
        )


def run_steps(target: Target, *, write: bool) -> list[Outcome]:
    return [step(target, write=write) for step in STEPS]


def check_line(target: Target, outcomes: list[Outcome]) -> str:
    missing = [o.missing for o in outcomes if o.missing]
    notes = [o.note for o in outcomes if o.note]
    parts = [f"missing: {', '.join(missing)}"] if missing else ["ok"]
    if notes:
        parts.append(f"note: {'; '.join(notes)}")
    return f"{target.name} — {' · '.join(parts)}"


def check_repos(cfg: Config, name: str | None) -> tuple[str, int]:
    """Read-only. One line per repo naming what is missing; exit 1 if any repo
    is incomplete, so this can go in a hook later. Containers get no line at
    all — only a count, so the skip is visible without being an entry that
    reads as a finding on every run."""
    if name:
        targets = [resolve_target(cfg, name)]
    else:
        root = cfg.projects.expanduser().resolve()
        targets = [
            Target(cfg, d, d.resolve().relative_to(root).as_posix(), project_id(d))
            for d in registered_dirs(cfg)
        ]
    containers = sum(1 for t in targets if is_container(t.path))
    targets = [t for t in targets if not is_container(t.path)]
    lines, incomplete = [], 0
    for target in targets:
        outcomes = run_steps(target, write=False)
        if any(o.missing for o in outcomes):
            incomplete += 1
        lines.append(check_line(target, outcomes))
    total = len(targets)
    noun = "repo" if total == 1 else "repos"
    tail = f", {incomplete} incomplete" if incomplete else ""
    if containers:
        held = "container" if containers == 1 else "containers"
        tail += f", {containers} {held} skipped"
    summary = f"docket init --check: {total - incomplete}/{total} {noun} wired"
    lines.append(summary + tail)
    return "\n".join(lines), (1 if incomplete else 0)


def _verify(target: Target) -> list[str]:
    """Step 9: the wiring is not done until the two commands it exists for run."""
    from docket.commands.brief import run_brief
    from docket.commands.check import run_check

    lines = []
    try:
        text = run_brief(target.cfg, target.name)
        head = text.splitlines()[0] if text.splitlines() else ""
        lines.append(f"verify    docket brief — {len(text)} chars, {head}")
    except DocketError as exc:
        lines.append(f"verify    docket brief FAILED — {exc}")
    try:
        _, code = run_check(target.cfg)
        lines.append(f"verify    docket check — {'passes' if code == 0 else 'FAILS'}")
    except DocketError as exc:
        lines.append(f"verify    docket check FAILED — {exc}")
    return lines


def run_init(
    cfg: Config,
    name: str | None = None,
    *,
    check: bool = False,
    namespace: str | None = None,
    project_id_override: str | None = None,
) -> tuple[str, int]:
    if check:
        return check_repos(cfg, name)
    target = resolve_target(
        cfg, name, namespace=namespace, override_id=project_id_override
    )
    refuse_container(target)
    lines = [f"{target.name} ({target.project_id})"]
    outcomes = run_steps(target, write=True)
    for outcome in outcomes:
        detail = outcome.action or outcome.missing or outcome.note
        if outcome.failed:
            label = "REFUSED"
        elif outcome.action:
            label = "wrote"
        elif outcome.missing:
            label = "left"  # a gap init did not fill; --check still reports it
        elif outcome.note:
            label = "note"
        else:
            label, detail = "ok", None
        lines.append(f"{label:<9} {outcome.key}" + (f": {detail}" if detail else ""))
    if target.blobs:
        lines.append(f"largest {len(target.blobs)} file(s) a push would carry:")
        lines.extend(blob.line() for blob in target.blobs)
    lines.extend(_verify(target))
    failed = sum(1 for o in outcomes if o.failed)
    lines.append(
        "docket init: done" if not failed else f"docket init: {failed} step(s) refused"
    )
    return "\n".join(lines), (1 if failed else 0)
