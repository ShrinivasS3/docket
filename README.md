# docket

Research decision log CLI. Writes flat notes with MineHQ-shaped frontmatter into
the context vault and injects marker-delimited blocks into `Dashboard.md`.

    pip install -e .
    docket --help

Configuration lives in `~/.docket/config.toml` (override with `DOCKET_CONFIG`).
Every write is idempotent, confined to the three configured roots, and never
touches file content outside `<!-- docket:begin X -->` / `<!-- docket:end X -->`
markers.

Commands in v0: `init`, `capture`, `gotcha`, `recall`, `brief`, `idea new`,
`idea import`, `dash`, `list`, `check`, `identity`.

## docket init

    docket init [--namespace <pattern>] [--project-id <id>] [<repo>]
    docket init --check [<repo>]

`init` wires one repo into docket. Every step is skipped when it is already
correct, so running it on a hand-wired repo is a no-op rather than a rewrite:

1. a git repo, a `.gitignore`, the 50 MB `.githooks/pre-commit` guard and
   `core.hooksPath`, and a private remote if there is none
2. the five largest files a push would carry, reported **before** any push.
   A file over 50 MB refuses the remote: GitHub blocks 100 MB outright and the
   fix afterwards is history surgery. This caught a 1.49 GiB `suite_report.html`
   once, and a 1.5 GiB `data/raw/Data.zip` since
3. `.docket.toml` carrying `project_id`
4. the research-log stanza in `AGENTS.md`, **appended**, never replacing what is
   there. The stanza is a template inside the package, so editing it once
   propagates to every repo wired afterwards
5. `CLAUDE.md`: absent becomes a symlink to `AGENTS.md`; a real file gets
   `@AGENTS.md` prepended; one that already imports is left alone
6. the `SessionStart` `docket brief` hook, merged into `.claude/settings.json`
   rather than overwriting it
7. the zero-byte type anchor in the context vault
8. `--namespace` adds a branch pattern to the global `[branches]` table,
   inserted before the `"*"` fallback so specific patterns still win
9. a verification pass: `docket brief` emits, `docket check` passes

`docket init --check [<repo>]` reports only. It writes nothing — no file, no git
mutation, no config edit — and prints one line per repo naming what is missing,
exiting 1 if any repo is incomplete, so it can go in a hook. With no repo
argument it checks every registered repo.

A directory that holds other repos rather than being one — QuadisPD holds the
app and its AWS infra — sets `container = true` in its `.docket.toml`. It is
still registered, so records can be filed against it, but `--check` gives it no
line at all and only counts it as skipped, and `init` refuses to wire it. An
expected condition reported on every run is noise. Branches that reach only the `"*"`
fallback are reported as a note rather than a gap, since a fallback branch is
drift in the namespace rather than missing wiring.

`docket brief <project>` prints a ~200-token digest of one repo, assembled
from files only: the first paragraph of `NORTH_STAR.md`, branch and unpushed
count, the active idea and its gate, the last three ledger rows from
`experiments/RESULTS.tsv`, falsified ideas, overlapping gotchas, and the
nearest deadline naming the project. Fields degrade one by one when a file
is missing, output is fitted to about 250 tokens, and nothing is written.
It is meant for a Claude Code `SessionStart` hook: `docket brief $(basename $PWD)`.

`docket recall "<words>"` searches the context vault and, read-only, the
personal vault. Terms are stemmed (aggregation matches aggregate) and every
note containing at least one term is a hit, ranked by how many terms it
contains. Results are tiered: every context record first, then personal
notes, each under its own header, because a record is a verdict and a note is
a mention. Records come back as frontmatter only (id, status, title, scope,
path), personal notes as the best-matching line plus one either side and
capped at five by default. Within a tier, up to five shown hits print in
full; more print one compact line each. Output is bounded at 60 rendered
lines, and any cut tier ends with a "N ..., showing M" line; `--all` lifts
both caps. `docket recall --full <id>` prints one record. `[recall.aliases]`
in config.toml maps a short form to its phrase (`sr = "successor
representation"`) and recall expands both ways on context records, so
either spelling finds a record that uses the other; personal notes match on
literal stems.

