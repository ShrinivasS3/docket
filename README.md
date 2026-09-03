# docket

Research decision log CLI. Writes flat notes with MineHQ-shaped frontmatter into
the context vault and injects marker-delimited blocks into `Dashboard.md`.

    pip install -e .
    docket --help

Configuration lives in `~/.docket/config.toml` (override with `DOCKET_CONFIG`).
Every write is idempotent, confined to the three configured roots, and never
touches file content outside `<!-- docket:begin X -->` / `<!-- docket:end X -->`
markers.

Commands in v0: `capture`, `gotcha`, `idea import`, `dash`, `list`, `check`.

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
