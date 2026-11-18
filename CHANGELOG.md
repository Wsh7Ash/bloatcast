# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses semantic versioning.

## [0.1.0] — 2026-11-18

### Added
- `analyze` command with text and JSON output.
- Autovacuum and autoanalyze trigger arithmetic with per-table `reloptions` overrides.
- Four-level severity model (`ok`, `info`, `warn`, `critical`) with a documented legend.
- Estimated reclaimable bytes per table.
- Per-table `ALTER TABLE ... SET (...)` recommendations targeting 5% dead tuples, with a threshold branch for small tables.
- Flags: `--min-severity`, `--top`, `--no-advice`, `--fail-on`.
- `rules` command.
- Strict export validation with distinct exit code `2`.
- 62 pytest tests and a GitHub Actions workflow.
