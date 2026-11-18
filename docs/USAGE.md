# Usage — bloatcast

## 1. Produce an export

Run this on the database you are reviewing. It needs `pg_monitor` (or superuser) for the statistics views.

```sql
SELECT json_build_object(
  'captured_at', now(),
  'settings', json_build_object(
    'autovacuum_vacuum_threshold', current_setting('autovacuum_vacuum_threshold')::numeric,
    'autovacuum_vacuum_scale_factor', current_setting('autovacuum_vacuum_scale_factor')::numeric,
    'autovacuum_analyze_threshold', current_setting('autovacuum_analyze_threshold')::numeric,
    'autovacuum_analyze_scale_factor', current_setting('autovacuum_analyze_scale_factor')::numeric
  ),
  'tables', json_agg(json_build_object(
    'schema', s.schemaname,
    'table', s.relname,
    'live_tuples', s.n_live_tup,
    'dead_tuples', s.n_dead_tup,
    'reltuples', c.reltuples,
    'table_size_bytes', pg_total_relation_size(c.oid),
    'mod_since_analyze', s.n_mod_since_analyze,
    'reloptions', COALESCE(
      (SELECT json_object_agg(o.option_name, o.option_value)
       FROM pg_options_to_table(c.reloptions) o),
      '{}'::json),
    'last_vacuum', s.last_vacuum,
    'last_autovacuum', s.last_autovacuum
  ))
)
FROM pg_stat_user_tables s
JOIN pg_class c ON c.oid = s.relid;
```

Save the single returned row to `stats.json`. The settings block is optional: when omitted, PostgreSQL defaults are assumed (`50`, `0.2`, `50`, `0.1`).

## 2. JSON shape

```json
{
  "captured_at": "2026-11-18T09:00:00Z",
  "settings": {
    "autovacuum_vacuum_threshold": 50,
    "autovacuum_vacuum_scale_factor": 0.2,
    "autovacuum_analyze_threshold": 50,
    "autovacuum_analyze_scale_factor": 0.1
  },
  "tables": [
    {
      "schema": "public",
      "table": "orders",
      "live_tuples": 4200000,
      "dead_tuples": 1430000,
      "reltuples": 4200000,
      "table_size_bytes": 2899102924,
      "mod_since_analyze": 1221000,
      "reloptions": {"autovacuum_vacuum_scale_factor": "0.05"},
      "last_vacuum": "2026-10-02 03:11:04+00",
      "last_autovacuum": "2026-11-09 04:52:18+00"
    }
  ]
}
```

Required per table: `schema`, `table`, `live_tuples`, `reltuples`, `table_size_bytes`. `dead_tuples`, `mod_since_analyze`, `reloptions`, `last_vacuum` and `last_autovacuum` are optional. Reloption keys are the PostgreSQL option names (`autovacuum_vacuum_scale_factor`); values may be strings or numbers, and numeric options are validated. Unknown keys inside a table object are ignored, but unknown keys in `settings` are rejected.

## 3. Read the report

```shell
$ bloatcast analyze stats.json --min-severity warn
```

Each table gets a severity, its dead ratio, its trigger value, and the arithmetic that produced the verdict. `fix` lines are suggestions only:

```sql
ALTER TABLE public.events SET (autovacuum_vacuum_scale_factor = 0.04);
```

Apply them one at a time, then compare a fresh export. `ALTER TABLE ... SET` affects future autovacuum decisions only; it does not clean up existing dead tuples. Run `VACUUM (VERBOSE, ANALYZE) table` (or `VACUUM FULL` / `pg_repack` if you need the space back on disk).

## 4. CI / cron gate

```shell
bloatcast analyze stats.json --json --fail-on critical > vacuum-report.json
```

Exit `1` means at least one critical table. A nightly job that captures the export, runs bloatcast and publishes `vacuum-report.json` is enough to make dead-space regressions visible.

## 5. Options

| Flag | Effect |
|---|---|
| `--json` | machine-readable report |
| `--min-severity` | hide findings below `ok`/`info`/`warn`/`critical` |
| `--top N` | keep only the N highest-priority findings (also applies to JSON) |
| `--no-advice` | omit `ALTER TABLE` suggestions |
| `--fail-on` | exit `1` if a finding at that severity exists |
| `rules` | print the severity legend and trigger formulas |

## 6. Limits worth knowing

- `pg_stat_user_tables` is a cumulative estimate that resets on crash recovery and is not a page-level bloat measurement.
- `reloptions` only contains options set explicitly on the table; role/database-level settings are not visible in the export.
- Partitioned parent tables and foreign tables have no meaningful dead-tuple counters and should be excluded or reviewed separately.
