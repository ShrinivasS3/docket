from docket import frontmatter as fm
from tests.conftest import snapshot

ARGS = (
    "gotcha",
    "--symptom",
    "Resonance trend appears where none exists",
    "--cause",
    "Forward Euler integration is unstable under rotation",
    "--fix",
    "Use RK4",
    "--scope",
    "oscillators, numerical-integration",
    "--project",
    "TestProj",
)


def test_gotcha_writes_expected_note(vault, cli):
    code, out, _ = cli(*ARGS)
    assert code == 0 and out.startswith("created")
    path = vault.context / "gotcha-X0001-resonance-trend-appears-where-none-exists.md"
    assert path.is_file()
    text = path.read_text()
    fields, body = fm.load(text)
    assert fields["categories"] == "[[Gotchas]]"
    assert fields["type"] == "[[TestProj]]"
    assert fields["docket_id"] == "X0001"
    assert fields["symptom"] == "Resonance trend appears where none exists"
    assert fields["cause"] == "Forward Euler integration is unstable under rotation"
    assert fields["fix"] == "Use RK4"
    assert fields["scope"] == ["oscillators", "numerical-integration"]
    assert str(fields["created"]) == "2026-09-03"
    assert text.startswith('---\ncategories: "[[Gotchas]]"\ntype: "[[TestProj]]"\n')
    assert "# Resonance trend appears where none exists" in body


def test_gotcha_is_idempotent(vault, cli):
    cli(*ARGS)
    before = snapshot(*vault.roots)
    code, out, _ = cli(*ARGS)
    assert code == 0 and out.startswith("unchanged")
    assert snapshot(*vault.roots) == before


def test_gotcha_numbers_increment(vault, cli):
    cli(*ARGS)
    cli(
        "gotcha",
        "--symptom",
        "Second: with colon",
        "--cause",
        "c",
        "--fix",
        "f",
        "--scope",
        "s",
        "--project",
        "TestProj",
    )
    names = sorted(p.name for p in vault.context.glob("gotcha-*.md"))
    assert names == [
        "gotcha-X0001-resonance-trend-appears-where-none-exists.md",
        "gotcha-X0002-second-with-colon.md",
    ]
    fields, _ = fm.load((vault.context / names[1]).read_text())
    assert fields["symptom"] == "Second: with colon"
    code, out, _ = cli("check")
    assert code == 0, out


def test_gotcha_dry_run_writes_nothing(vault, cli):
    before = snapshot(*vault.roots)
    code, out, _ = cli(*ARGS, "--dry-run")
    assert code == 0 and out.startswith("[dry-run] created")
    assert snapshot(*vault.roots) == before


def test_gotcha_warns_on_missing_anchor(vault, cli):
    code, _, err = cli(
        "gotcha",
        "--symptom",
        "s",
        "--cause",
        "c",
        "--fix",
        "f",
        "--scope",
        "x",
        "--project",
        "Nowhere",
    )
    assert code == 0 and "Nowhere.md does not exist" in err
    code, out, _ = cli("check")
    assert code == 1 and "missing anchor [[Nowhere]]" in out


def test_gotcha_note_appends_body_section_only(vault, cli):
    note = "First  para   with spaces.\n\n\n  Second para.  "
    code, out, _ = cli(*ARGS, "--note", note)
    assert code == 0 and out.startswith("created")
    path = vault.context / "gotcha-X0001-resonance-trend-appears-where-none-exists.md"
    fields, body = fm.load(path.read_text())
    assert "note" not in fields
    assert body.endswith(
        "**Fix.** Use RK4\n\n**Note.** First para with spaces.\n\nSecond para.\n"
    )
    code, out, _ = cli("check")
    assert code == 0, out


def test_gotcha_without_note_has_no_note_section(vault, cli):
    cli(*ARGS)
    path = vault.context / "gotcha-X0001-resonance-trend-appears-where-none-exists.md"
    text = path.read_text()
    assert "**Note.**" not in text and text.endswith("**Fix.** Use RK4\n")
