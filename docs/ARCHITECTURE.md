# Architecture — bloatcast

## Overview

```text
stats.json
   │
   ▼
model.load_export ──► model.parse_export ──► StatsExport(settings, tables)
   │                       (validation)
   ▼
analyze.analyze ──► Finding(severity, code, triggers, reclaimable_bytes, reasons)
   │
   ├─► advise.recommend_all ──► Recommendation(sql, setting, note)
   │
   └─► render.render_text / render_json ──► stdout; cli.main returns the exit code
```

No database driver, no network, no global state.

## Model (`model.py`)

`TableStats` is a frozen dataclass with the counters, `reloptions` and vacuum timestamps. `StatsExport` holds the settings and a tuple of tables. Validation is explicit and fails with `StatsError`:

- integers must be integers (booleans are rejected), non-negative;
- `reltuples` must be a non-negative number;
- reloption values for the four known numeric options must parse and be non-negative;
- `settings` may only contain the four known keys and `*_scale_factor` must be ≤ 1;
- `(schema, table)` must be unique;
- an empty table list is rejected — an empty report is almost always a broken export.

`effective_option()` resolves a setting per table and returns its source (`table` or `global`), which keeps the override rule in one place.

## Analysis (`analyze.py`)

For each table:

1. `vacuum_trigger = floor(threshold + scale × row_estimate)`, `row_estimate` being `reltuples` or, if that is zero, `n_live_tup`.
2. `dead_ratio = dead / (live + dead)`; empty tables are `ok`/`empty-table`.
3. `vacuum_overdue = dead >= vacuum_trigger`.
4. Severity from the overdue flag and the ratio:

   | Condition | Severity | Code |
   |---|---|---|
   | overdue and ratio ≥ 0.20 | `critical` | `vacuum-critical` |
   | overdue | `warn` | `vacuum-overdue` |
   | ratio ≥ 0.30 | `warn` | `dead-space` |
   | ratio ≥ 0.10 | `info` | `dead-space` |
   | analyze overdue | `info` | `analyze-overdue` |
   | otherwise | `ok` | `within-threshold` |

5. `reclaimable_bytes = round(size × dead_ratio)`.

Findings are sorted by severity descending, reclaimable bytes descending, then qualified name. `Analysis.counts`, `reclaimable_bytes` and `at_or_above()` are derived, not stored, so they cannot drift.

## Advice (`advise.py`)

Only `warn` and `critical` tables get a suggestion, and only if the current effective trigger is stricter than the policy:

```text
target = 0.05
if threshold + scale × rows <= target × rows: no change
factor = target − threshold / rows
if factor >= 0.01: lower autovacuum_vacuum_scale_factor to floor(factor, 2dp)
else:              lower autovacuum_vacuum_threshold to round(target × rows), minimum 10
```

The small-table branch exists because the 50-row constant dominates the trigger for tables with a few thousand rows: scaling down a percentage that is already irrelevant changes nothing. Identifiers are quoted only when they are not safe unquoted names.

Recommendations are text, not statements that run. Applying them is a human decision, and the tool states the resulting trigger for review.

## Rendering (`render.py`)

`render_text` prints severity, table, ratio, reclaimable space, trigger arithmetic, reasons and the fix. `render_json` emits `{captured_at, settings, summary, findings, recommendations}` with the same filters. `--top` and `--min-severity` are applied to the finding list before rendering, so text and JSON never disagree about what was shown.

## CLI and exit codes

`cli.main(argv)` is a pure function returning an integer, which is why the tests call it directly with `capsys`:

- `0` — analysis produced, gate not triggered;
- `1` — gate (`--fail-on`) matched;
- `2` — unreadable/invalid export, bad `--top`.

## Design decisions

- **Offline by design.** The tool is useful in a review, in CI, and on a dump from a database you cannot connect to.
- **Fixed thresholds.** Configuration would make two reports incomparable; the policy is documented and easy to fork.
- **`floor` for triggers.** A trigger of 210,050.9 is reported as 210,050, matching "dead ≥ trigger" as the conservative boundary.
- **Advice is advisory.** No `--apply`; setting changes on a production table deserve their own review.
