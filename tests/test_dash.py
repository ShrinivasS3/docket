from docket.markers import begin_marker, end_marker
from tests.conftest import (
    DASHBOARD,
    add_remote,
    days_ago,
    make_repo,
    set_mtime,
    snapshot,
)

FOCUS_PAIR = f"\n{begin_marker('focus')}\nstale\n{end_marker('focus')}\n"
OVERDUE = (
    '---\ncategories: "[[Ideas]]"\ntype: "[[TestProj]]"\n'
    'status: "[[In Progress]]"\ndocket_id: testproj-0009\n'
    "gate_date: 2026-08-30\nverdict: pending\n---\n"
)


def _focus(text: str) -> str:
    return text.split(begin_marker("focus"))[1].split(end_marker("focus"))[0]


def _register(path):
    path.mkdir(exist_ok=True)
    (path / ".docket.toml").write_text(f'project_id = "{path.name}"\n')


def _setup(vault, repo):
    title = "# Life HQ Dashboard\n"
    vault.dashboard.write_text(DASHBOARD.replace(title, title + FOCUS_PAIR, 1))
    (vault.context / "deadlines.yaml").write_text(
        "- venue: BrainBodyFM\n  date: 2026-09-05\n  for: [eeg-omega]\n"
        "- venue: COSYNE 2027\n  date: null\n  confirmed: false\n  for: [TestProj]\n"
        "- venue: Yesterday Conf\n  date: 2026-09-02\n"
        "- venue: ML4H\n  date: 2026-09-21\n  for: [stereopose3d]\n"
    )
    (vault.context / "idea-testproj-0009-overdue.md").write_text(OVERDUE)
    _register(vault.projects / "NoGit")
    (vault.projects / "Unregistered").mkdir()  # no toml: invisible to dash
    idle = make_repo(vault.projects, vault.root, "IdleProj", project_id="IdleProj")
    add_remote(idle, vault.root)
    idle.commit("last", days_ago(6))  # 1 unpushed commit, 6d old
    add_remote(repo, vault.root)  # TestProj: fully pushed
    (repo.path / "scratch.txt").write_text("dirty today")  # fresh: not blocking


def test_dash_md_regenerates_focus_and_ages_scratch(vault, repo, cli):
    _setup(vault, repo)
    cli("capture", "old note")
    vault.dashboard.write_text(
        vault.dashboard.read_text().replace(
            "- 2026-09-03: old note", "- 2026-08-31: old note"
        )
    )
    code, out, _ = cli("dash", "--md")
    assert code == 0 and out.startswith("updated"), out
    text = vault.dashboard.read_text()
    focus = _focus(text)
    assert "stale" not in focus
    assert focus.strip().split("\n")[:4] == [
        "> [!danger] Blocking",
        "> - testproj-0009 — gate 2026-08-30 passed 4d ago, verdict pending",
        "> - IdleProj — 1 unpushed commit, oldest 6d",
        "> - NoGit — no git repository",
    ]
    assert "TestProj —" not in focus  # fresh dirty file is normal working state
    assert "Unregistered" not in focus
    assert "`2d` BrainBodyFM · eeg-omega" in focus
    assert "`18d` ML4H · stereopose3d" in focus
    assert "`?` COSYNE 2027 · TestProj · unconfirmed · date unknown" in focus
    assert "Yesterday Conf" not in focus
    assert "`6d` IdleProj" in focus
    assert "`5d` TestProj" in focus
    assert "generated 2026-09-03" in focus
    assert "- 2026-08-31: old note · 3d" in text
    assert "- [ ] systemic check of hard bound" in text
    assert text.startswith("# Life HQ Dashboard\n\n" + begin_marker("focus"))


def test_blocking_is_capped_with_overflow_line(vault, repo, cli):
    _setup(vault, repo)
    for name in ("A1", "A2", "A3", "A4"):
        _register(vault.projects / name)  # four more "no git" entries -> 7 total
    cli("dash", "--md")
    lines = [
        line
        for line in _focus(vault.dashboard.read_text()).split("\n")
        if line.startswith("> - ")
    ]
    assert len(lines) == 6
    assert lines[0].startswith("> - testproj-0009")
    assert lines[-1] == "> - +2 more — run `docket check`"


