"""docket config check: drift between the live config and the committed template."""

import tomllib

from docket.commands.config import find_drift, run_config_check
from docket.config import load_config
from docket.templates import config_template

TEMPLATE = """
[roots]
projects = "<PROJECTS_ROOT>"
context  = "<CONTEXT_ROOT>"
personal = "<PERSONAL_ROOT>"

[dashboard]
target = "<DASHBOARD_TARGET>"

[branches]
"experiments/*" = "idea"
"diagnostics/*" = "idea"
"phase-*" = "idea"
"fix/*" = "gotcha"
"*" = "idea"

[recall.aliases]
sr = "successor representation"

[dash]
stale_days = 7

[identity]
device = "<ROLE>"
attended = true
"""

BRANCHES = [
    ('"experiments/*"', "idea"),
    ('"diagnostics/*"', "idea"),
    ('"phase-*"', "idea"),
    ('"fix/*"', "gotcha"),
    ('"*"', "idea"),
]
ALIASES = [("sr", "successor representation")]


def write_live(vault, *, branches=None, aliases=None, dash=7, tail=""):
    """A complete live config. Machine-specific values are the fixture's real
    paths and role, which is the point: they must never read as drift."""
    rows = "\n".join(
        f'{p} = "{k}"' for p, k in (BRANCHES if branches is None else branches)
    )
    als = "\n".join(
        f'{k} = "{v}"' for k, v in (ALIASES if aliases is None else aliases)
    )
    vault.config.write_text(
        f'[roots]\nprojects = "{vault.projects}"\ncontext = "{vault.context}"\n'
        f'personal = "{vault.personal}"\n\n'
        f'[dashboard]\ntarget = "{vault.dashboard}"\n\n'
        f"[branches]\n{rows}\n\n"
        f"[recall.aliases]\n{als}\n\n"
        f"[dash]\nstale_days = {dash}\n\n"
        f'[identity]\ndevice = "mac"\nattended = true\n{tail}'
    )


def drift(vault, **kw):
    write_live(vault, **kw)
    return find_drift(load_config(vault.config), TEMPLATE)


def lines(vault, **kw) -> str:
    return "\n".join(d.line for d in drift(vault, **kw))


# --- clean ---------------------------------------------------------------


def test_no_drift_when_they_agree(vault):
    assert drift(vault) == []


def test_clean_run_exits_zero(vault):
    write_live(vault)
    text, code = run_config_check(load_config(vault.config), TEMPLATE)
    assert code == 0 and "no drift" in text


def test_machine_specific_values_are_never_drift(vault):
    """The whole point: roots, dashboard target and device differ on every
    machine, and must not bury a real finding."""
    assert drift(vault) == []
    cfg = load_config(vault.config)
    assert str(cfg.projects) != "<PROJECTS_ROOT>"  # they really do differ
    assert cfg.identity.device == "mac"


# --- the motivating case -------------------------------------------------


def test_branch_pattern_added_locally_is_reported(vault):
    out = lines(
        vault, branches=[*BRANCHES[:-1], ('"redesign/*"', "idea"), BRANCHES[-1]]
    )
    assert 'branches  "redesign/*" = "idea"' in out
    assert "never committed" in out and "rebuild would lose it" in out


def test_recall_alias_added_locally_is_reported(vault):
    out = lines(vault, aliases=[*ALIASES, ("jepa", "joint-embedding")])
    assert 'recall.aliases.jepa = "joint-embedding"' in out
    assert "never committed" in out


def test_drift_exits_one(vault):
    write_live(vault, aliases=[*ALIASES, ("jepa", "joint-embedding")])
    text, code = run_config_check(load_config(vault.config), TEMPLATE)
    assert code == 1 and "1 difference between" in text


def test_several_drifts_are_all_reported(vault):
    out = lines(
        vault,
        branches=[*BRANCHES[:-1], ('"redesign/*"', "idea"), BRANCHES[-1]],
        aliases=[*ALIASES, ("hrf", "h")],
    )
    assert 'branches  "redesign/*"' in out and "recall.aliases.hrf" in out
    assert (
        "2 differences between"
        in run_config_check(load_config(vault.config), TEMPLATE)[0]
    )


# --- the other directions ------------------------------------------------


def test_template_only_pattern_is_reported(vault):
    out = lines(vault, branches=[b for b in BRANCHES if b[0] != '"diagnostics/*"'])
    assert 'branches  "diagnostics/*" = "idea"' in out
    assert "missing from the live config" in out


def test_changed_branch_kind_is_reported(vault):
    out = lines(vault, branches=[(p, "idea") for p, _ in BRANCHES])
    assert 'branches  "fix/*"  — live "idea", template "gotcha"' in out


def test_changed_dash_threshold_is_reported(vault):
    assert "dash.stale_days  — live 30, template 7" in lines(vault, dash=30)


def test_a_whole_new_section_is_reported(vault):
    out = lines(vault, tail="\n[papers]\nchecked_days = 30\n")
    assert "papers.checked_days = 30" in out and "never committed" in out


# --- ordering ------------------------------------------------------------


def test_reordered_branches_are_drift(vault):
    """[branches] is first-match-wins, so the same set in another order is a
    different config and must not read as clean."""
    swapped = [BRANCHES[1], BRANCHES[0], *BRANCHES[2:]]
    out = lines(vault, branches=swapped)
    assert "order differs from the template" in out
    assert "first-match-wins" in out


def test_same_order_is_not_reported_as_drift(vault):
    assert not any(d.kind == "order" for d in drift(vault))


def test_a_pure_reorder_reports_only_the_order(vault):
    swapped = [BRANCHES[1], BRANCHES[0], *BRANCHES[2:]]
    found = drift(vault, branches=swapped)
    assert [d.kind for d in found] == ["order"]


# --- the shipped template ------------------------------------------------


def test_shipped_template_placeholders_every_machine_specific_value():
    """A real path or role committed here would be a silent footgun on the next
    machine, and the drift check would never flag it."""
    data = tomllib.loads(config_template())
    for key in ("projects", "context", "personal"):
        assert data["roots"][key].startswith("<"), key
    assert data["dashboard"]["target"].startswith("<")
    assert data["identity"]["device"].startswith("<")
    assert "/" not in data["identity"]["device"]


def test_shipped_template_keeps_the_fallback_last():
    """The "*" fallback must stay at the end or it claims every branch."""
    assert list(tomllib.loads(config_template())["branches"])[-1] == "*"
