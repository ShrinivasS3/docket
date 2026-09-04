"""Guarded, idempotent file I/O. Every write in docket goes through here."""

from __future__ import annotations

import os
from pathlib import Path

from docket.config import Config


def read_text(path: Path) -> str:
    """Read preserving line endings exactly (newline='' disables translation)."""
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def write_text(cfg: Config, path: Path, content: str, *, dry_run: bool = False) -> bool:
    """Write `content` to `path` only if it differs. Returns True if a write happened
    (or would have, under dry_run). Atomic: tmp file in the same directory, then
    os.replace. Refuses paths outside the configured roots.
    """
    cfg.assert_inside_roots(path)
    if path.exists() and read_text(path) == content:
        return False
    if dry_run:
        return True
    _atomic_write(path, content)
    return True


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(content)
    os.replace(tmp, path)


def write_config(cfg: Config, content: str) -> bool:
    """Rewrite config.toml itself. The roots guard cannot apply here — the config
    lives outside all three roots by design — so the target is pinned to the file
    the config was loaded from and nothing else is writable through this path.
    """
    if cfg.path.exists() and read_text(cfg.path) == content:
        return False
    _atomic_write(cfg.path, content)
    return True
