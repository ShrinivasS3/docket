"""docket idea new: the gate refusal, branch seeding, scratch promotion, idempotency."""

import pytest

from docket import frontmatter as fm
from docket.markers import begin_marker, end_marker
from tests.conftest import days_ago, snapshot

GATE = "MLP beats ridge by 10% position MSE"


def new(cli, *args):
    return cli("idea", "new", *args)


def identity(vault, *, device="Workstation", attended=True):
    vault.config.write_text(
        vault.config.read_text()
        + f'\n[identity]\ndevice = "{device}"\nattended = {str(attended).lower()}\n'
    )


def outside_block(text: str, name: str) -> str:
    keep, inside = [], False
    for line in text.split("\n"):
        if line.strip() == begin_marker(name):
            inside = True
        elif line.strip() == end_marker(name):
            inside = False
        elif not inside:
            keep.append(line)
    return "\n".join(keep)


def scratch_lines(vault) -> list[str]:
    text = vault.dashboard.read_text()
    block = text.split(begin_marker("scratch"))[1].split(end_marker("scratch"))[0]
    return [line for line in block.split("\n") if line.strip()]


def ideas(vault) -> list[str]:
    return sorted(p.name for p in vault.context.glob("idea-*.md"))


# --- the refusal ----------------------------------------------------------


def test_refuses_without_gate_or_decide_by(vault, here, cli):
    before = snapshot(*vault.roots)
    code, out, err = new(cli, "--branch", "experiments/fresh-one")
    assert code == 2
    assert "no gate and no decide-by date" in err
    assert "--gate" in err and "--decide-by" in err
    assert "not a gate you committed to" in err
    assert snapshot(*vault.roots) == before  # nothing written, not even a stub


def test_refuses_before_touching_the_dashboard(vault, here, cli):
    cli("capture", "try a nonlinear readout")
    before = snapshot(*vault.roots)
    code, _, err = new(
        cli,
        "--branch",
        "experiments/fresh-one",
        "--from-scratch",
        "nonlinear readout",
    )
    assert code == 2 and "no gate" in err
    assert snapshot(*vault.roots) == before


def test_gate_alone_is_enough(vault, here, cli):
    code, out, _ = new(cli, "--branch", "experiments/fresh-one", "--gate", GATE)
    assert code == 0, out
    fields, _ = fm.load((vault.context / ideas(vault)[0]).read_text())
    assert fields["gate"] == GATE and "gate_date" not in fields


def test_decide_by_alone_is_enough(vault, here, cli):
    code, out, _ = new(
        cli,
        "--branch",
        "experiments/fresh-one",
        "--decide-by",
        "2026-09-30",
        "--kind",
        "exploratory",
    )
    assert code == 0, out
    fields, _ = fm.load((vault.context / ideas(vault)[0]).read_text())
    assert fields["gate"] == "" and str(fields["gate_date"]) == "2026-09-30"
    assert fields["kind"] == "exploratory"


def test_decide_by_must_be_a_date(vault, here, cli):
    before = snapshot(*vault.roots)
    code, _, err = new(
        cli, "--branch", "experiments/fresh-one", "--decide-by", "next friday"
    )
    assert code == 2 and "not a YYYY-MM-DD date" in err
    assert snapshot(*vault.roots) == before


# --- branch seeding -------------------------------------------------------

SEEDS = [
    (
        "experiments/nonlinear-readout",
        "experiments/*",
        "idea-testproj-0001-nonlinear-readout.md",
        "Nonlinear readout",
    ),
    (
        "diagnostics/readout-bottleneck",
        "diagnostics/*",
        "idea-testproj-0001-readout-bottleneck.md",
        "Readout bottleneck",
    ),
    (
        "phase-2-scale-free",
        "phase-*",
        "idea-testproj-0001-phase-2-scale-free.md",
        "Phase 2 scale free",
    ),
    ("bare-name", "*", "idea-testproj-0001-bare-name.md", "Bare name"),
]


@pytest.mark.parametrize("branch,pattern,filename,title", SEEDS)
def test_branch_seeds_title_slug_and_namespace(
    vault, here, cli, branch, pattern, filename, title
):
    here("checkout", "-q", "-b", branch, "main")
    here.commit("work", days_ago(1))
    code, out, _ = new(cli, "--gate", GATE)  # seeds from the checkout
    assert code == 0, out
    assert ideas(vault) == [filename]
    assert f"create     {filename}  [[In Progress]]  {branch}  pattern={pattern}" in out
    fields, body = fm.load((vault.context / filename).read_text())
    assert fields["title"] == title and fields["branch"] == branch
    assert body.strip() == f"# {title}"


