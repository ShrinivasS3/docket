"""docket init and docket init --check.

Two properties carry most of the weight: every step is a no-op the second time,
and --check writes nothing at all. The second is asserted twice over — once by
stubbing every writer so a write raises, once by snapshotting all three roots
and the config file around the call.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from docket.commands import init as init_mod
from docket.config import insert_branch_pattern, load_config

from .conftest import add_remote, make_repo, snapshot


@pytest.fixture(autouse=True)
def no_remote(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test may reach `gh`. Creating a GitHub repo is not undoable."""
    monkeypatch.setenv("DOCKET_NO_REMOTE", "1")

    def refuse(*args, **kwargs):  # pragma: no cover - only fires on a bug
        raise AssertionError("a test tried to create a real remote")

    monkeypatch.setattr(init_mod, "create_remote", refuse)


def everything(vault) -> dict[str, bytes]:
    """Every byte docket init could touch: the three roots and the config."""
    state = snapshot(*vault.roots)
    state["config.toml"] = vault.config.read_bytes()
    return state


def links(vault, name: str = "TestProj") -> dict[str, str]:
    """Symlinks under a repo, which a byte snapshot does not capture."""
    repo = vault.projects / name
    return {
        str(p.relative_to(repo)): os.readlink(p)
        for p in sorted(repo.rglob("*"))
        if p.is_symlink()
    }


# --- init writes the wiring --------------------------------------------------


def test_init_wires_a_bare_repo(vault, repo, cli):
    code, out, _ = cli("init", "TestProj")
    assert code == 0
    for key in ("gitignore", "hooks", "agents", "claude", "settings"):
        assert f"wrote     {key}:" in out, out
    path = vault.projects / "TestProj"
    assert (path / ".gitignore").is_file()
    assert (path / ".githooks" / "pre-commit").is_file()
    assert os.access(path / ".githooks" / "pre-commit", os.X_OK)
    assert (path / ".docket.toml").read_text() == 'project_id = "TestProj"\n'
    assert "## Research log" in (path / "AGENTS.md").read_text()
    assert (path / "CLAUDE.md").is_symlink()
    assert json.loads((path / ".claude" / "settings.json").read_text())["hooks"]


def test_init_sets_hooks_path(vault, repo, cli):
    cli("init", "TestProj")
    assert init_mod.git_config(vault.projects / "TestProj", "core.hooksPath") == (
        ".githooks"
    )


def test_init_creates_the_repo_when_there_is_none(vault, cli):
    (vault.projects / "Fresh").mkdir()
    code, out, _ = cli("init", "Fresh")
    assert code == 0 and "git init on main" in out
    assert (vault.projects / "Fresh" / ".git").is_dir()


def test_init_writes_the_type_anchor(vault, cli):
    (vault.projects / "Fresh").mkdir()
    cli("init", "Fresh")
    anchor = vault.context / "Fresh.md"
    assert anchor.is_file() and anchor.read_bytes() == b""


def test_init_honours_project_id(vault, repo, cli):
    cli("init", "TestProj", "--project-id", "Renamed")
    path = vault.projects / "TestProj" / ".docket.toml"
    assert path.read_text() == 'project_id = "Renamed"\n'
    assert (vault.context / "Renamed.md").is_file()


def test_init_verifies_brief_and_check(vault, repo, cli):
    _, out, _ = cli("init", "TestProj")
    assert "verify    docket brief —" in out
    assert "verify    docket check — passes" in out


def test_init_refuses_a_directory_outside_the_projects_root(vault, cli):
    (vault.root / "elsewhere").mkdir()
    code, _, err = cli("init", "../elsewhere")
    assert code == 2 and "projects root" in err


# --- idempotency, step by step -----------------------------------------------


def test_init_is_a_no_op_the_second_time(vault, repo, cli):
    cli("init", "TestProj")
    before, before_links = everything(vault), links(vault)
    code, out, _ = cli("init", "TestProj")
    assert code == 0
    assert everything(vault) == before
    assert links(vault) == before_links
    assert "wrote" not in out, out


@pytest.mark.parametrize(
    "key",
    [
        "git",
        "gitignore",
        "hooks",
        "docket.toml",
        "agents",
        "claude",
        "settings",
        "anchor",
    ],
)
def test_every_step_reports_ok_on_a_wired_repo(vault, repo, cli, key):
    cli("init", "TestProj")
    _, out, _ = cli("init", "TestProj")
    assert f"ok        {key}" in out, out


