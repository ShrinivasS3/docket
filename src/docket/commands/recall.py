"""docket recall: ranked search over the context vault and, read-only, the
personal vault.

Matching is by stemmed terms (see docket.stem): every note that contains at
least one query term is a hit, scored by how many distinct terms it contains,
and hits are sorted by score descending, so a note matching one of two terms
still appears, below one matching both. Stop words and one-character tokens
are ignored.

Context records are reported by frontmatter only: id, status, title, scope,
path. The body is never printed; `--full <id>` prints one whole record.
Personal-root notes are searched read-only when the configured root exists;
a hit shows the best-matching line plus one line either side.

Results are hard-tiered: every context record first, under its own header,
then personal notes under theirs. A record matching one of two terms ranks
above a note matching both: one is a verdict, the other a mention. Personal
notes are capped at PERSONAL_CAP by default. Within a tier, up to
FULL_FORMAT_MAX_HITS shown hits print in full; more print one compact line
each. CAP bounds rendered lines as a backstop, never hits. Whenever a tier
is cut, a count line says how many were shown, so the result is never
silent. `--all` lifts both caps.

This module has no write path: it imports no write helper and reads files
through Path.read_text only. tests/test_recall.py asserts both.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from docket.config import Config, DocketError
from docket.notes import Record, iter_markdown, load_records
from docket.stem import stem

CAP = 60  # rendered lines; room for two tiers of five full-format hits
PERSONAL_CAP = 5
FULL_FORMAT_MAX_HITS = 5
LINE_WIDTH = 120
COMPACT_WIDTH = 72
CONTEXT_LINES = 1  # lines shown either side of a personal-root match
STOP_WORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "to",
        "with",
    ]
)
_TOKEN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class Hit:
    root: str  # "context" sorts before "personal"
    key: str
    score: int
    compact: str
    full: tuple[str, ...]


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def _stems(text: str) -> set[str]:
    return {stem(tok) for tok in _tokens(text)}


def query_terms(query: str) -> list[str]:
    """Distinct stemmed query terms, in order; stop words and 1-char tokens dropped."""
    terms: list[str] = []
    for tok in _tokens(query):
        if len(tok) < 2 or tok in STOP_WORDS:
            continue
        s = stem(tok)
        if s not in terms:
            terms.append(s)
    if not terms:
        raise DocketError("recall needs at least one searchable word, or --full <id>")
    return terms


def _clip(line: str, width: int = LINE_WIDTH) -> str:
    line = line.rstrip()
    return line if len(line) <= width else line[: width - 1].rstrip() + "…"


def _score_tag(score: int, n_terms: int) -> str:
    return f" · matched {score}/{n_terms}" if n_terms > 1 else ""


def _record_hit(record: Record, root: Path, terms: list[str]) -> Hit | None:
    present = _stems(record.text)
    score = sum(1 for t in terms if t in present)
    if score == 0:
        return None
    ident = record.docket_id or record.path.stem
    status = record.status or "-"
    tag = _score_tag(score, len(terms))
    scope = record.fields.get("scope") or []
    if not isinstance(scope, list):
        scope = [scope]
    parts = [f"[context] {ident}", record.category, record.project, f"status: {status}"]
    full = [" · ".join(p for p in parts if p) + tag, "  " + _clip(record.title)]
    if scope:
        full.append("  scope: " + ", ".join(str(s) for s in scope))
    full.append("  " + record.path.relative_to(root).as_posix())
    compact = (
        f"[context] {ident} · status: {status} · "
        f"{_clip(record.title, COMPACT_WIDTH)}{tag}"
    )
    return Hit("context", ident.lower(), score, compact, tuple(full))


def _best_line(terms: list[str], lines: list[str]) -> int | None:
    """Index of the line holding the most query terms; earliest wins ties."""
    best, best_score = None, 0
    for idx, line in enumerate(lines):
        present = _stems(line)
        score = sum(1 for t in terms if t in present)
        if score > best_score:
            best, best_score = idx, score
    return best


def _personal_hit(path: Path, root: Path, terms: list[str]) -> Hit | None:
    text = path.read_text(encoding="utf-8", errors="replace")
    present = _stems(path.stem + "\n" + text)
    score = sum(1 for t in terms if t in present)
    if score == 0:
        return None
    lines = text.splitlines()
    idx = _best_line(terms, lines)
    if idx is None:  # only the file name matched
        shown, where = [line for line in lines if line.strip()][:1], ""
    else:
        lo = max(0, idx - CONTEXT_LINES)
        hi = min(len(lines), idx + CONTEXT_LINES + 1)
        shown, where = lines[lo:hi], f":{idx + 1}"
    rel = path.relative_to(root).as_posix()
    tag = _score_tag(score, len(terms))
    full = [f"[personal] {rel}{where}{tag}"]
    full.extend("  > " + _clip(line) for line in shown)
    matched = lines[idx].strip() if idx is not None else (shown[0] if shown else "")
    compact = f"[personal] {rel}{where} · {_clip(matched, COMPACT_WIDTH)}{tag}"
    return Hit("personal", rel.lower(), score, compact, tuple(full))


def _full_record(cfg: Config, docket_id: str) -> str:
    wanted = docket_id.strip().lower()
    records, _ = load_records(cfg.context)
    for record in records:
        if (record.docket_id or "").lower() == wanted:
            rel = record.path.relative_to(cfg.context).as_posix()
            return f"[context] {rel}\n{record.text.rstrip()}"
    raise DocketError(f"no context record with docket_id {docket_id}")


def find_hits(cfg: Config, terms: list[str]) -> list[Hit]:
    hits: list[Hit] = []
    records, _ = load_records(cfg.context)
    for record in records:
        hit = _record_hit(record, cfg.context, terms)
        if hit is not None:
            hits.append(hit)
    personal = cfg.roots.get("personal")
    if personal is not None and personal.is_dir():
        for path in iter_markdown(personal):
            hit = _personal_hit(path, personal, terms)
            if hit is not None:
                hits.append(hit)
    hits.sort(key=lambda h: (-h.score, h.root, h.key))
    return hits


def run_recall(
    cfg: Config,
    query: str | None,
    *,
    full: str | None = None,
    show_all: bool = False,
    cap: int = CAP,
) -> str:
    if full:
        return _full_record(cfg, full)
    if not query or not query.strip():
        raise DocketError("recall needs a query, or --full <id>")
    terms = query_terms(query)
    hits = find_hits(cfg, terms)
    if not hits:
        return f'no hits for "{query}"'
    context = [hit for hit in hits if hit.root == "context"]
    personal = [hit for hit in hits if hit.root == "personal"]
    lines = [
        f'{len(hits)} hit(s) for "{query}": {len(context)} context record(s), '
        f"{len(personal)} personal note(s)"
    ]
    tiers = (
        (context, "context records", None),
        (personal, "personal notes", PERSONAL_CAP),
    )
    for tier_hits, noun, tier_cap in tiers:
        if not tier_hits:
            continue
        lines.append(f"## {noun} ({len(tier_hits)})")
        limit = len(tier_hits)
        if tier_cap is not None and not show_all:
            limit = min(tier_cap, limit)
        compact = limit > FULL_FORMAT_MAX_HITS
        shown = 0
        for hit in tier_hits[:limit]:
            block = [hit.compact] if compact else list(hit.full)
            if not show_all and len(lines) + len(block) > cap - 1:
                break
            lines.extend(block)
            shown += 1
        if shown < len(tier_hits):
            lines.append(
                f"{len(tier_hits)} {noun}, showing {shown} — refine the query "
                "or use --all"
            )
    return "\n".join(lines)
