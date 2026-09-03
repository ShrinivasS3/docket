import datetime as dt

from docket.blocking import GATE, NO_GIT, STALE, UNPUSHED, all_blocking
from docket.config import load_config
from tests.conftest import TODAY, add_remote, days_ago, make_repo, set_mtime

OVERDUE = (
    '---\ncategories: "[[Ideas]]"\ntype: "[[TestProj]]"\nstatus: "[[In Progress]]"\n'
    "docket_id: testproj-0009\ngate_date: 2026-08-30\nverdict: pending\n---\n"
)


def _messages(vault):
    return [b.message for b in all_blocking(load_config(vault.config), TODAY)]


def test_repos_without_docket_toml_are_ignored(vault):
    (vault.projects / "Coursework").mkdir()  # no git, no toml
    make_repo(vault.projects, vault.root, "Unregistered")  # no toml, no remote
    assert _messages(vault) == []


def test_no_git_repository(vault):
    (vault.projects / "Empty").mkdir()
    (vault.projects / "Empty" / ".docket.toml").write_text('project_id = "Empty"\n')
    assert _messages(vault) == ["Empty — no git repository"]


def test_no_remote_configured(vault):
    make_repo(vault.projects, vault.root, "Local", project_id="Local")
    assert _messages(vault) == ["Local — no remote configured"]


def test_pushed_repo_is_quiet(vault):
    git = make_repo(vault.projects, vault.root, "Pushed", project_id="Pushed")
    add_remote(git, vault.root)
    assert _messages(vault) == []


def test_unpushed_commits_older_than_threshold(vault):
    git = make_repo(vault.projects, vault.root, "Behind", project_id="Behind")
    add_remote(git, vault.root)
    git.commit("a", days_ago(5))
    git.commit("b", days_ago(1))
    assert _messages(vault) == ["Behind — 2 unpushed commits, oldest 5d"]


def test_unpushed_commits_within_threshold_are_quiet(vault):
    git = make_repo(vault.projects, vault.root, "Fresh", project_id="Fresh")
    add_remote(git, vault.root)
    git.commit("a", days_ago(3))  # threshold is strictly greater than 3
    assert _messages(vault) == []


def test_unpushed_on_a_side_branch_counts(vault):
    git = make_repo(vault.projects, vault.root, "Side", project_id="Side")
    add_remote(git, vault.root)
    git("checkout", "-q", "-b", "experiments/never-pushed")
    git.commit("side", days_ago(20))
    git("checkout", "-q", "main")
    assert _messages(vault) == ["Side — 1 unpushed commit, oldest 20d"]


def test_fresh_uncommitted_paths_are_not_blocking(vault):
    git = make_repo(vault.projects, vault.root, "Work", project_id="Work")
    add_remote(git, vault.root)
    (git.path / "wip.txt").write_text("today")
    assert _messages(vault) == []


def test_stale_uncommitted_paths_block(vault):
    git = make_repo(vault.projects, vault.root, "Stale", project_id="Stale")
    add_remote(git, vault.root)
    (git.path / "new.txt").write_text("today")
    old = git.path / "old.txt"
    old.write_text("long ago")
    set_mtime(old, days_ago(12))
    assert _messages(vault) == ["Stale — 2 uncommitted paths, oldest 12d"]


def test_stale_within_threshold_is_quiet(vault):
    git = make_repo(vault.projects, vault.root, "Recent", project_id="Recent")
    add_remote(git, vault.root)
    path = git.path / "week.txt"
    path.write_text("x")
    set_mtime(path, days_ago(7))  # strictly greater than 7 required
    assert _messages(vault) == []


def test_deleted_paths_do_not_crash_and_renames_parse(vault):
    git = make_repo(vault.projects, vault.root, "Churn", project_id="Churn")
    add_remote(git, vault.root)
    (git.path / "init.txt").unlink()
    git("mv", "-q", "README.txt", "MOVED.txt") if (
        git.path / "README.txt"
    ).exists() else None
    assert _messages(vault) == []  # deletions have no mtime; nothing stale


