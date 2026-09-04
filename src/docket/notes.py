"""Scanning the flat context vault: records, anchors, ids, dates, slugs."""

from __future__ import annotations

import datetime as dt
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from docket import frontmatter as fm
from docket.config import Config, DocketError

SKIP_DIRS = {".git", ".obsidian", ".githooks", ".trash", "node_modules"}
MANAGED_STATUSES = {"Completed", "In Progress", "Parked"}


@dataclass
class Record:
    path: Path
    fields: dict
    fm_text: str
    body: str
    text: str = ""

    def with_frontmatter(self, fm_text: str) -> str:
        """The full file text with `fm_text` swapped in, original newlines kept."""
        newline = "\r\n" if "\r\n" in self.text else "\n"
        rebuilt = "---\n" + fm_text + "\n---\n" + self.body
        return rebuilt.replace("\n", newline) if newline != "\n" else rebuilt

    @property
    def docket_id(self) -> str | None:
        return fm.get_field(self.fields, "docket_id")

    def anchor(self, key: str) -> str | None:
        names = fm.link_names(self.fields.get(key))
        return names[0] if names else None

    @property
    def category(self) -> str | None:
        return self.anchor("categories")

    @property
    def project(self) -> str | None:
        return self.anchor("type")

    @property
    def status(self) -> str | None:
        return self.anchor("status")

    @property
    def title(self) -> str:
        return (
            fm.get_field(self.fields, "title")
            or fm.get_field(self.fields, "symptom")
            or self.path.stem
        )


@dataclass
class Problem:
    path: Path
    message: str


def today() -> dt.date:
    """Today's date, overridable with DOCKET_TODAY=YYYY-MM-DD for reproducibility."""
    override = os.environ.get("DOCKET_TODAY")
    if override:
        return dt.date.fromisoformat(override)
    return dt.date.today()


def iter_markdown(vault: Path) -> list[Path]:
    found: list[Path] = []
    for root, dirs, files in os.walk(vault):
        dirs[:] = sorted(
            d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")
        )
        for name in sorted(files):
            if name.endswith(".md"):
                found.append(Path(root) / name)
    return found


def anchor_index(vault: Path) -> set[str]:
    """Stems of every markdown file in the vault, Obsidian-style link targets."""
    return {path.stem for path in iter_markdown(vault)}


def load_records(vault: Path) -> tuple[list[Record], list[Problem]]:
    """Every note with a frontmatter mapping, plus problems for malformed ones.
    Notes with no frontmatter (anchors, README) are neither records nor problems.
    """
    if not vault.is_dir():
        raise DocketError(f"context vault not found: {vault}")
    records: list[Record] = []
    problems: list[Problem] = []
    for path in iter_markdown(vault):
        with open(path, encoding="utf-8", newline="") as fh:
            text = fh.read()
        try:
            fm_text, body = fm.split(text)
            if fm_text is None:
                continue
            fields = fm.parse(fm_text)
        except fm.MalformedFrontmatter as exc:
            problems.append(Problem(path, f"malformed frontmatter: {exc}"))
            continue
        records.append(Record(path, fields, fm_text, body, text))
    return records, problems


def to_date(value: object) -> dt.date | None:
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value).strip())
    except ValueError:
        return None


SCAFFOLD = "scaffold"


def is_scaffold(record: Record) -> bool:
    """`kind: scaffold` marks phase/infra/repo-setup records: work that lands code
    but tests no hypothesis, so it is never unjudged and never needs a gate."""
    return fm.get_field(record.fields, "kind") == SCAFFOLD


def verdict_pending(record: Record) -> bool:
    """No verdict beyond pending: the field is missing, empty, or `pending`."""
    return fm.get_field(record.fields, "verdict") in (None, "", "pending")


def is_unjudged(record: Record) -> bool:
    """Completed (the branch merged) but nobody has written a verdict."""
    return (
        not is_scaffold(record)
        and record.status == "Completed"
        and verdict_pending(record)
    )


def has_no_gate(record: Record) -> bool:
    """In Progress with no gate written: nothing says what would falsify it."""
    return (
        not is_scaffold(record)
        and record.status == "In Progress"
        and not fm.get_field(record.fields, "gate")
    )


def is_stub(record: Record) -> bool:
    """A record `docket check` warns about: unjudged or gate-less. Scaffold
    records are neither. Parked, Falsified and other hand-set statuses are
    never stubs."""
    return is_unjudged(record) or has_no_gate(record)


def overdue_gate(record: Record, now: dt.date) -> int | None:
    """Days since gate_date passed when verdict is still pending, else None."""
    gate_date = to_date(record.fields.get("gate_date"))
    verdict = fm.get_field(record.fields, "verdict")
    if gate_date is None or verdict != "pending":
        return None
    days = (now - gate_date).days
    return days if days > 0 else None


_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(text: str, limit: int = 60) -> str:
    slug = _SLUG_STRIP.sub("-", text.lower()).strip("-")
    if len(slug) > limit:
        slug = slug[:limit].rstrip("-")
    return slug or "untitled"


def titleize(slug: str) -> str:
    words = slug.replace("-", " ").replace("_", " ").split()
    text = " ".join(words)
    return text[:1].upper() + text[1:] if text else slug


def next_number(records: list[Record], prefix: str) -> int:
    """1 + the highest numeric suffix among docket_ids starting with `prefix`."""
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    highest = 0
    for record in records:
        did = record.docket_id
        if did is None:
            continue
        match = pattern.match(did)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def repo_settings(repo: Path) -> dict:
    """The repo's .docket.toml as a dict, empty when there is none."""
    toml_path = repo / ".docket.toml"
    if not toml_path.is_file():
        return {}
    try:
        return tomllib.loads(toml_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise DocketError(f"{toml_path} is not valid TOML: {exc}") from exc


def project_id(repo: Path) -> str:
    """`project_id` from the repo's .docket.toml, else the directory name."""
    value = repo_settings(repo).get("project_id")
    return str(value) if value else repo.name


def is_container(repo: Path) -> bool:
    """`container = true` marks a directory that holds other repos and is not
    one itself, like QuadisPD. It is registered so its records have a project
    to belong to, but it has no wiring of its own to be missing: reporting the
    same expected gaps on every run is noise that trains the eye to skip the
    report."""
    return repo_settings(repo).get("container") is True


def resolve_repo(cfg: Config, name: str) -> Path:
    repo = cfg.projects / name
    if not repo.is_dir():
        raise DocketError(f"repo not found under {cfg.projects}: {name}")
    return repo
