from pathlib import Path

from docket import fsio
from docket.commands import brief
from tests.conftest import add_remote, days_ago, make_repo, snapshot


def _idea(vault, num, title, *, status="Completed", branch="", gate="", gate_date=None,
          verdict="pending", last_commit="2026-08-19"):  # fmt: skip
    slug = title.lower().replace(" ", "-")
    extra = f"gate_date: {gate_date}\n" if gate_date else ""
    (vault.context / f"idea-testproj-{num:04d}-{slug}.md").write_text(
        f'---\ncategories: "[[Ideas]]"\ntype: "[[TestProj]]"\nstatus: "[[{status}]]"\n'
        f"docket_id: testproj-{num:04d}\ntitle: {title}\nbranch: {branch}\n"
        f"created: 2026-09-01\nlast_commit: {last_commit}\nmerged: false\n"
        f'gate: "{gate}"\n{extra}verdict: {verdict}\n---\n\n# {title}\n'
    )


def _gotcha(cli, project, symptom, scope):
    cli("gotcha", "--symptom", symptom, "--cause", "c", "--fix", "f",
        "--scope", scope, "--project", project)  # fmt: skip


def _populate(vault, repo, cli):
    add_remote(repo, vault.root)  # everything pushed as of 2026-09-02
    repo("checkout", "-q", "experiments/fresh-one")
    repo.commit("more", days_ago(0))
    repo.commit("more-again", days_ago(0))  # two unpushed commits on the branch
    (repo.path / "NORTH_STAR.md").write_text(
        "---\ntitle: north\n---\n# North star\n\n<!-- keep short -->\n"
        "> This supersedes the old north star; an aside, not the claim.\n\n"
        "---\n\n## 1. The claim\n"
        "Grids emerge from prediction alone,\nnot from supervision.\n\n"
        "Second paragraph is not the claim.\n"
    )
    (repo.path / "experiments").mkdir()
    rows = ["run_id\tidea\tmetric\tvalue\tnote"]
    rows += [f"r{i}\t0003\tgridness\t0.3{i}\tnote {i}" for i in range(1, 6)]
    (repo.path / "experiments" / "RESULTS.tsv").write_text("\n".join(rows) + "\n")
    _idea(vault, 3, "Grid emergence under prediction", status="In Progress",
          branch="experiments/fresh-one", gate="grids appear", gate_date="2026-09-30")  # fmt: skip  # noqa: E501
    _idea(
        vault, 6, "Readout bottleneck", status="In Progress", last_commit="2026-08-01"
    )
    for num, title in ((1, "Plain gaussian targets"), (2, "Cross entropy on dog"),
                       (4, "Bigger predictor"), (5, "Longer horizon")):  # fmt: skip
        _idea(vault, num, title, status="Falsified", verdict="refutes")
    _gotcha(cli, "TestProj", "Filed here", "integration")
    _gotcha(cli, "OtherProj", "Overlaps by scope", "readout, tempo")
    _gotcha(cli, "OtherProj", "No overlap at all", "hemodynamics")
    (vault.context / "deadlines.yaml").write_text(
        "- venue: ICLR abstract\n  date: 2026-09-17\n  for: [TestProj]\n"
        "- venue: Sooner but done\n  date: 2026-09-05\n  for: [TestProj]\n  status: done\n"  # noqa: E501
        "- venue: Other venue\n  date: 2026-09-04\n  for: [OtherProj]\n"
        "- venue: Later\n  date: 2026-12-01\n  for: [testproj]\n"
    )


def test_brief_fully_populated(vault, repo, cli):
    _populate(vault, repo, cli)
    code, out, _ = cli("brief", "TestProj")
    assert code == 0
    lines = out.rstrip("\n").split("\n")
    assert lines == [
        "# TestProj — brief, 2026-09-03",
        "Standing claim: Grids emerge from prediction alone, not from supervision.",
        "Branch:         experiments/fresh-one · 2 commits since last push (2026-09-02)",  # noqa: E501
        "Active idea:    0003 — Grid emergence under prediction. Gate 2026-09-30.",
        "Last 3 runs:    r3 0003 gridness 0.33; r4 0003 gridness 0.34; r5 0003 gridness 0.35",  # noqa: E501
        "Falsified here: 0005 Longer horizon; 0004 Bigger predictor; 0002 Cross entropy on dog; +1 more",  # noqa: E501
        "Gotchas:        X0001 (this project); X0002 (readout)",
        "Deadline:       ICLR abstract in 14d (2026-09-17)",
    ]
    assert len(out) <= brief.BUDGET_CHARS


