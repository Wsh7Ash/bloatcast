"""Load and validate a PostgreSQL table-statistics export.

The input is a JSON document produced by the queries in ``docs/USAGE.md``. All
numbers are estimates taken from ``pg_stat_user_tables`` and ``pg_class``; no
database connection is made by this tool.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

DEFAULT_SETTINGS: dict[str, float] = {
    "autovacuum_vacuum_threshold": 50.0,
    "autovacuum_vacuum_scale_factor": 0.2,
    "autovacuum_analyze_threshold": 50.0,
    "autovacuum_analyze_scale_factor": 0.1,
}

NUMERIC_RELOPTIONS = frozenset(DEFAULT_SETTINGS)


class StatsError(ValueError):
    """Raised when the export cannot be read as table statistics."""


@dataclass(frozen=True)
class TableStats:
    schema: str
    table: str
    live_tuples: int
    dead_tuples: int
    reltuples: float
    size_bytes: int
    mod_since_analyze: int
    reloptions: Mapping[str, str]
    last_vacuum: str | None = None
    last_autovacuum: str | None = None

    @property
    def qualified(self) -> str:
        return f"{self.schema}.{self.table}"

    @property
    def total_tuples(self) -> int:
        return self.live_tuples + self.dead_tuples

    @property
    def row_estimate(self) -> float:
        """Rows the planner believes exist; falls back to live tuples."""
        return self.reltuples if self.reltuples > 0 else float(self.live_tuples)


@dataclass(frozen=True)
class StatsExport:
    captured_at: str | None
    settings: Mapping[str, float]
    tables: tuple[TableStats, ...]


def _integer(value: Any, field: str, where: str, *, allow_zero: bool = True) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StatsError(f"{where}: {field} must be an integer, got {value!r}")
    if value < 0 or (value == 0 and not allow_zero):
        raise StatsError(f"{where}: {field} must be greater than {'or equal to ' if allow_zero else ''}zero")
    return value


def _number(value: Any, field: str, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StatsError(f"{where}: {field} must be a number, got {value!r}")
    if value < 0:
        raise StatsError(f"{where}: {field} must not be negative")
    return float(value)


def _settings(raw: Any) -> dict[str, float]:
    settings = dict(DEFAULT_SETTINGS)
    if raw is None:
        return settings
    if not isinstance(raw, dict):
        raise StatsError("settings must be an object")
    for key, value in raw.items():
        if key not in DEFAULT_SETTINGS:
            raise StatsError(f"settings: unknown key {key!r}")
        settings[key] = _number(value, key, "settings")
    if settings["autovacuum_vacuum_scale_factor"] > 1:
        raise StatsError("settings: autovacuum_vacuum_scale_factor must be <= 1")
    if settings["autovacuum_analyze_scale_factor"] > 1:
        raise StatsError("settings: autovacuum_analyze_scale_factor must be <= 1")
    return settings


def _reloptions(raw: Any, where: str) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise StatsError(f"{where}: reloptions must be an object")
    options: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, (str, int, float)) or isinstance(value, bool):
            raise StatsError(f"{where}: reloption {key!r} must map to a string or number")
        text = str(value)
        if key in NUMERIC_RELOPTIONS:
            try:
                number = float(text)
            except ValueError as exc:
                raise StatsError(f"{where}: reloption {key} is not numeric: {text!r}") from exc
            if number < 0:
                raise StatsError(f"{where}: reloption {key} must not be negative")
        options[key] = text
    return options


def _table(raw: Any, index: int) -> TableStats:
    where = f"tables[{index}]"
    if not isinstance(raw, dict):
        raise StatsError(f"{where}: must be an object")
    for required in ("schema", "table", "live_tuples", "reltuples", "table_size_bytes"):
        if required not in raw:
            raise StatsError(f"{where}: missing required field {required!r}")
    schema = raw["schema"]
    table = raw["table"]
    if not isinstance(schema, str) or not schema.strip():
        raise StatsError(f"{where}: schema must be a non-empty string")
    if not isinstance(table, str) or not table.strip():
        raise StatsError(f"{where}: table must be a non-empty string")
    where = f"{where} ({schema}.{table})"
    dead = _integer(raw.get("dead_tuples", 0), "dead_tuples", where)
    return TableStats(
        schema=schema,
        table=table,
        live_tuples=_integer(raw["live_tuples"], "live_tuples", where),
        dead_tuples=dead,
        reltuples=_number(raw["reltuples"], "reltuples", where),
        size_bytes=_integer(raw["table_size_bytes"], "table_size_bytes", where),
        mod_since_analyze=_integer(raw.get("mod_since_analyze", 0), "mod_since_analyze", where),
        reloptions=_reloptions(raw.get("reloptions"), where),
        last_vacuum=raw.get("last_vacuum"),
        last_autovacuum=raw.get("last_autovacuum"),
    )


def parse_export(document: Any) -> StatsExport:
    if not isinstance(document, dict):
        raise StatsError("export must be a JSON object")
    captured_at = document.get("captured_at")
    if captured_at is not None and not isinstance(captured_at, str):
        raise StatsError("captured_at must be a string")
    tables_raw = document.get("tables")
    if not isinstance(tables_raw, list) or not tables_raw:
        raise StatsError("tables must be a non-empty list")
    tables = tuple(_table(raw, i) for i, raw in enumerate(tables_raw))
    seen: set[str] = set()
    for table in tables:
        if table.qualified in seen:
            raise StatsError(f"duplicate table entry: {table.qualified}")
        seen.add(table.qualified)
    return StatsExport(captured_at=captured_at, settings=_settings(document.get("settings")), tables=tables)


def load_export(path: str | Path) -> StatsExport:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise StatsError(f"cannot read {path}: {exc.strerror or exc}") from exc
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StatsError(f"{path} is not valid JSON: line {exc.lineno} column {exc.colno}: {exc.msg}") from exc
    return parse_export(document)


def effective_option(table: TableStats, settings: Mapping[str, float], name: str) -> tuple[float, str]:
    """Resolve a setting for a table. Returns (value, source)."""
    if name in table.reloptions:
        return float(table.reloptions[name]), "table"
    return float(settings[name]), "global"