def test_gate_overdue_is_most_severe(vault):
    (vault.context / "idea-testproj-0009-overdue.md").write_text(OVERDUE)
    (vault.projects / "Empty").mkdir()
    (vault.projects / "Empty" / ".docket.toml").write_text('project_id = "Empty"\n')
    make_repo(vault.projects, vault.root, "Local", project_id="Local")
    found = all_blocking(load_config(vault.config), TODAY)
    assert [b.severity for b in found] == [GATE, UNPUSHED, NO_GIT]
    assert (
        found[0].message
        == "testproj-0009 — gate 2026-08-30 passed 4d ago, verdict pending"
    )


def test_severity_order_then_name(vault):
    for name in ("zeta", "alpha"):
        git = make_repo(vault.projects, vault.root, name, project_id=name)
        add_remote(git, vault.root)
        path = git.path / "old.txt"
        path.write_text("x")
        set_mtime(path, days_ago(30))
    make_repo(vault.projects, vault.root, "mid", project_id="mid")  # no remote
    found = all_blocking(load_config(vault.config), TODAY)
    assert [(b.severity, b.key) for b in found] == [
        (UNPUSHED, "mid"),
        (STALE, "alpha"),
        (STALE, "zeta"),
    ]


def test_thresholds_come_from_config(vault):
    vault.config.write_text(
        vault.config.read_text() + "\n[dash]\nunpushed_days = 0\nstale_days = 0\n"
    )
    git = make_repo(vault.projects, vault.root, "Tight", project_id="Tight")
    add_remote(git, vault.root)
    git.commit("a", days_ago(1))
    path = git.path / "wip.txt"
    path.write_text("x")
    set_mtime(path, days_ago(1))
    assert _messages(vault) == [
        "Tight — 1 unpushed commit, oldest 1d",
        "Tight — 1 uncommitted path, oldest 1d",
    ]
    assert isinstance(TODAY, dt.date)


def _names(vault):
    from docket.blocking import resolve_repos

    return [(r.name, r.has_git) for r in resolve_repos(load_config(vault.config))]


def test_docket_toml_above_nested_repos_reports_each(vault):
    top = vault.projects / "Mono"
    top.mkdir()
    (top / ".docket.toml").write_text('project_id = "Mono"\n')
    (top / "notes.md").write_text("not a repo")
    make_repo(top, vault.root, "app")  # no remote
    infra = make_repo(top, vault.root, "infra")
    add_remote(infra, vault.root)
    assert _names(vault) == [("Mono/app", True), ("Mono/infra", True)]
    assert _messages(vault) == ["Mono/app — no remote configured"]


def test_docket_toml_below_repo_root_walks_up(vault):
    git = make_repo(vault.projects, vault.root, "Big")
    add_remote(git, vault.root)
    pkg = git.path / "pkg"
    pkg.mkdir()
    (pkg / ".docket.toml").write_text('project_id = "Big"\n')
    assert _names(vault) == [("Big", True)]
    assert _messages(vault) == []


def test_two_registrations_in_one_repo_dedupe(vault):
    git = make_repo(vault.projects, vault.root, "Twice", project_id="Twice")
    (git.path / "sub").mkdir()
    (git.path / "sub" / ".docket.toml").write_text('project_id = "Twice"\n')
    assert _names(vault) == [("Twice", True)]
    assert _messages(vault) == ["Twice — no remote configured"]


def test_vendored_repo_inside_a_repo_is_not_separate(vault):
    git = make_repo(vault.projects, vault.root, "Outer", project_id="Outer")
    add_remote(git, vault.root)
    make_repo(git.path, vault.root, "vendored")
    assert _names(vault) == [("Outer", True)]


def test_registered_dir_with_no_repo_anywhere(vault):
    top = vault.projects / "Docs"
    top.mkdir()
    (top / ".docket.toml").write_text('project_id = "Docs"\n')
    (top / "deep" / "er").mkdir(parents=True)
    assert _names(vault) == [("Docs", False)]
    assert _messages(vault) == ["Docs — no git repository"]


def test_idle_repos_sorted_most_idle_first(vault):
    from docket.blocking import idle_repos

    for name, age in (("a", 4), ("b", 40), ("c", 1)):
        git = make_repo(vault.projects, vault.root, name, project_id=name)
        add_remote(git, vault.root)
        git.commit("x", days_ago(age))
    assert idle_repos(load_config(vault.config), TODAY) == [(40, "b"), (4, "a")]
