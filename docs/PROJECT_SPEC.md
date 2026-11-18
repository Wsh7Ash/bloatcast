# Project spec — bloatcast

## Name

bloatcast

## Category

database-tooling

## Target user

A database engineer, SRE or backend developer responsible for a PostgreSQL instance who has been told "the tables are bloated" and needs to know which tables are actually past their autovacuum trigger, by how much, and which setting to change.

## Problem

Autovacuum trigger arithmetic is table-specific: the global `0.2` scale factor and 50-row threshold are combined with `reltuples`, then overridden by any per-table `reloptions`. Reading `n_dead_tup` for a few tables is tractable; deciding which of a few hundred tables are genuinely overdue, and what per-table setting would fix it, is not. Existing observability dashboards graph dead tuples as a raw counter and say little about the trigger that should have fired.

## Solution

A stdlib-only CLI that takes a JSON export of `pg_stat_user_tables` plus `pg_class` and returns a ranked report of dead-tuple pressure: effective trigger per table, overdue state, severity, estimated reclaimable bytes, and one concrete `ALTER TABLE ... SET (...)` suggestion for each table above `info`. Text and JSON output, with a `--fail-on` gate for automation.

## Core workflow

1. Run the export query from `docs/USAGE.md` and save `stats.json`.
2. `bloatcast analyze stats.json`
3. Read critical tables first; decide whether the suggested setting matches operational policy.
4. Apply one change, capture a new export, compare.
5. Add `--fail-on critical` to a nightly job so the report cannot silently rot.

## Must-have features

- strict validation with a non-zero exit for unusable input;
- trigger arithmetic that respects per-table `reloptions`;
- four fixed severities with a documented legend;
- dead ratio and estimated reclaimable bytes;
- at most one setting recommendation per table, with the resulting trigger stated;
- text and JSON output plus severity/top filters;
- deterministic output for identical input;
- no database connection, no third-party dependency.

## Nice-to-have features

- `pgstattuple` input for measured bloat;
- before/after comparison of two exports;
- grouped output producing one plan per target setting.

## Stack

Python 3.12+, standard library only, pytest for tests.

## Test strategy

- `test_model.py`: valid example, defaults, partial overrides, per-table override resolution, `reltuples` fallback, and a table of rejected documents (empty list, missing fields, wrong types, booleans as integers, negatives, unknown settings, non-numeric reloptions, duplicates).
- `test_analyze.py`: trigger arithmetic (global and per-table), analyze trigger, ratio and reclaimable arithmetic, each severity branch including boundary cases, empty tables, sorting, counts and `at_or_above`.
- `test_advise.py`: scale-factor recommendation, threshold recommendation on small tables, no advice for `info`/`ok`, no advice when already stricter, identifier quoting, determinism.
- `test_cli.py`: text and JSON structure, filters, `--top`, `--no-advice`, `--fail-on` outcomes, invalid input exits, `rules`.

## Demo/result strategy

`examples/shop_stats.json` is a synthetic 10-table e-commerce export with five critical tables, one warning, one analyze-overdue table and three healthy tables. `results/analysis.txt` and `results/analysis.json` are the captured runs; `RESULTS.md` quotes them and records the gate exit code.

## Safety considerations

Read-only analysis of a user-supplied file. No SQL is executed; generated `ALTER TABLE` text is printed for review. The example data is synthetic and contains no personal information.

## Definition of done

- 62 tests green;
- example analysis produces 5 critical, 1 warn, 1 info, 3 ok and exits 1 under `--fail-on critical`;
- JSON report parses and matches the text summary;
- README/USAGE contain only observed output;
- committed and published.
