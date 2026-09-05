"""docket config check: drift between the live config and the committed template.

The live `~/.docket/config.toml` is the only file in the system that is neither
in a repo nor in a vault, so nothing carries it to a new machine and nothing
notices when it is lost. Most of it is portable — the `[branches]` table, the
recall aliases, the dash thresholds — and a pattern added locally and never
committed is exactly what a rebuild would silently drop.

Comparison is textual-free: both files are parsed with tomllib and compared as
data, because the template is hand-maintained and its comments are the point.
`[branches]` is compared as an ORDERED list: the table is first-match-wins, so
two configs with the same patterns in a different order behave differently.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from docket import templates
from docket.config import Config, DocketError

TEMPLATE = "config.template.toml"
BRANCHES = "branches"

# Values that legitimately differ per machine. Never compared, so a real drift
# report is never buried under noise the user cannot act on.
MACHINE_SPECIFIC = frozenset(
    {
        "roots.projects",
        "roots.context",
        "roots.personal",
        "dashboard.target",
        "identity.device",
        "identity.attended",
    }
)


@dataclass(frozen=True, order=True)
class Drift:
    """One disagreement. `kind` sorts the report; `line` is what is printed."""

    kind: str
    where: str
    line: str


def _is_placeholder(value: object) -> bool:
    text = str(value).strip()
    return text.startswith("<") and text.endswith(">")


def _flatten(data: dict, prefix: str = "") -> dict[str, object]:
    """Dotted-key view of every scalar, minus [branches].

    Branch patterns may themselves contain dots, so flattening them would make
    the key ambiguous; they are compared separately and in order.
    """
    out: dict[str, object] = {}
    for key, value in data.items():
        path = f"{prefix}{key}"
        if path == BRANCHES:
            continue
        if isinstance(value, dict):
            out.update(_flatten(value, f"{path}."))
        else:
            out[path] = value
    return out


def _render(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return f'"{value}"' if isinstance(value, str) else str(value)


def _branch_drift(live: dict, template: dict) -> list[Drift]:
    live_b = live.get(BRANCHES) or {}
    tmpl_b = template.get(BRANCHES) or {}
    found: list[Drift] = []

    for pattern, kind in live_b.items():
        if pattern not in tmpl_b:
            found.append(
                Drift(
                    "live-only",
                    BRANCHES,
                    f'branches  "{pattern}" = "{kind}"  — live only, never '
                    "committed; a rebuild would lose it",
                )
            )
        elif tmpl_b[pattern] != kind:
            found.append(
                Drift(
                    "differs",
                    BRANCHES,
                    f'branches  "{pattern}"  — live "{kind}", '
                    f'template "{tmpl_b[pattern]}"',
                )
            )
    for pattern, kind in tmpl_b.items():
        if pattern not in live_b:
            found.append(
                Drift(
                    "template-only",
                    BRANCHES,
                    f'branches  "{pattern}" = "{kind}"  — in the template, '
                    "missing from the live config",
                )
            )

    # Order matters: branch_match takes the first pattern that matches, so the
    # same set in a different order is a different config.
    shared = [p for p in live_b if p in tmpl_b]
    if shared != [p for p in tmpl_b if p in live_b]:
        found.append(
            Drift(
                "order",
                BRANCHES,
                "branches  order differs from the template — [branches] is "
                "first-match-wins, so this changes which pattern claims a branch",
            )
        )
    return found


def _scalar_drift(live: dict, template: dict) -> list[Drift]:
    live_f, tmpl_f = _flatten(live), _flatten(template)
    found: list[Drift] = []
    for key, value in live_f.items():
        if key in MACHINE_SPECIFIC:
            continue
        if key not in tmpl_f:
            found.append(
                Drift(
                    "live-only",
                    key,
                    f"{key} = {_render(value)}  — live only, never committed; "
                    "a rebuild would lose it",
                )
            )
        elif not _is_placeholder(tmpl_f[key]) and tmpl_f[key] != value:
            found.append(
                Drift(
                    "differs",
                    key,
                    f"{key}  — live {_render(value)}, template {_render(tmpl_f[key])}",
                )
            )
    for key, value in tmpl_f.items():
        if key in MACHINE_SPECIFIC or key in live_f:
            continue
        found.append(
            Drift(
                "template-only",
                key,
                f"{key} = {_render(value)}  — in the template, missing from "
                "the live config",
            )
        )
    return found


def _parse(path: Path, text: str) -> dict:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise DocketError(f"{path} is not valid TOML: {exc}") from exc


def find_drift(cfg: Config, template_text: str | None = None) -> list[Drift]:
    """Drift against the shipped template, or against `template_text` when given
    (which is how the tests pin a template instead of tracking the real one)."""
    live = _parse(cfg.path, cfg.path.read_text(encoding="utf-8"))
    text = templates.config_template() if template_text is None else template_text
    template = _parse(Path(TEMPLATE), text)
    return sorted(_branch_drift(live, template) + _scalar_drift(live, template))


def run_config_check(cfg: Config, template_text: str | None = None) -> tuple[str, int]:
    drift = find_drift(cfg, template_text)
    tmpl_path = templates.TEMPLATE_DIR / TEMPLATE
    if not drift:
        return (
            f"docket config check: no drift — {cfg.path} matches {tmpl_path.name}\n"
            f"  (roots, dashboard target and identity are machine-specific and "
            f"not compared)",
            0,
        )
    lines = [f"DRIFT  {item.line}" for item in drift]
    noun = "difference" if len(drift) == 1 else "differences"
    lines.append(
        f"docket config check: {len(drift)} {noun} between {cfg.path} and "
        f"{tmpl_path.name}"
    )
    lines.append(f"  commit the template to keep them: {tmpl_path}")
    return "\n".join(lines), 1
