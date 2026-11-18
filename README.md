# bloatcast

## Know which PostgreSQL tables are about to need a vacuum, and what to change

`bloatcast` reads a JSON export of PostgreSQL table statistics and turns it into a ranked vacuum-pressure report: dead-tuple ratio, the exact autovacuum trigger for each table (including per-table `reloptions`), estimated reclaimable space, and a concrete `ALTER TABLE ... SET (...)` suggestion when the current trigger is too lax. It never connects to a database.

- **Problem:** `n_dead_tup` is a raw counter. Whether a table is a problem depends on `reltuples`, its own `reloptions`, and the global autovacuum settings — arithmetic nobody does by hand for 200 tables.
- **Solution:** deterministic threshold arithmetic, four fixed severities, and a CI gate that fails when critical tables exist.
- **Audience:** database engineers, SREs and backend teams who want a reviewable vacuum plan before tuning production settings.

## Quick start

```shell
pip install -e ".[dev]"

bloatcast analyze examples/shop_stats.json
bloatcast analyze examples/shop_stats.json --json --fail-on critical
```

Exit code is `0` by default, `1` when `--fail-on` is set and a matching finding exists, `2` for unreadable input.

## Observed output

From `results/analysis.txt` (the bundled example, `--fail-on critical` exits `1`):

```text
bloatcast - vacuum pressure report
captured 2026-11-18T09:00:00Z | 10 tables | global trigger 50 + 0.20 x rows

CRITICAL public.events                       24.1% dead |   1.9 GiB reclaimable
         rows live 30,000,000 / dead 9,500,000 | trigger 6,000,050 | size 8.0 GiB
         - dead tuples 9,500,000 reached the autovacuum trigger 6,000,050
         - 24.1% of tuples are dead
         - last vacuum recorded at 2026-11-17 22:40:55+00
         fix ALTER TABLE public.events SET (autovacuum_vacuum_scale_factor = 0.04);
             triggers at 1,200,050 dead tuples (5% of ~30,000,000 rows) instead of 6,000,050

CRITICAL public.orders                       25.4% dead | 702.2 MiB reclaimable
...
WARN     public.users                        19.4% dead |   4.8 MiB reclaimable
...
summary: 5 critical, 1 warn, 1 info, 3 ok | ~2.8 GiB estimated reclaimable
```

## How a table is classified

Autovacuum fires when `dead_tuples` reaches `autovacuum_vacuum_threshold + autovacuum_vacuum_scale_factor × reltuples`; autoanalyze uses the same shape with its own two settings. Per-table `ALTER TABLE ... SET (...)` options override the global values, and bloatcast resolves them in that order.

| Severity | Condition |
|---|---|
| `critical` | past the vacuum trigger **and** at least 20% of tuples are dead |
| `warn` | past the vacuum trigger, or at least 30% dead |
| `info` | at least 10% dead, or rows changed past the analyze trigger |
| `ok` | inside the trigger budget |

Recommendations target 5% dead tuples. On large tables that means a lower `autovacuum_vacuum_scale_factor`; on small tables the 50-row constant dominates, so bloatcast lowers `autovacuum_vacuum_threshold` instead. Suggestions are printed, never applied.

## Features

- trigger arithmetic per table with `reloptions` overrides;
- estimated reclaimable bytes from the dead-tuple share (approximate, includes indexes);
- severities with a stable legend (`bloatcast rules`);
- text and JSON output, `--min-severity`, `--top`, `--no-advice`;
- `--fail-on` gate for cron jobs and CI;
- strict input validation: types, negative counters, unknown settings, duplicate tables, malformed JSON;
- zero runtime dependencies, no database connection.

## Architecture

```text
stats.json ──► model.load_export ──► analyze.analyze ──► advise.recommend_all ──► render/cli
                    (validate)        (triggers,           (ALTER suggestions)     (text/JSON,
                                       severities)                                   exit code)
```

- `model.py` validates the export and resolves effective settings.
- `analyze.py` computes triggers, ratios, reclaimable bytes and severities.
- `advise.py` proposes at most one setting change per table.
- `render.py` formats text or JSON; `cli.py` owns arguments and exit codes.

Details in `docs/ARCHITECTURE.md`.

## Requirements

- Python 3.12+
- No runtime dependencies; `pytest` for the test suite

## Installation

```shell
git clone https://github.com/Wsh7Ash/bloatcast
cd bloatcast
pip install -e ".[dev]"
```

## Usage

```shell
bloatcast analyze PATH [--json] [--min-severity ok|info|warn|critical]
                       [--top N] [--no-advice] [--fail-on none|info|warn|critical]
bloatcast rules
```

`docs/USAGE.md` contains the SQL that produces a compatible export, the JSON schema, and recipes for cron and CI.

## Configuration

There is no config file. The export carries the global settings it was produced under (`settings`), and per-table `reloptions` are read from `pg_class`. Severities and the 5% recommendation target are fixed so the same export always yields the same verdict.

## Testing

```shell
PYTHONPATH=src python -m pytest tests/ -v
```

62 tests cover parsing/validation, trigger arithmetic, boundary classification, reclaimable estimates, recommendation arithmetic, identifier quoting, rendering and exit codes. `results/validation.log` is the captured run.

## Project structure

```text
bloatcast/
├─ src/bloatcast/{model,analyze,advise,render,cli}.py
├─ tests/{test_model,test_analyze,test_advise,test_cli}.py
├─ examples/shop_stats.json
├─ docs/{ARCHITECTURE,USAGE,PROJECT_SPEC}.md
├─ results/{analysis.txt,analysis.json,validation.log}
├─ RESULTS.md
└─ .github/workflows/ci.yml
```

## Limitations

- All numbers are estimates from `pg_stat_user_tables`/`pg_class`; the dead-tuple ratio is not a page-level bloat measurement (`pgstattuple` is).
- Reclaimable bytes scale `pg_total_relation_size` by the dead-tuple share, so index and TOAST space are approximated, not measured.
- A table past its trigger is reported even if a long-running transaction is currently blocking autovacuum; bloatcast cannot see locks or autovacuum workers.
- `reltuples` can be stale; bloatcast falls back to `n_live_tup` only when it is zero.
- `last_vacuum`/`last_autovacuum` are echoed for context, not used in scoring.
- VACUUM makes space reusable; it does not return it to the filesystem.

## Roadmap

- Optional `pgstattuple` input for measured rather than estimated bloat.
- Compare two exports (`before`/`after`) to verify a tuning change.
- Emit a single combined `ALTER TABLE` plan grouped by target setting.

## License

MIT — see `LICENSE`.
