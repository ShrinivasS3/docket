"""Fixtures: a temp three-root layout, a temp config, and a temp git repo with
known branch names and commit dates pinned relative to DOCKET_TODAY."""

from __future__ import annotations

import datetime as dt
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from docket.cli import main

TODAY = dt.date(2026, 9, 3)

ANCHORS = [
    "Ideas",
    "Gotchas",
    "Papers",
    "Findings",
    "Runs",
    "In Progress",
    "Completed",
    "Parked",
    "Falsified",
    "Superseded",
    "Retracted",
    "Reviving",
    "TestProj",
    "OtherProj",
]

DASHBOARD = """# Life HQ Dashboard

![[Quick Links]]

TO DO:

- [ ] LinkedIn Banner
- [ ] X Banner

___

14.317 - 12 steps
8.22 - steps

___

- [ ] systemic check of hard bound
"""


def days_ago(n: int) -> dt.date:
    return TODAY - dt.timedelta(days=n)


def snapshot(*roots: Path) -> dict[str, bytes]:
    """Every file under the given roots, as relpath -> bytes."""
    out: dict[str, bytes] = {}
    for root in roots:
        for path in sorted(root.rglob("*")):
            if path.is_file() and ".git" not in path.parts:
                out[f"{root.name}/{path.relative_to(root)}"] = path.read_bytes()
    return out


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    projects, context, personal = (
        tmp_path / n for n in ("projects", "context", "personal")
    )
    for folder in (projects, context, personal):
        folder.mkdir()
    for anchor in ANCHORS:
        (context / f"{anchor}.md").write_text("")
    (context / "README.md").write_text("# docket-context\n")
    dashboard = personal / "Dashboard.md"
    dashboard.write_text(DASHBOARD)
    config = tmp_path / "config.toml"
    config.write_text(
        f'[roots]\nprojects = "{projects}"\ncontext = "{context}"\n'
        f'personal = "{personal}"\n\n[dashboard]\ntarget = "{dashboard}"\n\n'
        '[branches]\n"experiments/*" = "idea"\n"diagnostics/*" = "idea"\n'
        '"phase-*" = "idea"\n"fix/*" = "gotcha"\n"*" = "idea"\n'
    )
    monkeypatch.setenv("DOCKET_CONFIG", str(config))
    monkeypatch.setenv("DOCKET_TODAY", TODAY.isoformat())
    return SimpleNamespace(
        root=tmp_path,
        projects=projects,
        context=context,
        personal=personal,
        dashboard=dashboard,
        config=config,
        roots=(projects, context, personal),
    )


class Git:
    def __init__(self, path: Path, home: Path):
        self.path = path
        empty = home / "empty-gitconfig"
        empty.write_text("")
        self.env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
            "GIT_CONFIG_GLOBAL": str(empty),
            "GIT_CONFIG_NOSYSTEM": "1",
        }

    def __call__(self, *args: str, date: dt.date | None = None) -> str:
        env = dict(self.env)
        if date is not None:
            stamp = f"{date.isoformat()}T12:00:00 +0000"
            env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = stamp
        proc = subprocess.run(
            ["git", "-C", str(self.path), *args],
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        return proc.stdout

    def commit(self, name: str, date: dt.date) -> None:
        (self.path / f"{name}.txt").write_text(name)
        self("add", "-A")
        self("commit", "-q", "-m", name, date=date)


def set_mtime(path: Path, date: dt.date) -> None:
    stamp = dt.datetime.combine(date, dt.time(12, 0)).timestamp()
    os.utime(path, (stamp, stamp))


def add_remote(git: Git, home: Path, *, push: bool = True) -> Path:
    """Attach a bare remote; push every branch so nothing is unpushed."""
    bare = home / f"{git.path.name}-remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True, env=git.env)
    git("remote", "add", "origin", str(bare))
    if push:
        git("push", "-q", "origin", "--all")
    return bare


def make_repo(
    root: Path, home: Path, name: str, *, project_id: str | None = None
) -> Git:
    path = root / name
    path.mkdir()
    if project_id:
        (path / ".docket.toml").write_text(f'project_id = "{project_id}"\n')
    git = Git(path, home)
    git("init", "-q")
    git("symbolic-ref", "HEAD", "refs/heads/main")
    git.commit("init", days_ago(10))
    return git


@pytest.fixture
def repo(vault: SimpleNamespace) -> Git:
    """TestProj with: a merged branch, a fresh unmerged one, a stale unmerged one,
    a fix/* branch (kind gotcha), a worktree-agent-* branch, and main."""
    git = make_repo(vault.projects, vault.root, "TestProj", project_id="TestProj")
    git("checkout", "-q", "-b", "experiments/merged-one")
    git.commit("merged", days_ago(5))
    git("checkout", "-q", "main")
    git("merge", "-q", "--ff-only", "experiments/merged-one")
    git("checkout", "-q", "-b", "experiments/fresh-one", "main")
    git.commit("fresh", days_ago(1))
    git("checkout", "-q", "-b", "phase-1-old-one", "main")
    git.commit("old", days_ago(100))
    git("checkout", "-q", "-b", "fix/some-bug", "main")
    git.commit("fix", days_ago(3))
    git("checkout", "-q", "-b", "worktree-agent-7", "main")
    git.commit("wt", days_ago(1))
    git("checkout", "-q", "main")
    return git


@pytest.fixture
def cli(capsys: pytest.CaptureFixture[str]):
    """Run the CLI in-process: returns (exit_code, stdout, stderr)."""

    def run(*argv: str) -> tuple[int, str, str]:
        code = main(list(argv))
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return run
