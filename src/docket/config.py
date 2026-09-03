"""Configuration: roots, dashboard target, branch patterns, and the write guard."""

from __future__ import annotations

import fnmatch
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG = Path("~/.docket/config.toml")
ROOT_KEYS = ("projects", "context", "personal")


class DocketError(Exception):
    """A user-facing failure. The CLI prints the message and exits 2."""


@dataclass(frozen=True)
class DashConfig:
    """Tunable thresholds for the Blocking callout. Days are strict `>` limits."""

    unpushed_days: int = 3
    stale_days: int = 7
    max_blocking: int = 5
    max_idle: int = 5


@dataclass(frozen=True)
class Config:
    path: Path
    roots: dict[str, Path]
    dashboard: Path
    branches: tuple[tuple[str, str], ...]
    dash: DashConfig = DashConfig()

    @property
    def projects(self) -> Path:
        return self.roots["projects"]

    @property
    def context(self) -> Path:
        return self.roots["context"]

    @property
    def personal(self) -> Path:
        return self.roots["personal"]

    def branch_kind(self, branch: str) -> str | None:
        """First matching pattern wins; the user orders patterns most-specific first."""
        for pattern, kind in self.branches:
            if fnmatch.fnmatchcase(branch, pattern):
                return kind
        return None

    def assert_inside_roots(self, target: Path) -> None:
        """Refuse any write that would land outside the three configured roots."""
        resolved = _resolve(target)
        for root in self.roots.values():
            if resolved.is_relative_to(_resolve(root)):
                return
        raise DocketError(f"refusing to write outside configured roots: {target}")


def _resolve(path: Path) -> Path:
    # resolve() follows symlinks (OneDrive folders are often symlinked) but the
    # final component may not exist yet, which strict=False tolerates.
    return path.expanduser().resolve(strict=False)


def config_path(explicit: str | Path | None = None) -> Path:
    raw = explicit or os.environ.get("DOCKET_CONFIG") or DEFAULT_CONFIG
    return Path(raw).expanduser()


def load_config(explicit: str | Path | None = None) -> Config:
    path = config_path(explicit)
    if not path.is_file():
        raise DocketError(f"config not found: {path}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise DocketError(f"config is not valid TOML ({path}): {exc}") from exc

    roots_raw = data.get("roots") or {}
    missing = [key for key in ROOT_KEYS if key not in roots_raw]
    if missing:
        raise DocketError(f"config [roots] missing: {', '.join(missing)}")
    roots = {key: Path(str(value)).expanduser() for key, value in roots_raw.items()}

    target = (data.get("dashboard") or {}).get("target")
    dashboard = (
        Path(str(target)).expanduser() if target else roots["personal"] / "Dashboard.md"
    )

    branches_raw = data.get("branches") or {}
    branches = tuple((str(k), str(v)) for k, v in branches_raw.items())

    return Config(
        path=path,
        roots=roots,
        dashboard=dashboard,
        branches=branches,
        dash=_dash_config(data.get("dash") or {}),
    )


def _dash_config(raw: dict) -> DashConfig:
    values = {}
    for key, default in (
        ("unpushed_days", DashConfig.unpushed_days),
        ("stale_days", DashConfig.stale_days),
        ("max_blocking", DashConfig.max_blocking),
        ("max_idle", DashConfig.max_idle),
    ):
        value = raw.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise DocketError(f"config [dash] {key} must be a non-negative integer")
        values[key] = value
    return DashConfig(**values)
