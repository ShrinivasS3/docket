"""[identity] roles, --unattended, the commit trailers, and the recall/list filters."""

import pytest

from docket import frontmatter as fm
from docket.config import DocketError, load_config
from tests.conftest import days_ago


def identity(vault, *, device='"mac"', attended="true"):
    lines = "\n[identity]\n"
    if device is not None:
        lines += f"device = {device}\n"
    if attended is not None:
        lines += f"attended = {attended}\n"
    vault.config.write_text(vault.config.read_text() + lines)


def fields_of(path):
    return fm.load(path.read_text())[0]


def only_idea(vault):
    return next(iter(sorted(vault.context.glob("idea-*.md"))))


# --- the role ------------------------------------------------------------


def test_device_is_a_role_not_a_hostname(vault, here, cli):
    identity(vault)
    cli("idea", "new", "--branch", "experiments/fresh-one", "--gate", "g")
    assert fields_of(only_idea(vault))["device"] == "mac"


def test_identity_without_device_is_an_error(vault):
    identity(vault, device=None)
    with pytest.raises(DocketError, match="role, never a hostname"):
        load_config(vault.config)


def test_identity_with_a_blank_device_is_an_error(vault):
    identity(vault, device='"  "')
    with pytest.raises(DocketError, match="non-empty role string"):
        load_config(vault.config)


def test_no_identity_table_is_not_an_error_and_writes_nothing(vault, here, cli):
    code, out, _ = cli(
        "idea", "new", "--branch", "experiments/fresh-one", "--gate", "g"
    )
    assert code == 0, out
    got = fields_of(only_idea(vault))
    assert "device" not in got and "attended" not in got


def test_attended_must_be_a_bool(vault):
    identity(vault, attended='"yes"')
    with pytest.raises(DocketError, match="attended must be true or false"):
        load_config(vault.config)


# --- --unattended on the writers -----------------------------------------


def test_idea_new_unattended(vault, here, cli):
    identity(vault)
    cli(
        "idea",
        "new",
        "--branch",
        "experiments/fresh-one",
        "--gate",
        "g",
        "--unattended",
    )
    got = fields_of(only_idea(vault))
    assert got["device"] == "mac" and got["attended"] is False


def test_idea_import_unattended(vault, repo, cli):
    identity(vault)
    cli("idea", "import", "--repo", "TestProj", "--unattended")
    for path in vault.context.glob("idea-testproj-*.md"):
        got = fields_of(path)
        assert got["device"] == "mac" and got["attended"] is False


def test_idea_import_stamps_attended_by_default(vault, repo, cli):
    identity(vault)
    cli("idea", "import", "--repo", "TestProj")
    got = fields_of(vault.context / "idea-testproj-0003-fresh-one.md")
    assert got["device"] == "mac" and got["attended"] is True


def test_gotcha_unattended(vault, cli):
    identity(vault)
    cli(
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
        "TestProj",
        "--unattended",
    )
    got = fields_of(next(iter(vault.context.glob("gotcha-*.md"))))
    assert got["device"] == "mac" and got["attended"] is False


def test_unattended_overrides_an_attended_config(vault, here, cli):
    identity(vault, attended="true")
    cli(
        "idea",
        "new",
        "--branch",
        "experiments/fresh-one",
        "--gate",
        "g",
        "--unattended",
    )
    assert fields_of(only_idea(vault))["attended"] is False


def test_config_attended_false_is_the_default_for_that_machine(vault, here, cli):
    identity(vault, device='"hermes"', attended="false")
    cli("idea", "new", "--branch", "experiments/fresh-one", "--gate", "g")
    got = fields_of(only_idea(vault))
    assert got["device"] == "hermes" and got["attended"] is False


# --- commit trailers ------------------------------------------------------


def test_identity_prints_trailers(vault, cli):
    identity(vault)
    code, out, _ = cli("identity")
    assert code == 0
    assert out.strip().split("\n") == ["Device: mac", "Attended: true"]


def test_identity_unattended_trailers(vault, cli):
    identity(vault, device='"cnslab"')
    code, out, _ = cli("identity", "--unattended")
    assert code == 0
    assert out.strip().split("\n") == ["Device: cnslab", "Attended: false"]


def test_trailers_are_greppable_by_the_documented_pattern(vault, cli):
    identity(vault)
    _, out, _ = cli("identity", "--unattended")
    assert "Attended: false" in out  # git log --grep="Attended: false"


def test_identity_without_a_table_refuses(vault, cli):
    code, _, err = cli("identity")
    assert code == 2 and "no [identity] table" in err


# --- recall and list filters ---------------------------------------------


@pytest.fixture
def mixed(vault, repo, cli, here):
    """Two records on the same terms: one attended, one not."""
    identity(vault)
    here("checkout", "-q", "-b", "experiments/scheduled-sweep", "main")
    here.commit("sweep", days_ago(1))
    cli("idea", "new", "--gate", "g", "--unattended")
    here("checkout", "-q", "-b", "experiments/scheduled-by-hand", "main")
    here.commit("hand", days_ago(1))
    cli("idea", "new", "--gate", "g")
    return vault


def test_recall_marks_unattended_hits_visibly(mixed, cli):
    code, out, _ = cli("recall", "scheduled")
    assert code == 0, out
    marked = [ln for ln in out.split("\n") if "UNATTENDED" in ln]
    assert marked, out
    assert any("scheduled-sweep" in ln or "0001" in ln for ln in out.split("\n"))
    assert "no human read the work behind them" in out.lower()


def test_recall_does_not_mark_attended_hits(mixed, cli):
    _, out, _ = cli("recall", "by hand")
    lines = [ln for ln in out.split("\n") if "by-hand" in ln or "scheduled-by" in ln]
    assert lines and not any("UNATTENDED" in ln for ln in lines)


def test_recall_unattended_filter(mixed, cli):
    code, out, _ = cli("recall", "--unattended", "scheduled")
    assert code == 0, out
    assert "scheduled-sweep" in out
    assert "scheduled-by-hand" not in out
    assert "personal notes not searched" in out


def test_recall_attended_filter(mixed, cli):
    code, out, _ = cli("recall", "--attended", "scheduled")
    assert code == 0, out
    assert "scheduled-by-hand" in out
    assert "scheduled-sweep" not in out


def test_recall_filters_are_mutually_exclusive(mixed, cli):
    with pytest.raises(SystemExit):
        cli("recall", "--attended", "--unattended", "scheduled")


def test_list_attendance_filters(mixed, cli):
    _, unatt, _ = cli("list", "--unattended")
    _, att, _ = cli("list", "--attended")
    assert (
        "scheduled-sweep" in unatt.lower().replace(" ", "-")
        or "Scheduled sweep" in unatt
    )
    assert "Scheduled sweep" in unatt and "Scheduled by hand" not in unatt
    assert "Scheduled by hand" in att and "Scheduled sweep" not in att


def test_a_record_with_no_attended_field_matches_neither_filter(vault, repo, cli):
    cli("idea", "import", "--repo", "TestProj")  # no [identity] -> no field
    _, att, _ = cli("list", "--attended")
    _, unatt, _ = cli("list", "--unattended")
    assert att.strip() == "(no records)" and unatt.strip() == "(no records)"
    _, all_rows, _ = cli("list")
    assert "testproj-0003" in all_rows
