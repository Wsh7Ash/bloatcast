from pathlib import Path

import pytest

from bloatcast.advise import MIN_THRESHOLD, quote_ident, recommend, recommend_all
from bloatcast.analyze import analyze
from bloatcast.model import load_export, parse_export

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "shop_stats.json"


def table(**overrides):
    row = {
        "schema": "public",
        "table": "t",
        "live_tuples": 80_000,
        "dead_tuples": 20_000,
        "reltuples": 80_000,
        "table_size_bytes": 1_048_576,
        "mod_since_analyze": 0,
    }
    row.update(overrides)
    return row


def only_finding(**overrides):
    result = analyze(parse_export({"tables": [table(**overrides)]}))
    return result, result.findings[0]


@pytest.fixture(scope="module")
def example():
    return analyze(load_export(EXAMPLE))


def recs_by_table(analysis):
    return {r.table: r for r in recommend_all(analysis)}


def test_scale_factor_recommendation_for_large_table(example):
    rec = recs_by_table(example)["public.orders"]
    assert rec.setting == "autovacuum_vacuum_scale_factor"
    assert "ALTER TABLE public.orders SET (autovacuum_vacuum_scale_factor = 0.04);" == rec.sql
    assert "instead of 210,050" in rec.note


def test_threshold_recommendation_for_small_table(example):
    rec = recs_by_table(example)["public.notifications"]
    assert rec.setting == "autovacuum_vacuum_threshold"
    assert rec.sql == "ALTER TABLE public.notifications SET (autovacuum_vacuum_threshold = 45);"
    assert "row threshold dominates" in rec.note


def test_recommendations_only_for_warn_and_above(example):
    recs = recs_by_table(example)
    assert set(recs) == {
        "public.orders",
        "public.events",
        "public.invoices",
        "public.products",
        "public.notifications",
        "public.users",
    }
    assert "public.audit_log" not in recs
    assert "public.sessions" not in recs


def test_no_recommendation_when_already_stricter():
    result, finding = only_finding(
        live_tuples=90_000,
        dead_tuples=10_000,
        reltuples=90_000,
        reloptions={"autovacuum_vacuum_scale_factor": "0.01", "autovacuum_vacuum_threshold": "10"},
    )
    assert recommend(finding, result.export.settings) is None


def test_no_recommendation_for_info_or_ok():
    result, finding = only_finding(live_tuples=10_000, dead_tuples=0, reltuples=10_000)
    assert finding.severity == "ok"
    assert recommend(finding, result.export.settings) is None
    result, finding = only_finding(
        live_tuples=10_000, dead_tuples=0, reltuples=10_000, mod_since_analyze=2000
    )
    assert finding.severity == "info"
    assert recommend(finding, result.export.settings) is None


def test_threshold_recommendation_never_below_minimum():
    result, finding = only_finding(live_tuples=10, dead_tuples=5, reltuples=10)
    rec = recommend(finding, result.export.settings)
    assert rec is not None
    threshold = int(rec.sql.rsplit("=", 1)[1].strip(" ;)"))
    assert threshold >= MIN_THRESHOLD


def test_sql_quotes_unsafe_identifiers():
    result, finding = only_finding(schema="Sales Data", table="Order Lines")
    rec = recommend(finding, result.export.settings)
    assert rec is not None
    assert 'ALTER TABLE "Sales Data"."Order Lines"' in rec.sql


def test_quote_ident():
    assert quote_ident("public") == "public"
    assert quote_ident("order") == "order"
    assert quote_ident("Order") == '"Order"'
    assert quote_ident('we"ird') == '"we""ird"'


def test_recommend_all_is_deterministic(example):
    first = [r.sql for r in recommend_all(example)]
    second = [r.sql for r in recommend_all(example)]
    assert first == second
    assert len(first) == 6