`docket check` triages ideas into two WARN classes, never a FAIL:
`<n> records unjudged — Completed, verdict still pending` (the branch merged,
nobody wrote a verdict) and `<n> records have no gate — In Progress, gate
empty` (nothing says what would falsify it). A record with `kind: scaffold`
in its frontmatter (phase, infra, repo-reset, env-setup work that lands code
but tests nothing) is in neither class. Parked and hand-set statuses are in
neither class either. `docket list --stubs` prints the two warned classes.
A third WARN, `<repo> — <id> is Completed but its branch <b> is checked out
with <n> paths uncommitted`, flags the case where `idea import` marked a
branch Completed because its tip sits inside main, which is also what a branch
that never received a commit looks like: the work may be sitting uncommitted
in the tree. Only the checked-out branch's record can fire, since repo-wide
dirt says nothing about a record whose branch is not checked out. Never a FAIL.

## docket idea new

    docket idea new [--branch <b>] [--gate <text>] [--decide-by <date>]
                    [--parent <id>] [--inherits <G0004[,G0007]>]
                    [--from-scratch <line>] [--kind exploratory|scaffold]

Files one idea against the branch it lives on, run from inside the repo. The
branch list is already a lab notebook — thirty-nine branches in four deliberate
namespaces on PathJEPA alone — so `idea new` reads it rather than asking you to
type it twice: **title, slug and namespace are seeded from the checked-out
branch** (`--branch` overrides), and the branch is matched against `[branches]`
the same way `idea import` matches it. A branch whose pattern says `gotcha` is
refused and pointed at `docket gotcha`; `main` is refused outright, because an
idea earns its own branch.

**It refuses to finish without a gate.** Either `--gate "<the result that would
refute this>"` for a hypothesis, or `--decide-by <YYYY-MM-DD>` for exploratory
work whose question is when to stop rather than what would falsify it. Nothing
is written on that path — no record, no dashboard edit. docket will not pick a
gate for you: a gate it invented is not one you committed to, and `docket check`
would wave it through on the day it was meant to bite. A re-run may leave both
flags off once the record already carries a gate, but an `idea import` stub,
whose gate is `""`, still has to supply one.

`--decide-by` writes `gate_date`, the same field the Blocking callout watches,
so an exploratory thread that quietly outlives its own deadline surfaces on the
dashboard exactly like an overdue hypothesis.

`--parent <id>` and `--inherits <G….>` are the forward links: an idea descends
from another idea, and rests on cross-project findings. Both are stored as bare
ids and are never given a stored backlink — Obsidian computes the inverse. An id
naming nothing in the vault is reported as a `note:` rather than refused, since
the parent may live in a project you have not imported yet.

`--kind scaffold` marks phase, infra and repo-setup work: it lands code but
tests no hypothesis, so `docket check` never counts it unjudged or gate-less.
`--kind exploratory` is its counterpart, the work that takes a date instead.

`--from-scratch "<line>"` promotes a thought out of the `Dashboard.md` scratch
block. It names the line by its exact text, or by any substring that matches
only one — two matches is an error listing both, because promoting the wrong
line edits a file you were not looking at. The line's text is pulled into the
record body as a dated quote, and the line itself is replaced in place with a
three-line stub naming the record, the branch, and the gate:

```markdown
- 2026-09-03: try a nonlinear readout on frozen h_t → [[idea-pathjepa-0035-nonlinear-readout]]
  - promoted 2026-09-04 · pathjepa-0035 · experiments/nonlinear-readout
  - gate: a 2-layer MLP beats ridge-on-frame by >10% position MSE
```

Only the scratch block is read and only the scratch block is rewritten; every
other byte of `Dashboard.md` is returned untouched. Promoting twice rewrites
that stub rather than stacking a second one, and `docket dash`'s ` · Nd` ageing
suffix is stripped before the line is matched or rebuilt.

The record is written into the context vault with the frontmatter shape the
vault already uses, and **is idempotent by `docket_id`**: a second run finds the
record by its branch and edits it rather than adding one. Only the fields you
supplied that run move, and the device that first wrote a record keeps the
credit.

**`idea new` files an idea; it does not adjudicate one.** A new record is
`[[In Progress]]` because that is what filing one means, and on a re-run
`status`, `merged` and `last_commit` are left exactly as they are — so no
status, hand-set (`Falsified`, `Superseded`) or managed, is ever overwritten
here. Branch-derived state is `docket idea import`'s, which reads whole branch
histories; run it and a merged branch moves to `[[Completed]]` with the gate
intact. The split is not tidiness: `idea new` rides `git checkout -b`, so the
branch is typically seconds old with no commits of its own, which git cannot
tell apart from a fast-forward-merged one. Deriving status here would file every
new idea as already finished.