def test_init_does_not_rewrite_a_hand_wired_repo(vault, repo, cli):
    """The fifteen repos already carry this wiring. init must leave them alone."""
    path = vault.projects / "TestProj"
    (path / "AGENTS.md").write_text("## Research log\nhand written\n")
    (path / "CLAUDE.md").write_text("# real file\n@AGENTS.md\n")
    (path / ".claude").mkdir()
    (path / ".claude" / "settings.json").write_text(
        '{"hooks": {"SessionStart": [{"hooks": [{"command": "docket brief x"}]}]}}'
    )
    before = everything(vault)
    cli("init", "TestProj")
    after = everything(vault)
    for name in ("AGENTS.md", "CLAUDE.md", ".claude/settings.json"):
        assert after[f"projects/TestProj/{name}"] == before[f"projects/TestProj/{name}"]


# --- AGENTS.md ---------------------------------------------------------------


def test_agents_stanza_is_appended_not_replaced(vault, repo, cli):
    path = vault.projects / "TestProj" / "AGENTS.md"
    original = "# Agents\n\nSomething the user wrote.\n"
    path.write_text(original)
    cli("init", "TestProj")
    text = path.read_text()
    assert text.startswith(original)
    assert "## Research log" in text
    assert "Something the user wrote." in text


def test_agents_stanza_comes_from_the_package(vault, repo, cli):
    from docket import templates

    cli("init", "TestProj")
    text = (vault.projects / "TestProj" / "AGENTS.md").read_text()
    assert text == templates.agents_stanza()


def test_agents_append_keeps_crlf(vault, repo, cli):
    path = vault.projects / "TestProj" / "AGENTS.md"
    path.write_bytes(b"# Agents\r\n\r\nWindows file.\r\n")
    cli("init", "TestProj")
    raw = path.read_bytes()
    assert b"\r\n" in raw and b"\n\n" not in raw.replace(b"\r\n", b"")


# --- CLAUDE.md, all three cases ----------------------------------------------


def test_claude_absent_becomes_a_symlink(vault, repo, cli):
    cli("init", "TestProj")
    path = vault.projects / "TestProj" / "CLAUDE.md"
    assert path.is_symlink() and os.readlink(path) == "AGENTS.md"
    assert "## Research log" in path.read_text()


def test_claude_real_file_gets_the_import_prepended(vault, repo, cli):
    path = vault.projects / "TestProj" / "CLAUDE.md"
    path.write_text("# CLAUDE.md — TestProj\n\nArchitecture is locked.\n")
    cli("init", "TestProj")
    text = path.read_text()
    assert not path.is_symlink()
    assert text.startswith("@AGENTS.md\n\n# CLAUDE.md — TestProj")
    assert "Architecture is locked." in text


def test_claude_that_already_imports_is_left_alone(vault, repo, cli):
    path = vault.projects / "TestProj" / "CLAUDE.md"
    original = "@AGENTS.md\n\n# CLAUDE.md\n"
    path.write_text(original)
    _, out, _ = cli("init", "TestProj")
    assert path.read_text() == original
    assert "ok        claude" in out


def test_claude_symlink_elsewhere_is_reported_not_moved(vault, repo, cli):
    path = vault.projects / "TestProj" / "CLAUDE.md"
    (vault.projects / "TestProj" / "OTHER.md").write_text("x\n")
    os.symlink("OTHER.md", path)
    _, out, _ = cli("init", "TestProj")
    assert os.readlink(path) == "OTHER.md"
    assert "CLAUDE.md links to OTHER.md" in out


# --- .claude/settings.json ---------------------------------------------------


def test_settings_hook_merges_into_an_existing_file(vault, repo, cli):
    path = vault.projects / "TestProj" / ".claude" / "settings.json"
    path.parent.mkdir()
    path.write_text(
        json.dumps(
            {
                "permissions": {"allow": ["Bash(uv run pytest)"]},
                "hooks": {
                    "SessionEnd": [
                        {"hooks": [{"type": "command", "command": "echo bye"}]}
                    ]
                },
            },
            indent=2,
        )
        + "\n"
    )
    cli("init", "TestProj")
    data = json.loads(path.read_text())
    assert data["permissions"] == {"allow": ["Bash(uv run pytest)"]}
    assert data["hooks"]["SessionEnd"][0]["hooks"][0]["command"] == "echo bye"
    commands = [
        entry["command"]
        for group in data["hooks"]["SessionStart"]
        for entry in group["hooks"]
    ]
    assert commands == ["docket brief $(basename $PWD)"]


