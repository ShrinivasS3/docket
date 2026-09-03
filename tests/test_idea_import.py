from docket import frontmatter as fm
from docket.commands.idea import status_for
from tests.conftest import days_ago, snapshot

EXPECTED = {
    "idea-testproj-0001-phase-1-old-one.md": ("phase-1-old-one", "Parked", False),
    "idea-testproj-0002-merged-one.md": ("experiments/merged-one", "Completed", True),
    "idea-testproj-0003-fresh-one.md": ("experiments/fresh-one", "In Progress", False),
}


def _ideas(vault):
    return sorted(p.name for p in vault.context.glob("idea-*.md"))


def test_status_mapping_rules():
    assert status_for(True, 0) == "Completed"
    assert status_for(True, 500) == "Completed"
    assert status_for(False, 0) == "In Progress"
    assert status_for(False, 89) == "In Progress"
    assert status_for(False, 90) == "Parked"
    assert status_for(False, 400) == "Parked"


def test_import_maps_branches_to_status(vault, repo, cli):
    code, out, _ = cli("idea", "import", "--repo", "TestProj")
    assert code == 0, out
    assert _ideas(vault) == sorted(EXPECTED)
    for name, (branch, status, merged) in EXPECTED.items():
        fields, body = fm.load((vault.context / name).read_text())
        assert fields["branch"] == branch
        assert fields["status"] == f"[[{status}]]"
        assert fields["merged"] is merged
        assert fields["categories"] == "[[Ideas]]"
        assert fields["type"] == "[[TestProj]]"
        assert fields["gate"] == ""
        assert fields["verdict"] == "pending"
        assert str(fields["created"]) == "2026-09-03"
    assert "skip       main  (protected)" in out
    assert "skip       worktree-agent-7  (protected)" in out
    assert "skip       fix/some-bug  (kind=gotcha)" in out
    assert (
        "TestProj: 6 branches -> 3 notes (3 create, 0 update, 0 unchanged, 3 skipped)"
        in out
    )


def test_note_shape_matches_minehq_frontmatter(vault, repo, cli):
    cli("idea", "import", "--repo", "TestProj")
    text = (vault.context / "idea-testproj-0003-fresh-one.md").read_text()
    assert text == (
        "---\n"
        'categories: "[[Ideas]]"\n'
        'type: "[[TestProj]]"\n'
        'status: "[[In Progress]]"\n'
        "docket_id: testproj-0003\n"
        "title: Fresh one\n"
        "branch: experiments/fresh-one\n"
        "created: 2026-09-03\n"
        f"last_commit: {days_ago(1).isoformat()}\n"
        "merged: false\n"
        'gate: ""\n'
        "verdict: pending\n"
        "---\n"
        "\n"
        "# Fresh one\n"
    )


def test_import_is_idempotent(vault, repo, cli):
    cli("idea", "import", "--repo", "TestProj")
    before = snapshot(*vault.roots)
    code, out, _ = cli("idea", "import", "--repo", "TestProj")
    assert code == 0
    assert snapshot(*vault.roots) == before
    assert (
        "TestProj: 6 branches -> 3 notes (0 create, 0 update, 3 unchanged, 3 skipped)"
        in out
    )


def test_reimport_updates_status_without_duplicating(vault, repo, cli):
    cli("idea", "import", "--repo", "TestProj")
    repo("merge", "-q", "--ff-only", "experiments/fresh-one")
    code, out, _ = cli("idea", "import", "--repo", "TestProj")
    assert code == 0
    assert _ideas(vault) == sorted(EXPECTED)  # no new files
    fields, _ = fm.load((vault.context / "idea-testproj-0003-fresh-one.md").read_text())
    assert fields["status"] == "[[Completed]]"
    assert fields["merged"] is True
    assert fields["docket_id"] == "testproj-0003"
    assert "update     idea-testproj-0003-fresh-one.md  [[Completed]]" in out


