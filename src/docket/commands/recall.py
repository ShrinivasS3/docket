"""docket recall: search the context vault and, read-only, the personal vault.

Structured records (notes with frontmatter under the context root) are reported
by frontmatter only: id, status, title, scope, path. The body is never printed;
`--full <id>` prints one whole record on request.

Personal-root notes are searched read-only when the configured personal root
exists. A hit shows the matched line and one line either side, three at most.

Output is capped at CAP lines. When the hits would exceed it the command prints
the counts and asks for a tighter query instead of truncating, so a caller can
never mistake a partial listing for the whole picture.

This module has no write path: it imports no write helper and reads files
through Path.read_text only. tests/test_recall.py asserts both.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from docket.config import Config, DocketError
from docket.notes import Record, iter_markdown, load_records

CAP = 40
LINE_WIDTH = 120
CONTEXT_LINES = 1  # lines shown either side of a personal-root match


@dataclass(frozen=True)
class Hit:
    root: str
    lines: tuple[str, ...]


def _words(query: str) -> list[str]:
    words = [w.lower() for w in query.split()]
    if not words:
        raise DocketError("recall needs a non-empty query, or --full <id>")
    return words


def _matches(words: list[str], haystack: str) -> bool:
    return all(word in haystack for word in words)


def _clip(line: str, width: int = LINE_WIDTH) -> str:
    line = line.rstrip()
    return line if len(line) <= width else line[: width - 1].rstrip() + "…"


def _record_hit(record: Record, root: Path) -> Hit:
    scope = record.fields.get("scope") or []
    if not isinstance(scope, list):
        scope = [scope]
    parts = [
        f"[context] {record.docket_id or record.path.stem}",
        record.category,
        record.project,
        f"status: {record.status or '-'}",
    ]
    lines = [" · ".join(p for p in parts if p), "  " + _clip(record.title)]
    if scope:
        lines.append("  scope: " + ", ".join(str(s) for s in scope))
    lines.append("  " + record.path.relative_to(root).as_posix())
    return Hit("context", tuple(lines))


def _best_line(words: list[str], phrase: str, lines: list[str]) -> int | None:
    """Index of the line carrying the most query words; a line holding the whole
    phrase outranks any partial match. Earliest wins ties. None if no line hits."""
    best, best_score = None, 0
    for idx, line in enumerate(lines):
        low = line.lower()
        score = sum(1 for word in words if word in low)
        if score and phrase in low:
            score += len(words)
        if score > best_score:
            best, best_score = idx, score
    return best


def _personal_hit(path: Path, root: Path, words: list[str], phrase: str) -> Hit | None:
    text = path.read_text(encoding="utf-8", errors="replace")
    if not _matches(words, path.stem.lower() + "\n" + text.lower()):
        return None
    lines = text.splitlines()
    idx = _best_line(words, phrase, lines)
    if idx is None:  # only the file name matched
        shown, where = [line for line in lines if line.strip()][:1], ""
    else:
        lo = max(0, idx - CONTEXT_LINES)
        hi = min(len(lines), idx + CONTEXT_LINES + 1)
        shown, where = lines[lo:hi], f":{idx + 1}"
    out = [f"[personal] {path.relative_to(root).as_posix()}{where}"]
    out.extend("  > " + _clip(line) for line in shown)
    return Hit("personal", tuple(out))


def _full_record(cfg: Config, docket_id: str) -> str:
    wanted = docket_id.strip().lower()
    records, _ = load_records(cfg.context)
    for record in records:
        if (record.docket_id or "").lower() == wanted:
            rel = record.path.relative_to(cfg.context).as_posix()
            return f"[context] {rel}\n{record.text.rstrip()}"
    raise DocketError(f"no context record with docket_id {docket_id}")


def run_recall(
    cfg: Config, query: str | None, *, full: str | None = None, cap: int = CAP
) -> str:
    if full:
        return _full_record(cfg, full)
    if not query or not query.strip():
        raise DocketError("recall needs a query, or --full <id>")
    words = _words(query)
    phrase = " ".join(words)

    records, _ = load_records(cfg.context)
    records.sort(key=lambda r: ((r.docket_id or "~").lower(), r.path.name.lower()))
    hits = [
        _record_hit(record, cfg.context)
        for record in records
        if _matches(words, record.text.lower())
    ]
    personal = cfg.roots.get("personal")
    if personal is not None and personal.is_dir():
        for path in iter_markdown(personal):
            hit = _personal_hit(path, personal, words, phrase)
            if hit is not None:
                hits.append(hit)

    if not hits:
        return f'no hits for "{query}"'
    n_context = sum(1 for hit in hits if hit.root == "context")
    summary = (
        f'{len(hits)} hit(s) for "{query}": {n_context} context record(s), '
        f"{len(hits) - n_context} personal note(s)"
    )
    needed = 1 + sum(len(hit.lines) for hit in hits)
    if needed > cap:
        return (
            f"{summary}\n{needed} lines needed, over the {cap}-line cap. Nothing "
            "shown: tighten the query (add a scope tag, a project name, or a more "
            "distinctive word)."
        )
    out = [summary]
    for hit in hits:
        out.extend(hit.lines)
    return "\n".join(out)