def test_settings_hook_is_added_once(vault, repo, cli):
    cli("init", "TestProj")
    cli("init", "TestProj")
    path = vault.projects / "TestProj" / ".claude" / "settings.json"
    assert len(json.loads(path.read_text())["hooks"]["SessionStart"]) == 1


def test_settings_that_is_not_json_is_refused_not_overwritten(vault, repo, cli):
    path = vault.projects / "TestProj" / ".claude" / "settings.json"
    path.parent.mkdir()
    path.write_text("{ not json")
    code, out, _ = cli("init", "TestProj")
    assert path.read_text() == "{ not json"
    assert code == 1 and "REFUSED" in out and "not valid JSON" in out


# --- the namespace, inserted before the fallback -----------------------------


def test_namespace_is_inserted_before_the_fallback(vault, repo, cli):
    cli("init", "TestProj", "--namespace", "spike/*")
    text = vault.config.read_text()
    assert '"spike/*"' in text
    keys = [ln.split("=")[0].strip() for ln in text.splitlines() if "=" in ln]
    assert keys.index('"spike/*"') < keys.index('"*"')
    assert load_config(vault.config).branch_match("spike/x") == ("spike/*", "idea")


def test_namespace_already_present_is_a_no_op(vault, repo, cli):
    before = vault.config.read_bytes()
    _, out, _ = cli("init", "TestProj", "--namespace", "experiments/*")
    assert vault.config.read_bytes() == before
    assert "ok        namespace" in out


def test_namespace_insert_keeps_the_comment_with_the_fallback():
    text = (
        "[branches]\n"
        '"experiments/*" = "idea"\n'
        "# Fallback, explained at length.\n"
        "# Second line of the same comment.\n"
        '"*" = "idea"\n'
    )
    out = insert_branch_pattern(text, "spike/*")
    assert out is not None
    lines = out.splitlines()
    assert lines[2] == '"spike/*"       = "idea"'
    assert lines[3].startswith("# Fallback")


def test_namespace_insert_appends_when_there_is_no_fallback():
    text = '[branches]\n"experiments/*" = "idea"\n\n[dash]\nstale_days = 7\n'
    out = insert_branch_pattern(text, "spike/*")
    assert out is not None
    assert out.splitlines()[:3] == [
        "[branches]",
        '"experiments/*" = "idea"',
        '"spike/*"       = "idea"',
    ]
    assert "[dash]" in out


def test_namespace_insert_creates_the_table_when_absent():
    out = insert_branch_pattern('[roots]\nprojects = "/tmp"\n', "spike/*")
    assert out is not None and out.endswith('[branches]\n"spike/*" = "idea"\n')


def test_namespace_is_not_touched_without_the_flag(vault, repo, cli):
    before = vault.config.read_bytes()
    cli("init", "TestProj")
    assert vault.config.read_bytes() == before


# --- the blob audit ----------------------------------------------------------


def test_init_reports_the_largest_blobs(vault, repo, cli):
    (vault.projects / "TestProj" / "big.bin").write_bytes(b"x" * 4096)
    _, out, _ = cli("init", "TestProj")
    assert "largest" in out and "big.bin (worktree)" in out


def test_a_file_over_the_limit_refuses_the_remote(vault, repo, cli, monkeypatch):
    monkeypatch.setattr(init_mod, "LIMIT_BYTES", 1024)
    (vault.projects / "TestProj" / "huge.bin").write_bytes(b"x" * 4096)
    code, out, _ = cli("init", "TestProj")
    assert code == 1
    assert "REFUSED   remote" in out and "huge.bin" in out
    assert "history surgery" in out


def test_oversize_does_not_block_the_other_steps(vault, repo, cli, monkeypatch):
    monkeypatch.setattr(init_mod, "LIMIT_BYTES", 1024)
    (vault.projects / "TestProj" / "huge.bin").write_bytes(b"x" * 4096)
    cli("init", "TestProj")
    assert (vault.projects / "TestProj" / "AGENTS.md").is_file()


def test_ignored_files_are_not_counted(vault, repo, cli):
    path = vault.projects / "TestProj"
    (path / ".gitignore").write_text("outputs/\n")
    (path / "outputs").mkdir()
    (path / "outputs" / "big.bin").write_bytes(b"x" * 8192)
    blobs = init_mod.largest_blobs(path)
    assert all("outputs" not in b.path for b in blobs)


# --- --check reports and never writes ----------------------------------------


def test_check_reports_a_bare_repo_as_incomplete(vault, repo, cli):
    code, out, _ = cli("init", "--check", "TestProj")
    assert code == 1
    assert "TestProj — missing:" in out
    for gap in ("no .gitignore", "no AGENTS.md", "no CLAUDE.md", "no remote"):
        assert gap in out