```yaml
categories: "[[Ideas]]"
type: "[[PathJEPA]]"
status: "[[In Progress]]"
docket_id: pathjepa-0035
title: Nonlinear readout
branch: experiments/nonlinear-readout
created: 2026-09-04
last_commit: 2026-09-03
merged: false
gate: "a 2-layer MLP beats ridge-on-frame by >10% position MSE"
gate_date: 2026-09-30
verdict: pending
parent: pathjepa-0034
inherits: [G0004]
device: mac
attended: true
```

`device` and `attended` come from `[identity]` — see below.


## Identity, attendance and commit trailers

```toml
[identity]
device   = "mac"      # a role: mac, cnslab, hermes
attended = true
```

**`device` is a role, never a hostname.** A hostname stops being comparable the
moment the machine is replaced or renamed, and the question a record has to
answer two years later is which role wrote it — not what that laptop happened
to be called. `device` is required when the table exists; there is no default,
because falling back to the hostname would silently reintroduce the exact value
the role replaces. No `[identity]` table at all means neither field is written:
a machine that has not been told its role does not get to claim one.

`attended` says whether a human was at the keyboard. **`--unattended` writes
`attended: false`** and is accepted by every command that authors a record —
`gotcha`, `idea new`, `idea import` — and by `identity`. It always overrides
the config, so a scheduled writer can say so on a machine configured
`attended = true`, and nothing can claim attendance on a sweep's behalf. A
machine that is only ever driven by a scheduler sets `attended = false` as its
default instead. Until something could write `false`, the field carried no
information.

### Reading it back

`docket recall` and `docket list` take `--attended` / `--unattended`. **`recall`
marks unattended hits `UNATTENDED` in the hit line and adds a closing note**, so
an agent reading a result cannot miss that no human ever checked the work:

```
[context] demoproj-0001 · Ideas · DemoProj · status: In Progress · UNATTENDED
  Nightly sweep readout
note: 1 record marked UNATTENDED — written by a scheduled or autonomous
process. No human read the work behind them, so treat them as unreviewed.
```

An attendance filter drops the personal-vault tier entirely rather than
returning notes the filter never tested — attendance is a question only a
docket record can answer. A record written before the field existed carries no
`attended` at all, and matches neither filter: unknown is not the same as
unattended.

### Commit trailers

```
docket identity [--unattended]
```

prints the two trailers and nothing else:

```
Device: mac
Attended: false
```

docket does not commit; its two launchd agents do, and they pass `--unattended`
because launchd ran them and no human read the change. **Trailers, not
`user.name`** — authorship on GitHub stays the user's, while

```
git log --grep="Attended: false"
```

finds every commit no human stood behind. Pass them as the *last* `-m`: git
reads trailers only from the final paragraph, so a prose paragraph after them
silently invalidates the block. In a shell script build the arguments as an
array —

```bash
trailers=$(docket identity --unattended 2>/dev/null) || trailers=""
msg=(-m "log: auto $ts")
[ -n "$trailers" ] && msg+=(-m "$trailers")
git -C "$VAULT" commit -q "${msg[@]}"
```

— because `${trailers:+-m "$trailers"}` splits on the newline between the two
trailers and git then refuses the block. A failed or missing `docket` must
never stop the vault being committed, which is what the `|| trailers=""` is
for.


## Blocking callout

`docket dash` scopes to repos reachable from a `.docket.toml` (the directory
itself, else the nearest ancestor repo, else every repo nested beneath it, so a
directory holding several repos reports each) and lists at most `max_blocking`
entries in this severity order, with a `+N more` line pointing at
`docket check`, which reports the same set uncapped (as `WARN` lines that never
change its exit code). Idle repos are capped at `max_idle` the same way and
mirrored into `docket check` as `IDLE` lines.

1. `gate_date` passed, verdict still pending
2. commits unpushed for more than `unpushed_days`, or no remote configured
3. uncommitted paths whose oldest modification is older than `stale_days`
4. no git repository at all

Thresholds live in `~/.docket/config.toml`:

```toml
[dash]
unpushed_days = 3
stale_days = 7
max_blocking = 5
max_idle = 5
```
