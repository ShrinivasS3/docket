"""docket recall: ranked search over the context vault and, read-only, the
personal vault.

Matching is by stemmed terms (see docket.stem): every note that contains at
least one query term is a hit, scored by how many distinct terms it contains,
and hits are sorted by score descending, so a note matching one of two terms
still appears, below one matching both. Stop words and one-character tokens
are ignored. `[recall.aliases]` in config.toml (short = "phrase") expands
both ways, on context records only: a record saying "sr" counts as saying
"successor representation" and vice versa. Records are terse and derive
from branch slugs, so they need it; personal notes are prose that spells
things out, so they match on literal stems, where expansion would only cost
precision.

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
from docket.notes import (
    Record,
    attended_flag,
    iter_markdown,
    load_records,
    matches_attended,
)
from docket.stem import stem

UNATTENDED = "UNATTENDED"  # caps, so it survives a dot-separated lowercase line
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


Alias = tuple[str, frozenset[str]]  # (short stem, phrase stems)


@dataclass(frozen=True)
class Hit:
    root: str  # "context" sorts before "personal"
    key: str
    score: int
    compact: str
    full: tuple[str, ...]
    unattended: bool = False  # written by a process with no human behind it


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def _stems(text: str) -> set[str]:
    return {stem(tok) for tok in _tokens(text)}


def _aliases(cfg: Config) -> list[Alias]:
    pairs: list[Alias] = []
    for short, phrase in cfg.recall.aliases:
        short_stems = [stem(t) for t in _tokens(short)]
        phrase_stems = frozenset(
            stem(t) for t in _tokens(phrase) if len(t) >= 2 and t not in STOP_WORDS
        )
        if len(short_stems) == 1 and phrase_stems:
            pairs.append((short_stems[0], phrase_stems))
    return pairs


def _expand(stems: set[str], aliases: list[Alias]) -> set[str]:
    """Stems plus every alias equivalent: short form implies the phrase's stems,
    the full phrase implies the short form."""
    out = set(stems)
    for short, phrase in aliases:
        if short in stems:
            out |= phrase
        if phrase <= stems:
            out.add(short)
    return out


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


def _record_hit(
    record: Record, root: Path, terms: list[str], aliases: list[Alias]
) -> Hit | None:
    present = _expand(_stems(record.text), aliases)
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
    if attended_flag(record) is False:
        parts.append(UNATTENDED)
    full = [" · ".join(p for p in parts if p) + tag, "  " + _clip(record.title)]
    if scope:
        full.append("  scope: " + ", ".join(str(s) for s in scope))
    full.append("  " + record.path.relative_to(root).as_posix())
    mark = f" · {UNATTENDED}" if attended_flag(record) is False else ""
    compact = (
        f"[context] {ident} · status: {status}{mark} · "
        f"{_clip(record.title, COMPACT_WIDTH)}{tag}"
    )
    return Hit(
        "context",
        ident.lower(),
        score,
        compact,
        tuple(full),
        unattended=attended_flag(record) is False,
    )


def _best_line(terms: list[str], lines: list[str], aliases: list[Alias]) -> int | None:
    """Index of the line holding the most query terms; earliest wins ties."""
    best, best_score = None, 0
    for idx, line in enumerate(lines):
        present = _expand(_stems(line), aliases)
        score = sum(1 for t in terms if t in present)
        if score > best_score:
            best, best_score = idx, score
    return best


def _personal_hit(
    path: Path, root: Path, terms: list[str], aliases: list[Alias]
) -> Hit | None:
    text = path.read_text(encoding="utf-8", errors="replace")
    present = _expand(_stems(path.stem + "\n" + text), aliases)
    score = sum(1 for t in terms if t in present)
    if score == 0:
        return None
    lines = text.splitlines()
    idx = _best_line(terms, lines, aliases)
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


def find_hits(cfg: Config, terms: list[str], attended: bool | None = None) -> list[Hit]:
    aliases = _aliases(cfg)
    hits: list[Hit] = []
    records, _ = load_records(cfg.context)
    for record in records:
        if not matches_attended(record, attended):
            continue
        hit = _record_hit(record, cfg.context, terms, aliases)
        if hit is not None:
            hits.append(hit)
    personal = cfg.roots.get("personal")
    # An attendance filter is a question only a docket record can answer, so the
    # personal tier drops out entirely rather than returning notes the filter
    # never actually tested.
    if attended is None and personal is not None and personal.is_dir():
        for path in iter_markdown(personal):
            hit = _personal_hit(path, personal, terms, [])  # literal stems only
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
    attended: bool | None = None,
    cap: int = CAP,
) -> str:
    if full:
        return _full_record(cfg, full)
    if not query or not query.strip():
        raise DocketError("recall needs a query, or --full <id>")
    terms = query_terms(query)
    hits = find_hits(cfg, terms, attended)
    scope = ""
    if attended is not None:
        scope = (
            f" [{'attended' if attended else UNATTENDED} records only; "
            "personal notes not searched]"
        )
    if not hits:
        return f'no hits for "{query}"{scope}'
    context = [hit for hit in hits if hit.root == "context"]
    personal = [hit for hit in hits if hit.root == "personal"]
    lines = [
        f'{len(hits)} hit(s) for "{query}": {len(context)} context record(s), '
        f"{len(personal)} personal note(s){scope}"
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
    marked = sum(1 for hit in hits if hit.unattended)
    if marked:
        noun = "record" if marked == 1 else "records"
        lines.append(
            f"note: {marked} {noun} marked {UNATTENDED} — written by a "
            "scheduled or autonomous process. No human read the work behind "
            "them, so treat them as unreviewed."
        )
    return "\n".join(lines)