def test_branch_flag_overrides_the_checkout(vault, here, cli):
    code, out, _ = new(cli, "--branch", "experiments/merged-one", "--gate", GATE)
    assert code == 0, out
    assert ideas(vault) == ["idea-testproj-0001-merged-one.md"]
    fields, _ = fm.load((vault.context / ideas(vault)[0]).read_text())
    assert fields["branch"] == "experiments/merged-one"


def test_a_freshly_cut_branch_is_in_progress_not_completed(vault, here, cli):
    # The common case: `idea new` rides `git checkout -b`, so the branch has no
    # commits of its own and looks exactly like a fast-forward-merged one.
    here("checkout", "-q", "-b", "experiments/just-cut", "main")
    code, out, _ = new(cli, "--gate", GATE)
    assert code == 0, out
    fields, _ = fm.load((vault.context / ideas(vault)[0]).read_text())
    assert fields["status"] == "[[In Progress]]" and fields["merged"] is False


def test_a_freshly_cut_branch_is_not_judged_on_a_rerun(vault, here, cli):
    here("checkout", "-q", "-b", "experiments/just-cut", "main")
    new(cli, "--gate", GATE)
    before = snapshot(*vault.roots)
    code, out, _ = new(cli, "--gate", GATE)
    assert code == 0, out
    assert snapshot(*vault.roots) == before  # status does not flip to Completed


def test_import_is_what_moves_a_merged_branch_to_completed(vault, here, cli):
    """`idea new` files and gates; `idea import` adjudicates. The gate survives."""
    new(cli, "--branch", "experiments/fresh-one", "--gate", GATE)
    here("merge", "-q", "--ff-only", "experiments/fresh-one")
    fields, _ = fm.load((vault.context / ideas(vault)[0]).read_text())
    assert fields["status"] == "[[In Progress]]"
    cli("idea", "import", "--repo", "TestProj")
    fields, _ = fm.load((vault.context / "idea-testproj-0001-fresh-one.md").read_text())
    assert fields["status"] == "[[Completed]]" and fields["merged"] is True
    assert fields["gate"] == GATE


def test_branch_that_does_not_exist_yet_is_noted_not_refused(vault, here, cli):
    code, out, _ = new(cli, "--branch", "experiments/not-yet", "--gate", GATE)
    assert code == 0, out
    assert "note: experiments/not-yet does not exist in TestProj yet" in out
    fields, _ = fm.load((vault.context / ideas(vault)[0]).read_text())
    assert fields["last_commit"] == "" and fields["merged"] is False
    assert fields["status"] == "[[In Progress]]"


def test_gotcha_branch_is_refused(vault, here, cli):
    before = snapshot(*vault.roots)
    code, _, err = new(cli, "--branch", "fix/some-bug", "--gate", GATE)
    assert code == 2 and "'fix/*' = 'gotcha'" in err and "docket gotcha" in err
    assert snapshot(*vault.roots) == before


def test_protected_branch_is_refused(vault, here, cli):
    code, _, err = new(cli, "--gate", GATE)  # main is checked out
    assert code == 2 and "protected branch" in err


def test_outside_a_repo_is_refused(vault, monkeypatch, cli):
    monkeypatch.chdir(vault.personal)
    code, _, err = new(cli, "--branch", "experiments/x", "--gate", GATE)
    assert code == 2 and "no repository at or above" in err


# --- the record -----------------------------------------------------------


def test_record_shape_matches_minehq_frontmatter(vault, here, cli):
    identity(vault)
    cli("idea", "import", "--repo", "TestProj")  # so parent testproj-0003 exists
    here("checkout", "-q", "-b", "experiments/nonlinear-readout", "main")
    here.commit("work", days_ago(1))
    code, out, _ = new(
        cli,
        "--gate",
        GATE,
        "--decide-by",
        "2026-09-30",
        "--parent",
        "testproj-0003",
        "--inherits",
        "G0004",
    )
    assert code == 0, out
    text = (vault.context / "idea-testproj-0004-nonlinear-readout.md").read_text()
    assert text == (
        "---\n"
        'categories: "[[Ideas]]"\n'
        'type: "[[TestProj]]"\n'
        'status: "[[In Progress]]"\n'
        "docket_id: testproj-0004\n"
        "title: Nonlinear readout\n"
        "branch: experiments/nonlinear-readout\n"
        "created: 2026-09-03\n"
        f"last_commit: {days_ago(1).isoformat()}\n"
        "merged: false\n"
        f'gate: "{GATE}"\n'
        "gate_date: 2026-09-30\n"
        "verdict: pending\n"
        "parent: testproj-0003\n"
        "inherits: [G0004]\n"
        "device: Workstation\n"
        "attended: true\n"
        "---\n"
        "\n"
        "# Nonlinear readout\n"
    )
    assert "note: parent testproj-0003 is not a record" not in out
    assert "note: inherits G0004 is not a record in the context vault" in out