def test_reimport_preserves_hand_edits_and_manual_status(vault, repo, cli):
    cli("idea", "import", "--repo", "TestProj")
    path = vault.context / "idea-testproj-0003-fresh-one.md"
    text = path.read_text()
    text = text.replace('status: "[[In Progress]]"', 'status: "[[Falsified]]"')
    text = text.replace(
        'gate: ""', "gate: MLP beats ridge by 10%\ngate_date: 2026-12-01"
    )
    text += "\n## Log\n- tried it, nope\n"
    path.write_text(text)
    before = path.read_text()
    code, out, _ = cli("idea", "import", "--repo", "TestProj")
    assert code == 0 and path.read_text() == before
    fields, body = fm.load(path.read_text())
    assert fields["status"] == "[[Falsified]]"
    assert "## Log" in body


def test_reimport_after_hand_edit_only_touches_managed_fields(vault, repo, cli):
    cli("idea", "import", "--repo", "TestProj")
    path = vault.context / "idea-testproj-0003-fresh-one.md"
    path.write_text(path.read_text() + "\nHand-written body line.\n")
    repo("merge", "-q", "--ff-only", "experiments/fresh-one")
    cli("idea", "import", "--repo", "TestProj")
    text = path.read_text()
    assert 'status: "[[Completed]]"' in text and "merged: true" in text
    assert text.endswith("\nHand-written body line.\n")


def test_dry_run_writes_nothing_but_reports_plan(vault, repo, cli):
    before = snapshot(*vault.roots)
    code, out, _ = cli("idea", "import", "--repo", "TestProj", "--dry-run")
    assert code == 0
    assert snapshot(*vault.roots) == before
    assert out.count("[dry-run] create") == 3
    assert "[dry-run] TestProj: 6 branches -> 3 notes" in out


def test_numbering_continues_from_existing_ids(vault, repo, cli):
    cli("idea", "import", "--repo", "TestProj")
    repo("checkout", "-q", "-b", "experiments/newest", "main")
    repo.commit("newest", days_ago(0))
    repo("checkout", "-q", "main")
    cli("idea", "import", "--repo", "TestProj")
    assert "idea-testproj-0004-newest.md" in _ideas(vault)


def test_missing_repo_is_an_error(vault, cli):
    code, _, err = cli("idea", "import", "--repo", "Nope")
    assert code == 2 and "repo not found" in err


def test_branch_sharing_a_name_with_a_path_still_imports(vault, repo, cli):
    # A directory named like a branch makes bare `git log <ref>` ambiguous.
    (repo.path / "experiments" / "fresh-one").mkdir(parents=True)
    (repo.path / "experiments" / "fresh-one" / "run.txt").write_text("x")
    code, out, _ = cli("idea", "import", "--repo", "TestProj")
    assert code == 0, out
    assert "idea-testproj-0003-fresh-one.md" in _ideas(vault)


def test_import_reports_matched_pattern_per_branch(vault, repo, cli):
    code, out, _ = cli("idea", "import", "--repo", "TestProj")
    assert code == 0, out
    assert "experiments/merged-one  pattern=experiments/*" in out
    assert "experiments/fresh-one  pattern=experiments/*" in out
    assert "phase-1-old-one  pattern=phase-*" in out
    assert "skip       fix/some-bug  (kind=gotcha)  pattern=fix/*" in out
    # protected branches are never matched, so they carry no pattern
    assert "skip       main  (protected)\n" in out
    assert "skip       worktree-agent-7  (protected)\n" in out


def test_dry_run_lists_fallback_branches(vault, repo, cli):
    repo("checkout", "-q", "-b", "bare-name", "main")
    repo.commit("bare", days_ago(2))
    repo("checkout", "-q", "main")
    code, out, _ = cli("idea", "import", "--repo", "TestProj", "--dry-run")
    assert code == 0, out
    assert "[dry-run] create     idea-testproj-0003-bare-name.md" in out
    assert "bare-name  pattern=*" in out
    assert '[dry-run] fallback "*" (1 branch, ' in out
    assert out.rstrip().endswith("): bare-name")
    # a real run still names the pattern per branch but adds no summary
    code, out, _ = cli("idea", "import", "--repo", "TestProj")
    assert code == 0, out
    assert "bare-name  pattern=*" in out
    assert 'fallback "*"' not in out


def test_dry_run_reports_no_fallback_when_every_branch_is_namespaced(vault, repo, cli):
    _, out, _ = cli("idea", "import", "--repo", "TestProj", "--dry-run")
    assert out.rstrip().endswith('[dry-run] fallback "*": none')
