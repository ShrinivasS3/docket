"""Files `docket init` writes into a repo, kept as data instead of inline text.

One source of truth. The AGENTS.md stanza in particular is quoted in fifteen
repos; editing it here is what makes a future edit propagate, so nothing that
writes a wired file may hold its own copy of the text.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

TEMPLATE_DIR = Path(__file__).parent


@cache
def load(name: str) -> str:
    """Contents of one template file, newlines untranslated."""
    with open(TEMPLATE_DIR / name, encoding="utf-8", newline="") as fh:
        return fh.read()


def agents_stanza() -> str:
    """The `## Research log` section appended to a repo's AGENTS.md."""
    return load("agents-stanza.md")


def gitignore() -> str:
    """A starting .gitignore. Only written when the repo has none at all."""
    return load("gitignore")


def pre_commit_hook() -> str:
    """The 50 MB staged-file guard installed at .githooks/pre-commit."""
    return load("pre-commit")