def test_no_identity_table_writes_no_device(vault, here, cli):
    new(cli, "--branch", "experiments/fresh-one", "--gate", GATE)
    fields, _ = fm.load((vault.context / ideas(vault)[0]).read_text())
    assert "device" not in fields and "attended" not in fields


def test_unattended_identity_is_recorded(vault, here, cli):
    identity(vault, device="OptiPlex", attended=False)
    new(cli, "--branch", "experiments/fresh-one", "--gate", GATE)
    fields, _ = fm.load((vault.context / ideas(vault)[0]).read_text())
    assert fields["device"] == "OptiPlex" and fields["attended"] is False


def test_inherits_must_be_finding_ids(vault, here, cli):
    code, _, err = new(
        cli,
        "--branch",
        "experiments/fresh-one",
        "--gate",
        GATE,
        "--inherits",
        "0004",
    )
    assert code == 2 and "finding ids like G0004" in err


def test_numbering_continues_from_imported_records(vault, here, cli):
    cli("idea", "import", "--repo", "TestProj")  # 0001..0003
    here("checkout", "-q", "-b", "experiments/newest", "main")
    here.commit("newest", days_ago(0))
    code, out, _ = new(cli, "--gate", GATE)
    assert code == 0, out
    assert "idea-testproj-0004-newest.md" in ideas(vault)


def test_dry_run_writes_nothing(vault, here, cli):
    cli("capture", "try a nonlinear readout")
    before = snapshot(*vault.roots)
    code, out, _ = new(
        cli,
        "--branch",
        "experiments/fresh-one",
        "--gate",
        GATE,
        "--from-scratch",
        "nonlinear readout",
        "--dry-run",
    )
    assert code == 0, out
    assert out.startswith("[dry-run] create")
    assert "[dry-run] promoted   Dashboard.md scratch:" in out
    assert snapshot(*vault.roots) == before


# --- --from-scratch -------------------------------------------------------


def promote(vault, cli):
    cli("capture", "try a nonlinear readout on frozen h_t")
    before = vault.dashboard.read_text()
    code, out, err = new(
        cli,
        "--branch",
        "experiments/nonlinear-readout",
        "--gate",
        GATE,
        "--from-scratch",
        "nonlinear readout",
    )
    return code, out, err, before


def test_from_scratch_preserves_everything_outside_the_markers(vault, here, cli):
    code, out, _, before = promote(vault, cli)
    assert code == 0, out
    after = vault.dashboard.read_text()
    assert after != before  # the block did change
    assert outside_block(after, "scratch") == outside_block(before, "scratch")
    assert after.count(begin_marker("scratch")) == 1
    assert "- [ ] systemic check of hard bound" in after
    assert "14.317 - 12 steps" in after


def test_from_scratch_replaces_the_line_with_a_three_line_stub(vault, here, cli):
    code, out, _, _ = promote(vault, cli)
    assert code == 0, out
    assert scratch_lines(vault) == [
        "- 2026-09-03: try a nonlinear readout on frozen h_t"
        " → [[idea-testproj-0001-nonlinear-readout]]",
        "  - promoted 2026-09-03 · testproj-0001 · experiments/nonlinear-readout",
        f"  - gate: {GATE}",
    ]
    assert "promoted   Dashboard.md scratch: - 2026-09-03: try a nonlinear" in out


def test_from_scratch_pulls_the_text_into_the_record(vault, here, cli):
    promote(vault, cli)
    _, body = fm.load(
        (vault.context / "idea-testproj-0001-nonlinear-readout.md").read_text()
    )
    assert body.strip().split("\n") == [
        "# Nonlinear readout",
        "",
        "From the Dashboard scratch block, captured 2026-09-03:",
        "",
        "> try a nonlinear readout on frozen h_t",
    ]


def test_from_scratch_stub_carries_the_decide_by_date(vault, here, cli):
    cli("capture", "maybe try spectral pooling")
    new(
        cli,
        "--branch",
        "experiments/fresh-one",
        "--decide-by",
        "2026-09-30",
        "--kind",
        "exploratory",
        "--from-scratch",
        "spectral pooling",
    )
    assert scratch_lines(vault)[-1] == "  - decide by: 2026-09-30"


