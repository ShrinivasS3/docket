import pytest

from docket.config import DocketError, load_config


def test_dash_defaults(vault):
    cfg = load_config(vault.config)
    assert (cfg.dash.unpushed_days, cfg.dash.stale_days, cfg.dash.max_blocking) == (
        3,
        7,
        5,
    )


def test_dash_overrides(vault):
    vault.config.write_text(
        vault.config.read_text()
        + "\n[dash]\nunpushed_days = 1\nstale_days = 14\nmax_blocking = 2\n"
    )
    cfg = load_config(vault.config)
    assert (cfg.dash.unpushed_days, cfg.dash.stale_days, cfg.dash.max_blocking) == (
        1,
        14,
        2,
    )


def test_dash_rejects_bad_values(vault):
    vault.config.write_text(
        vault.config.read_text() + '\n[dash]\nstale_days = "soon"\n'
    )
    with pytest.raises(DocketError, match="stale_days"):
        load_config(vault.config)
    vault.config.write_text(vault.config.read_text().replace('"soon"', "-1"))
    with pytest.raises(DocketError, match="stale_days"):
        load_config(vault.config)


def test_branch_kind_first_match_wins(vault):
    cfg = load_config(vault.config)
    assert cfg.branch_kind("experiments/x") == "idea"
    assert cfg.branch_kind("fix/x") == "gotcha"
    assert cfg.branch_kind("bare-name") == "idea"
