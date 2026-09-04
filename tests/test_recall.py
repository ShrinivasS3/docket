import os
import shutil
import stat
from pathlib import Path

from docket import fsio
from docket.commands import recall
from tests.conftest import snapshot

GOTCHA = (
    "gotcha",
    "--symptom",
    "Resonance trend appears where none exists",
    "--cause",
    "Forward Euler is unstable under rotation",
    "--fix",
    "Use RK4",
    "--scope",
    "oscillators, numerical-integration",
    "--project",
    "TestProj",
    "--note",
    "BODYONLY sentinel that recall must never print",
)
IDEA = (
    '---\ncategories: "[[Ideas]]"\ntype: "[[TestProj]]"\n'
    'status: "[[Falsified]]"\ndocket_id: testproj-0004\n'
    "title: Temporal aggregation before the readout\n"
    "scope: [temporal-aggregation, fmri]\n---\n\n"
    "Averaging temporal windows before the readout lost the effect. IDEABODY.\n"
)
LECTURE = (
    "# Lecture\n\nIntro line.\n"
    "Temporal aggregation of EEG windows was discussed here.\n"
    "Next line.\nUnrelated tail.\n"
)


def _setup(vault, cli):
    cli(*GOTCHA)
    (vault.context / "idea-testproj-0004-temporal-aggregation.md").write_text(IDEA)
    (vault.personal / "Lecture notes.md").write_text(LECTURE)
    (vault.personal / "Other.md").write_text("Nothing relevant here.\n")


def test_recall_context_hit_is_frontmatter_only(vault, cli):
    _setup(vault, cli)
    code, out, _ = cli("recall", "resonance")
    assert code == 0
    assert out.startswith('1 hit(s) for "resonance": 1 context record(s), 0 personal')
    assert "[context] X0001 · Gotchas · TestProj · status: -" in out
    assert "  Resonance trend appears where none exists" in out
    assert "  scope: oscillators, numerical-integration" in out
    assert "  gotcha-X0001-resonance-trend-appears-where-none-exists.md" in out
    assert "BODYONLY" not in out and "Cause." not in out and "Use RK4" not in out


def test_recall_personal_hit_shows_matched_line_plus_one_each_side(vault, cli):
    _setup(vault, cli)
    code, out, _ = cli("recall", "temporal aggregation")
    assert code == 0
    assert out.startswith(
        '2 hit(s) for "temporal aggregation": 1 context record(s), 1 personal note(s)'
    )
    assert "[context] testproj-0004 · Ideas · TestProj · status: Falsified" in out
    assert "  scope: temporal-aggregation, fmri" in out
    assert "IDEABODY" not in out
    tail = out.split("[personal] Lecture notes.md:4\n")[1].rstrip("\n").split("\n")
    assert tail == [
        "  > Intro line.",
        "  > Temporal aggregation of EEG windows was discussed here.",
        "  > Next line.",
    ]
    assert "Unrelated tail" not in out and "Other.md" not in out


def test_recall_words_may_be_on_different_lines(vault, cli):
    _setup(vault, cli)
    (vault.personal / "Split.md").write_text("temporal stuff\nmore\naggregation here\n")
    code, out, _ = cli("recall", "Temporal AGGREGATION")
    assert code == 0 and "[personal] Split.md:1" in out
    assert "  > temporal stuff\n  > more\n" in out
    assert "  > aggregation here" not in out  # only one line either side


def test_recall_over_cap_reports_counts_and_shows_nothing(vault, cli):
    _setup(vault, cli)
    for i in range(25):
        (vault.personal / f"note{i:02d}.md").write_text(f"common word here {i}\n")
    code, out, _ = cli("recall", "common")
    assert code == 0
    assert out.startswith('25 hit(s) for "common": 0 context record(s), 25 personal')
    assert "over the 40-line cap" in out and "tighten the query" in out
    assert "note00.md" not in out and "  >" not in out


def test_recall_no_hits(vault, cli):
    _setup(vault, cli)
    code, out, _ = cli("recall", "zzz-nothing-matches")
    assert code == 0 and out.strip() == 'no hits for "zzz-nothing-matches"'


def test_recall_full_prints_whole_record(vault, cli):
    _setup(vault, cli)
    code, out, _ = cli("recall", "--full", "x0001")
    assert code == 0
    assert out.startswith("[context] gotcha-X0001-resonance-trend-appears-where")
    assert 'categories: "[[Gotchas]]"' in out and "BODYONLY" in out
    code, _, err = cli("recall", "--full", "X9999")
    assert code == 2 and "no context record with docket_id X9999" in err
    code, _, err = cli("recall")
    assert code == 2 and "needs a query" in err


def test_recall_without_personal_root_searches_context_only(vault, cli):
    _setup(vault, cli)
    shutil.rmtree(vault.personal)
    code, out, _ = cli("recall", "temporal aggregation")
    assert code == 0 and "[context] testproj-0004" in out
    assert "[personal]" not in out


def test_recall_has_no_write_path_to_the_personal_root(vault, cli, monkeypatch):
    """Three guards: the only write helper is stubbed to fail, the personal root
    is made read-only for the call, and the module source names no write API."""
    _setup(vault, cli)
    before = snapshot(*vault.roots)

    def refuse(*_args, **_kwargs):
        raise AssertionError("recall reached a write helper")

    monkeypatch.setattr(fsio, "write_text", refuse)
    locked = []
    for path in [vault.personal, *vault.personal.rglob("*")]:
        mode = path.stat().st_mode
        locked.append((path, mode))
        os.chmod(path, mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    try:
        code, out, _ = cli("recall", "temporal aggregation")
    finally:
        for path, mode in reversed(locked):
            os.chmod(path, mode)
    assert code == 0 and "[personal] Lecture notes.md:4" in out
    assert snapshot(*vault.roots) == before

    source = Path(recall.__file__).read_text()
    for forbidden in (
        "fsio",
        "write_text",
        "write_bytes",
        "os.replace",
        "unlink",
        "rename",
        "mkdir",
        "open(",
    ):
        assert forbidden not in source, forbidden