def test_brief_bare_repo(vault, cli, capsys):
    bare = vault.projects / "Bare"
    bare.mkdir()
    (bare / ".docket.toml").write_text('project_id = "Bare"\n')
    code, out, _ = cli("brief", "Bare")
    assert code == 0
    assert out.rstrip("\n").split("\n") == [
        "# Bare — brief, 2026-09-03",
        "Branch:         no git repository",
        "Active idea:    none",
        "Last 3 runs:    no ledger",
        "Falsified here: none marked (0 stubs)",
        "Gotchas:        none",
        "Deadline:       none",
    ]
    print("\n" + out, end="")  # visible with pytest -s


def test_brief_ideas_but_no_ledger(vault, repo, cli):
    cli("idea", "import", "--repo", "TestProj")
    code, out, _ = cli("brief", "TestProj")
    assert code == 0
    lines = out.rstrip("\n").split("\n")
    assert "Standing claim" not in out
    assert lines[1] == "Branch:         main · no remote"
    assert lines[2] == "Active idea:    0003 — Fresh one. Gate none set."
    assert lines[3] == "Last 3 runs:    no ledger"
    assert lines[4:] == [
        # 0002 is unjudged, 0003 has no gate; 0001 is Parked (neither)
        "Falsified here: none marked (2 stubs)",
        "Gotchas:        none",
        "Deadline:       none",
    ]


def test_brief_active_idea_prefers_current_branch(vault, repo, cli):
    _populate(vault, repo, cli)
    repo("checkout", "-q", "main")
    code, out, _ = cli("brief", "TestProj")
    # no idea on main: most recently committed In Progress idea wins
    assert "Active idea:    0003 — Grid emergence under prediction." in out


def test_brief_fits_budget_by_tightening(vault, repo, cli):
    _populate(vault, repo, cli)
    long = "Claim " * 400
    (repo.path / "NORTH_STAR.md").write_text(f"# N\n\n{long}\n")
    for num in range(10, 20):
        _idea(
            vault,
            num,
            f"Falsified idea number {num} with a long title",
            status="Falsified",
        )
    code, out, _ = cli("brief", "TestProj")
    assert code == 0 and len(out) <= brief.BUDGET_CHARS
    assert "Standing claim: Claim Claim" in out and "…" in out
    assert "Falsified here: 0019 Falsified idea number 19…" in out or "+" in out


def test_brief_resolves_project_id_and_rejects_unknown(vault, repo, cli):
    other = make_repo(vault.projects, vault.root, "other-dir", project_id="OtherProj")
    assert other.path.is_dir()
    code, out, _ = cli("brief", "otherproj")
    assert code == 0 and out.startswith("# OtherProj — brief, 2026-09-03")
    code, _, err = cli("brief", "Nowhere")
    assert code == 2 and "no project named Nowhere" in err


def test_brief_never_writes(vault, repo, cli, monkeypatch):
    _populate(vault, repo, cli)
    before = snapshot(*vault.roots)

    def refuse(*_a, **_k):
        raise AssertionError("brief reached a write helper")

    monkeypatch.setattr(fsio, "write_text", refuse)
    code, out, _ = cli("brief", "TestProj")
    assert code == 0 and out.startswith("# TestProj")
    assert snapshot(*vault.roots) == before
    source = Path(brief.__file__).read_text()
    for forbidden in ("fsio", "write_text", "write_bytes", "os.replace", "unlink",
                      "rename", "mkdir", "open("):  # fmt: skip
        assert forbidden not in source, forbidden


def test_brief_shows_status_of_a_merged_branch_idea(vault, repo, cli):
    _populate(vault, repo, cli)
    _idea(vault, 7, "Merged one", status="Completed", branch="experiments/merged-one")
    repo("checkout", "-q", "experiments/merged-one")
    code, out, _ = cli("brief", "TestProj")
    assert code == 0
    assert "Active idea:    0007 — Merged one (Completed). Gate none set." in out