def test_from_scratch_is_idempotent_and_never_stacks_stubs(vault, here, cli):
    promote(vault, cli)
    first = vault.dashboard.read_text()
    before = snapshot(*vault.roots)
    code, out, _ = new(
        cli,
        "--branch",
        "experiments/nonlinear-readout",
        "--gate",
        GATE,
        "--from-scratch",
        "nonlinear readout",
    )
    assert code == 0, out
    assert vault.dashboard.read_text() == first
    assert snapshot(*vault.roots) == before
    assert len(scratch_lines(vault)) == 3


def test_from_scratch_survives_dash_ageing_the_line(vault, here, cli):
    promote(vault, cli)
    cli("dash", "--md")
    aged = scratch_lines(vault)
    assert aged[0].endswith("→ [[idea-testproj-0001-nonlinear-readout]] · 0d")
    new(
        cli,
        "--branch",
        "experiments/nonlinear-readout",
        "--gate",
        GATE,
        "--from-scratch",
        "nonlinear readout",
    )
    # the age suffix and the old arrow are stripped, not re-appended
    assert scratch_lines(vault)[0] == (
        "- 2026-09-03: try a nonlinear readout on frozen h_t"
        " → [[idea-testproj-0001-nonlinear-readout]]"
    )


def test_from_scratch_with_no_match_writes_nothing(vault, here, cli):
    cli("capture", "try a nonlinear readout")
    before = snapshot(*vault.roots)
    code, _, err = new(
        cli,
        "--branch",
        "experiments/fresh-one",
        "--gate",
        GATE,
        "--from-scratch",
        "spectral pooling",
    )
    assert code == 2 and "no scratch line matching" in err
    assert snapshot(*vault.roots) == before  # no orphan record left behind


def test_from_scratch_ambiguous_match_refuses_with_the_candidates(vault, here, cli):
    cli("capture", "try a nonlinear readout on h_t")
    cli("capture", "try a nonlinear readout on z_t")
    before = snapshot(*vault.roots)
    code, _, err = new(
        cli,
        "--branch",
        "experiments/fresh-one",
        "--gate",
        GATE,
        "--from-scratch",
        "nonlinear readout",
    )
    assert code == 2 and "2 scratch lines match" in err
    assert "on h_t" in err and "on z_t" in err
    assert snapshot(*vault.roots) == before


def test_from_scratch_exact_text_beats_a_substring(vault, here, cli):
    cli("capture", "nonlinear readout")
    cli("capture", "nonlinear readout on frozen h_t")
    code, out, _ = new(
        cli,
        "--branch",
        "experiments/fresh-one",
        "--gate",
        GATE,
        "--from-scratch",
        "nonlinear readout",
    )
    assert code == 0, out
    lines = scratch_lines(vault)
    assert lines[0].startswith("- 2026-09-03: nonlinear readout → [[")
    assert lines[-1] == "- 2026-09-03: nonlinear readout on frozen h_t"


def test_from_scratch_without_a_scratch_block_refuses(vault, here, cli):
    before = snapshot(*vault.roots)
    code, _, err = new(
        cli,
        "--branch",
        "experiments/fresh-one",
        "--gate",
        GATE,
        "--from-scratch",
        "anything",
    )
    assert code == 2 and "nothing to promote" in err
    assert snapshot(*vault.roots) == before


# --- idempotency and hand edits -------------------------------------------


def test_rerun_is_idempotent(vault, here, cli):
    identity(vault)
    new(cli, "--branch", "experiments/fresh-one", "--gate", GATE)
    before = snapshot(*vault.roots)
    code, out, _ = new(cli, "--branch", "experiments/fresh-one", "--gate", GATE)
    assert code == 0, out
    assert snapshot(*vault.roots) == before
    assert ideas(vault) == ["idea-testproj-0001-fresh-one.md"]
    assert out.startswith("unchanged  idea-testproj-0001-fresh-one.md")


def test_rerun_does_not_renumber_or_duplicate(vault, here, cli):
    new(cli, "--branch", "experiments/fresh-one", "--gate", GATE)
    new(cli, "--branch", "experiments/fresh-one", "--decide-by", "2026-10-01")
    assert ideas(vault) == ["idea-testproj-0001-fresh-one.md"]
    fields, _ = fm.load((vault.context / ideas(vault)[0]).read_text())
    assert fields["docket_id"] == "testproj-0001"
    assert fields["gate"] == GATE  # not supplied this run, so not cleared
    assert str(fields["gate_date"]) == "2026-10-01"


