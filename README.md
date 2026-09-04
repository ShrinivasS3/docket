# docket

Research decision log CLI. Writes flat notes with MineHQ-shaped frontmatter into
the context vault and injects marker-delimited blocks into `Dashboard.md`.

    pip install -e .
    docket --help

Configuration lives in `~/.docket/config.toml` (override with `DOCKET_CONFIG`).
Every write is idempotent, confined to the three configured roots, and never
touches file content outside `<!-- docket:begin X -->` / `<!-- docket:end X -->`
markers.

Commands in v0: `capture`, `gotcha`, `recall`, `idea import`, `dash`, `list`,
`check`.

`docket recall "<words>"` searches the context vault and, read-only, the
personal vault. Terms are stemmed (aggregation matches aggregate) and every
note containing at least one term is a hit, ranked by how many terms it
contains. Records come back as frontmatter only (id, status, title, scope,
path), personal notes as the best-matching line plus one either side. Up to
five hits print in full; more print one compact line each. Output is capped
at 40 rendered lines and ends with a "N hits, showing M" line when cut;
`--all` lifts the cap. `docket recall --full <id>` prints one record.

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
