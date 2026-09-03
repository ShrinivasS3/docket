"""Marker-delimited block injection: <!-- docket:begin X --> ... <!-- docket:end X -->.

Only the lines strictly between the markers are ever regenerated. Everything else
in the file is returned byte-for-byte, line endings included.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_RULE = re.compile(r"^\s*_{3,}\s*$")


def begin_marker(name: str) -> str:
    return f"<!-- docket:begin {name} -->"


def end_marker(name: str) -> str:
    return f"<!-- docket:end {name} -->"


@dataclass
class Doc:
    """A text file as lines plus its newline convention."""

    lines: list[str]
    newline: str

    @classmethod
    def from_text(cls, text: str) -> Doc:
        newline = "\r\n" if "\r\n" in text else "\n"
        return cls(text.replace("\r\n", "\n").split("\n"), newline)

    def to_text(self) -> str:
        return self.newline.join(self.lines)

    def find_block(self, name: str) -> tuple[int, int] | None:
        """(index of begin line, index of end line) or None if either is missing."""
        begin = end = None
        b_marker, e_marker = begin_marker(name), end_marker(name)
        for idx, line in enumerate(self.lines):
            stripped = line.strip()
            if begin is None and stripped == b_marker:
                begin = idx
            elif begin is not None and stripped == e_marker:
                end = idx
                break
        if begin is None or end is None:
            return None
        return begin, end

    def block_lines(self, name: str) -> list[str] | None:
        found = self.find_block(name)
        if found is None:
            return None
        begin, end = found
        return self.lines[begin + 1 : end]

    def replace_block(self, name: str, inner: list[str]) -> bool:
        """Regenerate the block body. Returns False when the markers are absent."""
        found = self.find_block(name)
        if found is None:
            return False
        begin, end = found
        self.lines[begin + 1 : end] = list(inner)
        return True

    def append_to_block(self, name: str, new_lines: list[str]) -> bool:
        found = self.find_block(name)
        if found is None:
            return False
        _, end = found
        self.lines[end:end] = list(new_lines)
        return True

    def ensure_block_after_rule(self, name: str) -> bool:
        """Create an empty marker pair immediately after the first `___` rule when
        the block is missing. Falls back to the end of the file when there is no
        rule. Returns True if markers were inserted.
        """
        if self.find_block(name) is not None:
            return False
        markers = [begin_marker(name), end_marker(name)]
        for idx, line in enumerate(self.lines):
            if _RULE.match(line):
                insert = ["", *markers]
                nxt = self.lines[idx + 1] if idx + 1 < len(self.lines) else None
                if nxt is not None and nxt.strip() != "":
                    insert.append("")
                self.lines[idx + 1 : idx + 1] = insert
                return True
        # No rule: append at the end, keeping a single trailing newline.
        while self.lines and self.lines[-1] == "":
            self.lines.pop()
        self.lines.extend(["", *markers, ""])
        return True
