import json
from pathlib import Path

import pytest

from bloatcast.model import (
    DEFAULT_SETTINGS,
    StatsError,
    effective_option,
    load_export,
    parse_export,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "shop_stats.json"


def minimal_table(**overrides):
    table = {
        "schema": "public",
        "table": "orders",
        "live_tuples": 1000,
        "dead_tuples": 10,
        "reltuples": 1000,
        "table_size_bytes": 8192,
        "mod_since_analyze": 0,
    }
    table.update(overrides)
    return table


def test_loads_example_export():
    export = load_export(EXAMPLE)
    assert export.captured_at == "2026-11-18T09:00:00Z"
    assert len(export.tables) == 10
    assert export.settings["autovacuum_vacuum_scale_factor"] == 0.2
    orders = next(t for t in export.tables if t.table == "orders")
    assert orders.qualified == "public.orders"
    assert orders.total_tuples == 5_630_000
    assert orders.reloptions["autovacuum_vacuum_scale_factor"] == "0.05"


def test_settings_default_when_absent():
    export = parse_export({"tables": [minimal_table()]})
    assert export.settings == pytest.approx(DEFAULT_SETTINGS)
    assert export.captured_at is None


def test_settings_override_and_partial():
    export = parse_export(
        {"settings": {"autovacuum_vacuum_scale_factor": 0.05}, "tables": [minimal_table()]}
    )
    assert export.settings["autovacuum_vacuum_scale_factor"] == pytest.approx(0.05)
    assert export.settings["autovacuum_vacuum_threshold"] == 50.0


def test_effective_option_prefers_table_reloptions():
    export = parse_export(
        {"tables": [minimal_table(reloptions={"autovacuum_vacuum_scale_factor": "0.01"})]}
    )
    value, source = effective_option(
        export.tables[0], export.settings, "autovacuum_vacuum_scale_factor"
    )
    assert value == pytest.approx(0.01)
    assert source == "table"


def test_effective_option_falls_back_to_global():
    export = parse_export({"tables": [minimal_table()]})
    value, source = effective_option(
        export.tables[0], export.settings, "autovacuum_vacuum_threshold"
    )
    assert value == 50.0
    assert source == "global"


def test_row_estimate_falls_back_to_live_tuples():
    export = parse_export({"tables": [minimal_table(reltuples=0, live_tuples=321)]})
    assert export.tables[0].row_estimate == 321.0


@pytest.mark.parametrize(
    "document, message",
    [
        ({"tables": []}, "non-empty list"),
        ({}, "non-empty list"),
        ({"tables": [minimal_table(table="")]}, "table must be a non-empty string"),
        ({"tables": [minimal_table(schema=3)]}, "schema must be a non-empty string"),
        ({"tables": [minimal_table(live_tuples=True)]}, "live_tuples must be an integer"),
        ({"tables": [minimal_table(dead_tuples=-1)]}, "dead_tuples must be greater"),
        ({"tables": [minimal_table(table_size_bytes="big")]}, "table_size_bytes must be an integer"),
        ({"tables": [minimal_table(reltuples=-5)]}, "reltuples must not be negative"),
        ({"settings": {"unknown": 1}, "tables": [minimal_table()]}, "unknown key"),
        (
            {"settings": {"autovacuum_vacuum_scale_factor": 3}, "tables": [minimal_table()]},
            "must be <= 1",
        ),
        (
            {"tables": [minimal_table(reloptions={"autovacuum_vacuum_scale_factor": "lots"})]},
            "not numeric",
        ),
        (
            {"tables": [minimal_table(), minimal_table()]},
            "duplicate table entry: public.orders",
        ),
        ({"tables": [{"schema": "public"}]}, "missing required field"),
    ],
)
def test_rejects_bad_documents(document, message):
    with pytest.raises(StatsError, match=message):
        parse_export(document)


def test_duplicate_allowed_across_schemas():
    export = parse_export(
        {"tables": [minimal_table(), minimal_table(schema="archive")]}
    )
    assert len(export.tables) == 2


def test_missing_file_is_a_stats_error(tmp_path):
    with pytest.raises(StatsError, match="cannot read"):
        load_export(tmp_path / "nope.json")


def test_invalid_json_is_a_stats_error(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(StatsError, match="not valid JSON"):
        load_export(path)


def test_unknown_fields_are_ignored():
    document = {"tables": [minimal_table(extra="ignored")], "captured_by": "psql"}
    export = parse_export(document)
    assert export.tables[0].table == "orders"


def test_example_file_is_serialisable():
    document = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    assert document["tables"][0]["table"] == "orders"
