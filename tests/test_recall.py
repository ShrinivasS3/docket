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


def _order(out: str, *needles: str) -> list[int]:
    return [out.index(n) for n in needles]


def test_recall_context_hit_is_frontmatter_only(vault, cli):
    _setup(vault, cli)
    code, out, _ = cli("recall", "resonance")
    assert code == 0
    assert out.startswith('1 hit(s) for "resonance": 1 context record(s), 0 personal')
    assert (
        "\n## context records (1)\n[context] X0001 · Gotchas · TestProj · status: -\n"
        in out
    )
    assert "## personal notes" not in out
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
    assert " · matched 2/2" in out and "IDEABODY" not in out
    tail = out.split("[personal] Lecture notes.md:4 · matched 2/2\n")[1]
    assert tail.rstrip("\n").split("\n") == [
        "  > Intro line.",
        "  > Temporal aggregation of EEG windows was discussed here.",
        "  > Next line.",
    ]
    assert "Unrelated tail" not in out and "Other.md" not in out


def test_recall_partial_match_ranks_below_full_match(vault, cli):
    _setup(vault, cli)
    (vault.personal / "Partial.md").write_text("Only aggregation is mentioned.\n")
    (vault.personal / "Split.md").write_text("temporal stuff\nmore\naggregation here\n")
    code, out, _ = cli("recall", "temporal aggregation")
    assert code == 0 and out.startswith('4 hit(s) for "temporal aggregation"')
    assert "[personal] Partial.md:1 · matched 1/2" in out
    assert "[personal] Split.md:1 · matched 2/2" in out
    full, split, partial = _order(out, "testproj-0004", "Split.md", "Partial.md")
    assert full < split < partial
    assert "  > temporal stuff\n  > more\n" in out
    assert "  > aggregation here" not in out  # only one line either side


def test_recall_context_record_outranks_personal_note_with_more_terms(vault, cli):
    _setup(vault, cli)
    (vault.context / "idea-testproj-0007-temporal-masking.md").write_text(
        '---\ncategories: "[[Ideas]]"\ntype: "[[TestProj]]"\n'
        'status: "[[In Progress]]"\ndocket_id: testproj-0007\n'
        "title: Temporal masking\n---\n\n# Temporal masking\n"
    )
    code, out, _ = cli("recall", "temporal aggregation")
    assert code == 0
    header, one_of_two, two_of_two, lecture = _order(
        out,
        "## context records (2)",
        "[context] testproj-0007 · Ideas · TestProj · status: In Progress · matched 1/2",  # noqa: E501
        "[context] testproj-0004 · Ideas · TestProj · status: Falsified · matched 2/2",
        "## personal notes (1)\n[personal] Lecture notes.md:4 · matched 2/2",
    )
    assert header < two_of_two < one_of_two < lecture


def test_recall_stems_plurals_and_suffixes(vault, cli):
    _setup(vault, cli)
    (vault.personal / "Verb.md").write_text("We aggregate windows here.\n")
    code, out, _ = cli("recall", "aggregation")
    assert code == 0 and "[personal] Verb.md:1" in out
    code, out, _ = cli("recall", "oscillator")
    assert code == 0 and "[context] X0001" in out  # scope says oscillators


def test_recall_ignores_stop_words(vault, cli):
    _setup(vault, cli)
    code, out, _ = cli("recall", "the aggregation of")
    assert code == 0 and "matched 1/1" not in out and "testproj-0004" in out
    code, _, err = cli("recall", "the of a")
    assert code == 2 and "at least one searchable word" in err


def test_recall_personal_notes_capped_at_five_with_count_line(vault, cli):
    _setup(vault, cli)
    for i in range(6):
        (vault.personal / f"note{i:02d}.md").write_text(f"common word here {i}\n")
    code, out, _ = cli("recall", "common")
    lines = out.rstrip("\n").split("\n")
    assert code == 0 and lines[0].startswith('6 hit(s) for "common"')
    assert lines[1] == "## personal notes (6)"
    assert lines[2:4] == ["[personal] note00.md:1", "  > common word here 0"]  # full
    assert "note05.md" not in out
    assert lines[-1] == "6 personal notes, showing 5 — refine the query or use --all"
    code, out, _ = cli("recall", "common", "--all")
    lines = out.rstrip("\n").split("\n")
    assert code == 0 and "showing" not in out
    assert lines[2:] == [
        f"[personal] note{i:02d}.md:1 · common word here {i}" for i in range(6)
    ]  # six shown: compact


def test_recall_line_cap_cuts_a_long_context_tier_with_count_line(vault, cli):
    _setup(vault, cli)
    for i in range(70):
        (vault.context / f"idea-testproj-{i + 100:04d}-common.md").write_text(
            '---\ncategories: "[[Ideas]]"\ntype: "[[TestProj]]"\n'
            f"docket_id: testproj-{i + 100:04d}\ntitle: Common thing {i}\n---\n"
        )
    (vault.personal / "Mention.md").write_text("common here too\n")
    code, out, _ = cli("recall", "common")
    lines = out.rstrip("\n").split("\n")
    assert code == 0 and lines[1] == "## context records (70)"
    assert lines[2].startswith("[context] testproj-0100 · status: - · Common thing 0")
    cut = lines.index("70 context records, showing 57 — refine the query or use --all")
    assert cut == 59  # header + section line + 57 compact hits fill the 60-line cap
    assert lines[cut + 1 :] == [
        "## personal notes (1)",
        "1 personal notes, showing 0 — refine the query or use --all",
    ]
    code, out, _ = cli("recall", "common", "--all")
    lines = out.rstrip("\n").split("\n")
    assert code == 0 and "showing" not in out and len(lines) == 1 + 1 + 70 + 1 + 2


def test_recall_no_hits(vault, cli):
    _setup(vault, cli)
    code, out, _ = cli("recall", "zzz qqq")
    assert code == 0 and out.strip() == 'no hits for "zzz qqq"'


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
