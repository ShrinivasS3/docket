# docket

Research decision log CLI. Writes flat notes with MineHQ-shaped frontmatter into
the context vault and injects marker-delimited blocks into `Dashboard.md`.

    pip install -e .
    docket --help

Configuration lives in `~/.docket/config.toml` (override with `DOCKET_CONFIG`).
Every write is idempotent, confined to the three configured roots, and never
touches file content outside `<!-- docket:begin X -->` / `<!-- docket:end X -->`
markers.

Commands in v0: `capture`, `gotcha`, `recall`, `brief`, `idea import`, `dash`,
`list`, `check`.

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
A third WARN, `<repo> — <n> Completed records while <m> paths uncommitted;
checked-out branch <b> belongs to <id>`, flags the case where `idea import`
marked a branch Completed because its tip sits inside main, which is also what
a branch that never received a commit looks like: the work may be sitting
uncommitted in the tree. One line per repo, never a FAIL.

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
