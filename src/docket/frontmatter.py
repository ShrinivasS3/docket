"""Frontmatter in MineHQ's shape: scalar wikilink values, plain dates, bare tokens.

Parsing uses yaml.safe_load. Rendering is a small deliberate emitter so the output
is byte-stable across runs and matches the vault's hand-written conventions
(double-quoted wikilinks, `merged: false`, `gate: ""`).
"""

from __future__ import annotations

import datetime as dt
import json
import re

import yaml


class MalformedFrontmatter(ValueError):
    """Raised when a file opens a frontmatter block but the block is unusable."""


_FENCE = re.compile(r"^---[ \t]*$")
_CLOSE = re.compile(r"^(---|\.\.\.)[ \t]*$")
_BARE_OK = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./ -]*[A-Za-z0-9_./-]$|^[A-Za-z0-9_]$")
_RESERVED = {
    "true",
    "false",
    "null",
    "yes",
    "no",
    "on",
    "off",
    "y",
    "n",
    "~",
}
_NUMERIC = re.compile(r"^[+-]?(\d[\d_]*(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")
_WIKILINK = re.compile(r"^\[\[(.+?)\]\]$")


def split(text: str) -> tuple[str | None, str]:
    """Return (frontmatter_text, body). frontmatter_text is None when the file has
    no frontmatter. The returned frontmatter text excludes the fences.
    Raises MalformedFrontmatter when the opening fence has no closing fence.
    """
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or not _FENCE.match(lines[0]):
        return None, text
    for idx in range(1, len(lines)):
        if _CLOSE.match(lines[idx]):
            fm = "\n".join(lines[1:idx])
            body = "\n".join(lines[idx + 1 :])
            return fm, body
    raise MalformedFrontmatter("frontmatter opened with --- but never closed")


def parse(fm_text: str) -> dict:
    """Parse frontmatter text into a mapping. Raises MalformedFrontmatter."""
    try:
        data = yaml.safe_load(fm_text)
    except yaml.YAMLError as exc:
        raise MalformedFrontmatter(f"frontmatter is not valid YAML: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise MalformedFrontmatter("frontmatter is not a mapping")
    return data


def load(text: str) -> tuple[dict | None, str]:
    """(fields or None when absent, body)."""
    fm_text, body = split(text)
    if fm_text is None:
        return None, body
    return parse(fm_text), body


def render_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None or value == "":
        return '""'
    if isinstance(value, (dt.date, dt.datetime)):
        return (
            value.date().isoformat()
            if isinstance(value, dt.datetime)
            else value.isoformat()
        )
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(render_value(v) for v in value) + "]"
    text = str(value)
    if (
        _BARE_OK.match(text)
        and text.lower() not in _RESERVED
        and not _NUMERIC.match(text)
        and "  " not in text
    ):
        return text
    return json.dumps(text, ensure_ascii=False)


def render(fields: dict) -> str:
    """Render a frontmatter block including fences and a trailing newline."""
    lines = ["---"]
    for key, value in fields.items():
        lines.append(f"{key}: {render_value(value)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def set_field(fm_text: str, key: str, value: object) -> str:
    """Replace one key's value inside frontmatter text at the line level, leaving
    every other line untouched. Handles a block/list continuation under the key.
    Appends the key when it is missing.
    """
    rendered = f"{key}: {render_value(value)}"
    lines = fm_text.split("\n")
    key_re = re.compile(rf"^{re.escape(key)}\s*:")
    for idx, line in enumerate(lines):
        if key_re.match(line):
            end = idx + 1
            while end < len(lines) and (
                lines[end].startswith((" ", "\t")) or lines[end].startswith("- ")
            ):
                end += 1
            lines[idx:end] = [rendered]
            return "\n".join(lines)
    if lines and lines[-1] == "":
        lines.insert(len(lines) - 1, rendered)
    else:
        lines.append(rendered)
    return "\n".join(lines)


def get_field(fields: dict, key: str) -> str | None:
    """Scalar string view of a field, or None. Lists collapse to their first item."""
    value = fields.get(key)
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None:
        return None
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return str(value)


def link_name(value: object) -> str:
    """`[[Name|alias]]` -> `Name`; bare strings pass through stripped."""
    text = str(value).strip()
    match = _WIKILINK.match(text)
    if match:
        text = match.group(1)
    return text.split("|", 1)[0].split("#", 1)[0].strip()


def link_names(value: object) -> list[str]:
    """All anchor names referenced by a scalar or list field value."""
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    return [link_name(item) for item in items if str(item).strip()]


def wikilink(name: str) -> str:
    return f"[[{name}]]"