def test_check_reports_a_wired_repo_as_ok(vault, repo, cli):
    add_remote(repo, vault.root)
    cli("init", "TestProj")
    code, out, _ = cli("init", "--check", "TestProj")
    assert code == 0 and "TestProj — ok" in out
    assert "1/1 repo wired" in out


def test_check_covers_every_registered_repo(vault, repo, cli):
    make_repo(vault.projects, vault.root, "OtherProj", project_id="OtherProj")
    code, out, _ = cli("init", "--check")
    assert code == 1
    names = [line.split(" — ")[0] for line in out.splitlines()[:-1]]
    assert names == ["OtherProj", "TestProj"]
    assert "0/2 repos wired, 2 incomplete" in out


def test_check_skips_unregistered_directories(vault, repo, cli):
    (vault.projects / "coursework").mkdir()
    _, out, _ = cli("init", "--check")
    assert "coursework" not in out


def test_check_writes_nothing(vault, repo, cli, monkeypatch):
    """Stub every writer, then compare all three roots and the config."""
    make_repo(vault.projects, vault.root, "OtherProj", project_id="OtherProj")

    def boom(*args, **kwargs):
        raise AssertionError("--check wrote something")

    for name in ("write_text", "write_config", "git_write"):
        monkeypatch.setattr(init_mod, name, boom)
    monkeypatch.setattr(os, "symlink", boom)

    before = everything(vault)
    code, out, _ = cli("init", "--check")
    assert code == 1 and out
    assert everything(vault) == before


def test_check_writes_nothing_for_a_wired_repo(vault, repo, cli, monkeypatch):
    add_remote(repo, vault.root)
    cli("init", "TestProj")
    before = everything(vault)
    for name in ("write_text", "write_config", "git_write"):
        monkeypatch.setattr(init_mod, name, lambda *a, **k: 1 / 0)
    cli("init", "--check", "TestProj")
    assert everything(vault) == before


def test_check_notes_branches_on_the_fallback(vault, repo, cli):
    repo("checkout", "-q", "-b", "bare-named", "main")
    _, out, _ = cli("init", "--check", "TestProj")
    assert 'note: 1 branch on "*"' in out


def test_check_note_alone_does_not_make_a_repo_incomplete(vault, repo, cli):
    repo("checkout", "-q", "-b", "bare-named", "main")
    add_remote(repo, vault.root)
    cli("init", "TestProj")
    code, out, _ = cli("init", "--check", "TestProj")
    assert code == 0 and "ok · note:" in out


def test_check_reports_a_missing_anchor(vault, repo, cli):
    add_remote(repo, vault.root)
    cli("init", "TestProj")
    (vault.context / "TestProj.md").unlink()
    code, out, _ = cli("init", "--check", "TestProj")
    assert code == 1 and "no TestProj.md anchor in the context vault" in out


def test_check_reports_an_oversized_file(vault, repo, cli, monkeypatch):
    monkeypatch.setattr(init_mod, "LIMIT_BYTES", 1024)
    (vault.projects / "TestProj" / "huge.bin").write_bytes(b"x" * 4096)
    code, out, _ = cli("init", "--check", "TestProj")
    assert code == 1 and "file(s) over 50 MB" in out and "huge.bin" in out


def test_check_reports_a_directory_with_no_git(vault, repo, cli):
    holder = vault.projects / "NoGit"
    holder.mkdir()
    (holder / ".docket.toml").write_text('project_id = "NoGit"\n')
    _, out, _ = cli("init", "--check")
    assert "NoGit — missing: no git repository" in out


def test_check_of_one_repo_ignores_the_others(vault, repo, cli):
    make_repo(vault.projects, vault.root, "OtherProj", project_id="OtherProj")
    _, out, _ = cli("init", "--check", "TestProj")
    assert "OtherProj" not in out


# --- templates are data, not inline strings ----------------------------------


def test_templates_live_in_the_package():
    from docket import templates

    root = Path(templates.__file__).parent
    for name in ("agents-stanza.md", "gitignore", "pre-commit"):
        assert (root / name).is_file()
    assert templates.agents_stanza().startswith("## Research log")
    assert "50" in templates.pre_commit_hook()


def test_no_module_inlines_the_stanza():
    """A second copy of the stanza is the thing that drifts."""
    from docket import templates

    first = templates.agents_stanza().splitlines()[1]
    src = Path(init_mod.__file__).parent.parent
    for path in src.rglob("*.py"):
        assert first not in path.read_text(encoding="utf-8"), path