def test_cap_is_configurable(vault, repo, cli):
    _setup(vault, repo)
    vault.config.write_text(vault.config.read_text() + "\n[dash]\nmax_blocking = 1\n")
    cli("dash", "--md")
    lines = [
        line
        for line in _focus(vault.dashboard.read_text()).split("\n")
        if line.startswith("> - ")
    ]
    assert lines == [
        "> - testproj-0009 — gate 2026-08-30 passed 4d ago, verdict pending",
        "> - +2 more — run `docket check`",
    ]


def test_stale_uncommitted_appears_after_unpushed(vault, repo, cli):
    _setup(vault, repo)
    old = repo.path / "forgotten.txt"
    old.write_text("x")
    set_mtime(old, days_ago(10))
    cli("dash", "--md")
    focus = _focus(vault.dashboard.read_text())
    assert "> - TestProj — 2 uncommitted paths, oldest 10d" in focus
    assert focus.index("IdleProj") < focus.index("TestProj —") < focus.index("NoGit")


def test_dash_md_is_idempotent(vault, repo, cli):
    _setup(vault, repo)
    cli("capture", "note")
    cli("dash", "--md")
    before = snapshot(*vault.roots)
    code, out, _ = cli("dash", "--md")
    assert code == 0 and out.startswith("unchanged")
    assert snapshot(*vault.roots) == before


def test_dash_without_focus_markers_skips_block(vault, repo, cli):
    cli("capture", "note")
    before = vault.dashboard.read_text()
    code, out, _ = cli("dash", "--md")
    assert code == 0 and "focus block skipped" in out
    after = vault.dashboard.read_text()
    assert begin_marker("focus") not in after
    assert after == before.replace("- 2026-09-03: note", "- 2026-09-03: note · 0d")


def test_dash_stdout_only_writes_nothing(vault, repo, cli):
    _setup(vault, repo)
    before = snapshot(*vault.roots)
    code, out, _ = cli("dash")
    assert code == 0 and "> [!danger] Blocking" in out
    assert snapshot(*vault.roots) == before


def test_dash_dry_run_writes_nothing(vault, repo, cli):
    _setup(vault, repo)
    before = snapshot(*vault.roots)
    code, out, _ = cli("dash", "--md", "--dry-run")
    assert code == 0 and out.startswith("[dry-run] updated")
    assert "--- focus block ---" in out
    assert snapshot(*vault.roots) == before


def test_dash_nothing_blocking(vault, cli):
    vault.dashboard.write_text(DASHBOARD + FOCUS_PAIR)
    code, out, _ = cli("dash", "--md")
    assert code == 0
    text = vault.dashboard.read_text()
    assert "> [!success] Nothing blocking" in text
    assert "_(nothing idle)_" in text
    assert "_(no upcoming deadlines in deadlines.yaml)_" in text


def test_idle_is_capped_with_overflow_line(vault, repo, cli):
    _setup(vault, repo)  # TestProj 5d, IdleProj 6d already idle
    for name, age in (("q1", 30), ("q2", 20), ("q3", 10), ("q4", 9), ("q5", 8)):
        git = make_repo(vault.projects, vault.root, name, project_id=name)
        add_remote(git, vault.root)
        git.commit("x", days_ago(age))
    cli("dash", "--md")
    focus = _focus(vault.dashboard.read_text())
    idle = focus.split("**Idle**")[1].split("<sub>")[0].strip().split("\n")
    assert idle == [
        "`30d` q1",
        "`20d` q2",
        "`10d` q3",
        "`9d` q4",
        "`8d` q5",
        "+2 more — run `docket check`",
    ]


def test_idle_cap_is_configurable(vault, repo, cli):
    _setup(vault, repo)
    vault.config.write_text(vault.config.read_text() + "\n[dash]\nmax_idle = 1\n")
    cli("dash", "--md")
    focus = _focus(vault.dashboard.read_text())
    idle = focus.split("**Idle**")[1].split("<sub>")[0].strip().split("\n")
    assert idle == ["`6d` IdleProj", "+1 more — run `docket check`"]
