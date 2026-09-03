IDEA = (
    '---\ncategories: "[[Ideas]]"\ntype: "[[TestProj]]"\nstatus: "[[In Progress]]"\n'
    "docket_id: testproj-0001\nbranch: experiments/x\ncreated: 2026-09-01\n"
    'merged: false\ngate: ""\nverdict: pending\n---\n\n# x\n'
)


def _write(vault, name, text):
    (vault.context / name).write_text(text)


def test_clean_vault_passes(vault, cli):
    _write(vault, "idea-testproj-0001-x.md", IDEA)
    code, out, _ = cli("check")
    assert code == 0 and out == "docket check: ok (1 records)\n"


def test_missing_anchor_fails(vault, cli):
    _write(vault, "idea-testproj-0001-x.md", IDEA.replace("[[TestProj]]", "[[Ghost]]"))
    code, out, _ = cli("check")
    assert code == 1
    assert (
        "FAIL  idea-testproj-0001-x.md: type references missing anchor [[Ghost]]" in out
    )


def test_missing_anchor_in_list_form_fails(vault, cli):
    text = IDEA.replace('status: "[[In Progress]]"', 'status:\n  - "[[Nowhere]]"')
    _write(vault, "idea-testproj-0001-x.md", text)
    code, out, _ = cli("check")
    assert code == 1 and "status references missing anchor [[Nowhere]]" in out


def test_unclosed_frontmatter_fails(vault, cli):
    _write(vault, "idea-bad.md", '---\ncategories: "[[Ideas]]"\n\n# never closed\n')
    code, out, _ = cli("check")
    assert code == 1 and "idea-bad.md: malformed frontmatter" in out


def test_invalid_yaml_frontmatter_fails(vault, cli):
    _write(vault, "idea-bad.md", "---\ncategories: [[Ideas\nstatus: : :\n---\n")
    code, out, _ = cli("check")
    assert code == 1 and "malformed frontmatter" in out


def test_non_mapping_frontmatter_fails(vault, cli):
    _write(vault, "idea-bad.md", "---\n- just\n- a list\n---\n")
    code, out, _ = cli("check")
    assert code == 1 and "not a mapping" in out


def test_overdue_gate_fails(vault, cli):
    _write(
        vault,
        "idea-testproj-0001-x.md",
        IDEA.replace('gate: ""', "gate: g\ngate_date: 2026-08-30"),
    )
    code, out, _ = cli("check")
    assert (
        code == 1 and "gate_date 2026-08-30 passed 4d ago with verdict pending" in out
    )


def test_future_gate_or_settled_verdict_passes(vault, cli):
    _write(
        vault,
        "idea-testproj-0001-x.md",
        IDEA.replace('gate: ""', "gate_date: 2026-12-01"),
    )
    assert cli("check")[0] == 0
    _write(
        vault,
        "idea-testproj-0001-x.md",
        IDEA.replace('gate: ""', "gate_date: 2026-08-30").replace(
            "verdict: pending", "verdict: refutes"
        ),
    )
    assert cli("check")[0] == 0
    # Today itself is not "passed".
    _write(
        vault,
        "idea-testproj-0001-x.md",
        IDEA.replace('gate: ""', "gate_date: 2026-09-03"),
    )
    assert cli("check")[0] == 0


def test_docket_id_collision_fails(vault, cli):
    _write(vault, "idea-testproj-0001-x.md", IDEA)
    _write(
        vault, "idea-testproj-0001-y.md", IDEA.replace("experiments/x", "experiments/y")
    )
    code, out, _ = cli("check")
    assert code == 1
    assert "docket_id testproj-0001 collides: " in out
    assert "idea-testproj-0001-x.md, idea-testproj-0001-y.md" in out


def test_all_four_classes_reported_together(vault, cli):
    _write(vault, "idea-a.md", IDEA.replace("[[Ideas]]", "[[Nope]]"))
    _write(vault, "idea-b.md", "---\nunclosed\n")
    _write(
        vault,
        "idea-c.md",
        IDEA.replace("0001", "0002").replace('gate: ""', "gate_date: 2026-01-01"),
    )
    _write(vault, "idea-d.md", IDEA.replace("0001", "0003"))
    _write(vault, "idea-e.md", IDEA.replace("0001", "0003"))
    code, out, _ = cli("check")
    assert code == 1
    assert "missing anchor" in out and "malformed" in out
    assert "verdict pending" in out and "collides" in out
    assert out.strip().endswith("problem(s) in 4 records")


def test_anchor_notes_and_readme_are_not_records(vault, cli):
    code, out, _ = cli("check")
    assert code == 0 and "(0 records)" in out


def test_check_lists_repo_blockers_uncapped_without_failing(vault, cli):
    from tests.conftest import make_repo

    for name in ("R1", "R2", "R3", "R4", "R5", "R6", "R7"):
        make_repo(vault.projects, vault.root, name, project_id=name)  # no remote
    code, out, _ = cli("check")
    assert code == 0
    warns = [line for line in out.split("\n") if line.startswith("WARN  ")]
    assert len(warns) == 7
    assert warns[0] == "WARN  R1 — no remote configured"
    idle = [line for line in out.split("\n") if line.startswith("IDLE  ")]
    assert len(idle) == 7 and idle[0] == "IDLE  R1 — 10d since last commit"
    assert out.strip().endswith("docket check: ok (0 records), 7 warning(s), 7 idle")


def test_check_failures_and_warnings_together(vault, cli):
    from tests.conftest import make_repo

    make_repo(vault.projects, vault.root, "Local", project_id="Local")
    _write(
        vault,
        "idea-testproj-0001-x.md",
        IDEA.replace('gate: ""', "gate_date: 2026-08-30"),
    )
    code, out, _ = cli("check")
    assert code == 1
    assert "FAIL  idea-testproj-0001-x.md: gate_date 2026-08-30 passed 4d ago" in out
    assert "WARN  Local — no remote configured" in out
    assert out.strip().endswith(
        "docket check: 1 problem(s), 1 warning(s), 1 idle in 1 records"
    )
