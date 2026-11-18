# Results — bloatcast

## Environment
- OS: Windows (MSYS2/Git Bash)
- Runtime: Python 3.14.3
- Dependency manager: pip (stdio-only runtime, no dependencies)
- Test runner: pytest 9.1.1

## Validation performed
- install: PASS (`PYTHONPATH=src python -c "import bloatcast.cli"`)
- build: PASS (no build step; the CLI runs from source)
- unit tests: PASS (62 passed)
- integration tests: PASS (CLI runs against the bundled 10-table export in text and JSON mode)
- lint: N/A (no linter configured for this stdlib-only project)
- type check: N/A (no type checker in scope for this run)
- demo run: PASS (`--fail-on critical` reports 5 critical tables and exits 1, which is the expected gate result)

## Commands executed
```shell
cd projects/2026-11-18/bloatcast
PYTHONPATH=src python -m pytest tests/ -q
PYTHONPATH=src python -m bloatcast analyze examples/shop_stats.json --fail-on critical
PYTHONPATH=src python -m bloatcast analyze examples/shop_stats.json --json
PYTHONPATH=src python -m bloatcast rules
```

## Observed result

`pytest`: `62 passed in 0.69s`.

`analyze --fail-on critical` exits `1` and reports:

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
         rows live 4,200,000 / dead 1,430,000 | trigger 210,050 | size 2.7 GiB
         - dead tuples 1,430,000 reached the autovacuum trigger 210,050
         - 25.4% of tuples are dead
         - 1,221,000 rows changed since the last analyze (threshold 420,050)
         - last vacuum recorded at 2026-11-09 04:52:18+00
         fix ALTER TABLE public.orders SET (autovacuum_vacuum_scale_factor = 0.04);
             triggers at 168,050 dead tuples (5% of ~4,200,000 rows) instead of 210,050

CRITICAL public.invoices                     20.0% dead |  64.0 MiB reclaimable
...
CRITICAL public.products                     30.0% dead |  12.0 MiB reclaimable
...
CRITICAL public.notifications                29.7% dead | 118.8 KiB reclaimable
...
WARN     public.users                        19.4% dead |   4.8 MiB reclaimable
...
INFO     public.audit_log                     9.4% dead |  95.9 MiB reclaimable
...
summary: 5 critical, 1 warn, 1 info, 3 ok | ~2.8 GiB estimated reclaimable
note: ratios come from pg_stat_user_tables estimates; VACUUM makes space reusable, it does not return it to the filesystem (VACUUM FULL / pg_repack do).
```

The full text is in `results/analysis.txt`. `results/analysis.json` has the same run in JSON: `summary.counts = {ok: 3, info: 1, warn: 1, critical: 5}`, 10 findings, 6 recommendations, `reclaimable_bytes = 2987744534`.

The orders row also demonstrates per-table `reloptions`: its trigger is `210,050` (`50 + 0.05 × 4,200,000`), not the global `840,050`.

## Generated artifacts
- `results/analysis.txt` — captured text report (gate exit 1)
- `results/analysis.json` — captured JSON report
- `results/validation.log` — captured pytest run

## Known limitations
- Estimates, not measurements: no `pgstattuple`, no page inspection.
- Reclaimable bytes approximate index and TOAST space by scaling total size.
- Locks, running autovacuum workers and replication slots are invisible; an overdue table may be blocked rather than unmaintained.
- Role/database-level autovacuum settings are not visible unless the export includes them (bloatcast only reads the settings block and table `reloptions`).
- Advice targets a fixed 5% dead-tuple policy and is printed, never applied.
