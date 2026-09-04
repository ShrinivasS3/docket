"""Configuration: roots, dashboard target, branch patterns, and the write guard."""

from __future__ import annotations

import fnmatch
import os
import platform
import re
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
class RecallConfig:
    """[recall.aliases]: short form -> phrase, expanded both ways by recall."""

    aliases: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class IdentityConfig:
    """[identity]: which machine wrote a record, and whether a human was there.

    No `[identity]` table means no `device` and no `attended` in the record. A
    machine that has not been told who it is does not get to claim a device, and
    a stamped-on default would be indistinguishable from a real answer.
    """

    device: str = ""
    attended: bool = True

    @property
    def present(self) -> bool:
        return bool(self.device)


@dataclass(frozen=True)
class Config:
    path: Path
    roots: dict[str, Path]
    dashboard: Path
    branches: tuple[tuple[str, str], ...]
    dash: DashConfig = DashConfig()
    recall: RecallConfig = RecallConfig()
    identity: IdentityConfig = IdentityConfig()

    @property
    def projects(self) -> Path:
        return self.roots["projects"]

    @property
    def context(self) -> Path:
        return self.roots["context"]

    @property
    def personal(self) -> Path:
        return self.roots["personal"]

    def branch_match(self, branch: str) -> tuple[str, str] | None:
        """(pattern, kind) of the first matching [branches] entry, else None.
        First match wins; the user orders patterns most-specific first.
        """
        for pattern, kind in self.branches:
            if fnmatch.fnmatchcase(branch, pattern):
                return pattern, kind
        return None

    def branch_kind(self, branch: str) -> str | None:
        match = self.branch_match(branch)
        return None if match is None else match[1]

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
        recall=_recall_config(data.get("recall") or {}),
        identity=_identity_config(data.get("identity")),
    )


def _identity_config(raw: dict | None) -> IdentityConfig:
    """Absent table -> an empty identity, which writes no fields at all."""
    if not raw:
        return IdentityConfig()
    device = raw.get("device", platform.node().split(".")[0])
    if not isinstance(device, str) or not device.strip():
        raise DocketError("config [identity] device must be a non-empty string")
    attended = raw.get("attended", True)
    if not isinstance(attended, bool):
        raise DocketError("config [identity] attended must be true or false")
    return IdentityConfig(device=device.strip(), attended=attended)


def _recall_config(raw: dict) -> RecallConfig:
    aliases_raw = raw.get("aliases") or {}
    if not isinstance(aliases_raw, dict):
        raise DocketError("config [recall.aliases] must be a table of short = phrase")
    aliases = []
    for short, phrase in aliases_raw.items():
        if not isinstance(phrase, str) or not phrase.strip() or not str(short).strip():
            raise DocketError(
                f"config [recall.aliases] {short!r} must map to a non-empty string"
            )
        aliases.append((str(short).strip(), phrase.strip()))
    return RecallConfig(aliases=tuple(aliases))


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


BRANCH_FALLBACK = "*"
_TABLE = re.compile(r"^\s*\[")
_ENTRY = re.compile(r'^\s*(?:"([^"]*)"|([A-Za-z0-9_.*/\[\]-]+))\s*=')


def _entry_key(line: str) -> str | None:
    """The key a [branches] entry line defines, quoted or bare, else None."""
    match = _ENTRY.match(line)
    if match is None:
        return None
    return match.group(1) if match.group(1) is not None else match.group(2)


def _strip_trailing_blank(lines: list[str]) -> list[str]:
    end = len(lines)
    while end and not lines[end - 1].strip():
        end -= 1
    return lines[:end]


def insert_branch_pattern(text: str, pattern: str, kind: str = "idea") -> str | None:
    """Config text with `pattern` added to [branches], or None if it is already
    there. The entry goes immediately before the "*" fallback — and before the
    comment block attached to it — so a specific pattern still wins the
    first-match-wins lookup. Every other byte of the file is preserved, which
    matters because the table is commented and tomllib cannot round-trip it.
    """
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.replace("\r\n", "\n").split("\n")
    entry = f'"{pattern}"'

    start = next(
        (i for i, line in enumerate(lines) if line.strip() == "[branches]"), None
    )
    if start is None:
        block = ["", "[branches]", f'{entry} = "{kind}"']
        return newline.join([*_strip_trailing_blank(lines), *block, ""])

    end = len(lines)
    for idx in range(start + 1, len(lines)):
        if _TABLE.match(lines[idx]):
            end = idx
            break

    width = len(entry)
    fallback = None
    for idx in range(start + 1, end):
        key = _entry_key(lines[idx])
        if key is None:
            continue
        if key == pattern:
            return None
        width = max(width, len(f'"{key}"'))
        if key == BRANCH_FALLBACK and fallback is None:
            fallback = idx

    at = end
    if fallback is not None:
        at = fallback
        while at > start + 1 and lines[at - 1].lstrip().startswith("#"):
            at -= 1
    while at > start + 1 and not lines[at - 1].strip():
        at -= 1

    lines.insert(at, f'{entry:<{width}} = "{kind}"')
    return newline.join(lines)
