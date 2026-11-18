from pathlib import Path

import pytest

from bloatcast.analyze import (
    analyze,
    analyze_trigger,
    dead_ratio,
    reclaimable_bytes,
    vacuum_trigger,
)
from bloatcast.model import load_export, parse_export

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "shop_stats.json"


def table(**overrides):
    row = {
        "schema": "public",
        "table": "t",
        "live_tuples": 10_000,
        "dead_tuples": 0,
        "reltuples": 10_000,
        "table_size_bytes": 1_048_576,
        "mod_since_analyze": 0,
    }
    row.update(overrides)
    return row


def analysis_for(**overrides):
    return analyze(parse_export({"tables": [table(**overrides)]}))


@pytest.fixture(scope="module")
def example():
    return analyze(load_export(EXAMPLE))


def by_name(analysis):
    return {f.table.table: f for f in analysis.findings}


def test_vacuum_trigger_uses_global_defaults():
    export = load_export(EXAMPLE)
    sessions = next(t for t in export.tables if t.table == "sessions")
    assert vacuum_trigger(sessions, export.settings) == 2_400_050


def test_vacuum_trigger_respects_table_reloption():
    export = load_export(EXAMPLE)
    orders = next(t for t in export.tables if t.table == "orders")
    assert vacuum_trigger(orders, export.settings) == 210_050


def test_analyze_trigger():
    export = load_export(EXAMPLE)
    sessions = next(t for t in export.tables if t.table == "sessions")
    assert analyze_trigger(sessions, export.settings) == 1_200_050


def test_dead_ratio_and_reclaimable():
    export = load_export(EXAMPLE)
    invoices = next(t for t in export.tables if t.table == "invoices")
    assert dead_ratio(invoices) == pytest.approx(0.2)
    assert reclaimable_bytes(invoices) == 67_108_864


def test_empty_table_has_zero_ratio_and_no_reclaimable():
    result = analysis_for(live_tuples=0, dead_tuples=0, reltuples=0)
    finding = result.findings[0]
    assert finding.dead_ratio == 0
    assert finding.reclaimable_bytes == 0
    assert finding.severity == "ok"
    assert finding.code == "empty-table"
    assert finding.reasons == ()


def test_past_trigger_and_high_ratio_is_critical():
    result = analysis_for(live_tuples=80_000, dead_tuples=20_000, reltuples=80_000)
    finding = result.findings[0]
    assert finding.severity == "critical"
    assert finding.code == "vacuum-critical"
    assert finding.vacuum_trigger == 16_050
    assert finding.vacuum_overdue is True


def test_past_trigger_with_low_ratio_is_warn():
    result = analysis_for(live_tuples=100_000, dead_tuples=21_000, reltuples=100_000)
    finding = result.findings[0]
    assert finding.severity == "warn"
    assert finding.code == "vacuum-overdue"


def test_below_trigger_but_hi_ratio_is_warn():
    result = analysis_for(
        live_tuples=100_000,
        dead_tuples=16_000,
        reltuples=500_000,
        reloptions={"autovacuum_vacuum_scale_factor": "1"},
    )
    finding = result.findings[0]
    assert finding.vacuum_overdue is False
    assert finding.dead_ratio > 0.13
    assert finding.code == "dead-space"
    assert finding.severity in {"info", "warn"}


def test_dead_space_above_30_percent_without_overdue_is_warn():
    result = analysis_for(
        live_tuples=70_000,
        dead_tuples=30_000,
        reltuples=1_000_000,
        reloptions={"autovacuum_vacuum_scale_factor": "1"},
    )
    assert result.findings[0].severity == "warn"
    assert result.findings[0].code == "dead-space"


def test_analyze_overdue_is_info():
    result = analysis_for(mod_since_analyze=1200)
    finding = result.findings[0]
    assert finding.severity == "info"
    assert finding.code == "analyze-overdue"
    assert any("analyze" in reason for reason in finding.reasons)


def test_within_threshold_is_ok():
    result = analysis_for()
    assert result.findings[0].severity == "ok"
    assert result.findings[0].code == "within-threshold"


def test_example_classification(example):
    findings = by_name(example)
    assert findings["orders"].severity == "critical"
    assert findings["events"].severity == "critical"
    assert findings["invoices"].severity == "critical"
    assert findings["products"].severity == "critical"
    assert findings["notifications"].severity == "critical"
    assert findings["users"].severity == "warn"
    assert findings["audit_log"].severity == "info"
    assert findings["audit_log"].code == "analyze-overdue"
    assert findings["sessions"].severity == "ok"
    assert findings["imports"].severity == "ok"
    assert findings["ledger_entries"].severity == "ok"


def test_example_counts_and_reclaimable(example):
    assert example.counts == {"ok": 3, "info": 1, "warn": 1, "critical": 5}
    assert example.reclaimable_bytes == sum(
        f.reclaimable_bytes for f in example.findings if f.severity != "ok"
    )
    assert example.reclaimable_bytes > 2_900_000_000


def test_findings_sorted_by_severity_then_reclaimable(example):
    severities = [f.severity for f in example.findings]
    assert severities == sorted(
        severities, key=lambda s: {"critical": 0, "warn": 1, "info": 2, "ok": 3}[s]
    )
    assert example.findings[0].table.table == "events"


def test_at_or_above(example):
    labels = {f.table.table for f in example.at_or_above("warn")}
    assert labels == {"events", "orders", "invoices", "products", "notifications", "users"}
    assert len(example.at_or_above("ok")) == 10
