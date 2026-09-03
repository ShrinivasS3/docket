import pytest

from docket.commands.capture import run_capture
from docket.config import DocketError, load_config
from docket.markers import begin_marker, end_marker
from tests.conftest import DASHBOARD, snapshot


def _outside_block(text: str, name: str) -> str:
    keep, inside = [], False
    for line in text.split("\n"):
        if line.strip() == begin_marker(name):
            inside = True
        elif line.strip() == end_marker(name):
            inside = False
        elif not inside:
            keep.append(line)
    return "\n".join(keep)


def test_capture_creates_markers_after_first_rule(vault, cli):
    code, out, _ = cli("capture", "first thought")
    assert code == 0 and "captured" in out and "created scratch markers" in out
    text = vault.dashboard.read_text()
    lines = text.split("\n")
    rule = lines.index("___")
    assert lines[rule + 1] == ""
    assert lines[rule + 2] == begin_marker("scratch")
    assert lines[rule + 3] == "- 2026-09-03: first thought"
    assert lines[rule + 4] == end_marker("scratch")
    # Everything outside the block is the original file, modulo one blank line.
    assert _outside_block(text, "scratch").replace("\n\n\n", "\n\n") == DASHBOARD


def test_capture_is_idempotent(vault, cli):
    cli("capture", "same", "thing")
    before = snapshot(*vault.roots)
    code, out, _ = cli("capture", "same thing")
    assert code == 0 and out.startswith("unchanged")
    assert snapshot(*vault.roots) == before


def test_capture_appends_in_order_and_never_reorders(vault, cli):
    cli("capture", "one")
    cli("capture", "two")
    cli("capture", "three")
    text = vault.dashboard.read_text()
    block = text.split(begin_marker("scratch"))[1].split(end_marker("scratch"))[0]
    assert block.strip().split("\n") == [
        "- 2026-09-03: one",
        "- 2026-09-03: two",
        "- 2026-09-03: three",
    ]
    assert text.count(begin_marker("scratch")) == 1
    assert "- [ ] systemic check of hard bound" in text


def test_capture_dry_run_writes_nothing(vault, cli):
    before = snapshot(*vault.roots)
    code, out, _ = cli("capture", "--dry-run", "ghost")
    assert code == 0 and out.startswith("[dry-run]")
    assert snapshot(*vault.roots) == before


def test_capture_empty_text_rejected(vault, cli):
    code, _, err = cli("capture", "   ")
    assert code == 2 and "empty" in err


def test_capture_refuses_dashboard_outside_roots(vault, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "Dashboard.md").write_text(DASHBOARD)
    vault.config.write_text(
        vault.config.read_text().replace(
            str(vault.dashboard), str(outside / "Dashboard.md")
        )
    )
    cfg = load_config(vault.config)
    with pytest.raises(DocketError, match="outside configured roots"):
        run_capture(cfg, "nope")
    assert (outside / "Dashboard.md").read_text() == DASHBOARD