def test_hand_set_status_survives_a_rerun(vault, here, cli):
    new(cli, "--branch", "experiments/fresh-one", "--gate", GATE)
    path = vault.context / "idea-testproj-0001-fresh-one.md"
    path.write_text(
        path.read_text().replace('status: "[[In Progress]]"', 'status: "[[Falsified]]"')
        + "\n## Log\n- tried it, nope\n"
    )
    here("merge", "-q", "--ff-only", "experiments/fresh-one")
    code, out, _ = new(
        cli, "--branch", "experiments/fresh-one", "--gate", "a sharper gate"
    )
    assert code == 0, out
    fields, body = fm.load(path.read_text())
    assert fields["status"] == "[[Falsified]]"
    assert fields["gate"] == "a sharper gate"
    assert "## Log" in body and "- tried it, nope" in body
    assert "[[Falsified]]" in out


def test_rerun_over_an_imported_record_keeps_its_id(vault, here, cli):
    cli("idea", "import", "--repo", "TestProj")
    code, out, _ = new(cli, "--branch", "experiments/fresh-one", "--gate", GATE)
    assert code == 0, out
    assert ideas(vault) == [
        "idea-testproj-0001-phase-1-old-one.md",
        "idea-testproj-0002-merged-one.md",
        "idea-testproj-0003-fresh-one.md",
    ]
    fields, _ = fm.load((vault.context / "idea-testproj-0003-fresh-one.md").read_text())
    assert fields["docket_id"] == "testproj-0003" and fields["gate"] == GATE


def test_rerun_keeps_the_device_that_wrote_the_record(vault, here, cli):
    identity(vault, device="Workstation")
    new(cli, "--branch", "experiments/fresh-one", "--gate", GATE)
    vault.config.write_text(
        vault.config.read_text().replace(
            'device = "Workstation"', 'device = "OptiPlex"'
        )
    )
    new(cli, "--branch", "experiments/fresh-one", "--gate", GATE)
    fields, _ = fm.load((vault.context / ideas(vault)[0]).read_text())
    assert fields["device"] == "Workstation"


def test_scaffold_kind_is_written_and_check_leaves_it_alone(vault, here, cli):
    code, out, _ = new(
        cli,
        "--branch",
        "phase-1-old-one",
        "--decide-by",
        "2026-12-01",
        "--kind",
        "scaffold",
    )
    assert code == 0, out
    fields, _ = fm.load((vault.context / ideas(vault)[0]).read_text())
    assert fields["kind"] == "scaffold"
    code, out, _ = cli("check")
    assert "no gate" not in out


def test_rerun_inherits_the_gate_already_on_the_record(vault, here, cli):
    new(cli, "--branch", "experiments/fresh-one", "--gate", GATE)
    cli("capture", "worth a second look")
    code, out, _ = new(
        cli, "--branch", "experiments/fresh-one", "--from-scratch", "second look"
    )
    assert code == 0, out
    fields, _ = fm.load((vault.context / ideas(vault)[0]).read_text())
    assert fields["gate"] == GATE


def test_import_stub_still_has_to_supply_a_gate(vault, here, cli):
    cli("idea", "import", "--repo", "TestProj")  # writes gate: ""
    before = snapshot(*vault.roots)
    code, _, err = new(cli, "--branch", "experiments/fresh-one")
    assert code == 2 and "no gate and no decide-by date" in err
    assert snapshot(*vault.roots) == before


def test_stub_names_the_gate_the_record_already_carries(vault, here, cli):
    new(cli, "--branch", "experiments/fresh-one", "--gate", GATE)
    cli("capture", "worth promoting")
    code, out, _ = new(
        cli, "--branch", "experiments/fresh-one", "--from-scratch", "worth promoting"
    )
    assert code == 0, out
    assert scratch_lines(vault)[-1] == f"  - gate: {GATE}"


def test_hand_written_sub_bullets_are_not_eaten_by_a_promotion(vault, here, cli):
    cli("capture", "worth promoting")
    text = vault.dashboard.read_text()
    vault.dashboard.write_text(
        text.replace(
            "- 2026-09-03: worth promoting",
            "- 2026-09-03: worth promoting\n  - my own note\n  - and another",
        )
    )
    code, out, _ = new(
        cli,
        "--branch",
        "experiments/fresh-one",
        "--gate",
        GATE,
        "--from-scratch",
        "worth promoting",
    )
    assert code == 0, out
    assert scratch_lines(vault)[-2:] == ["  - my own note", "  - and another"]
    assert len(scratch_lines(vault)) == 5
