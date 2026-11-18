import json
from pathlib import Path

import pytest

from bloatcast.cli import main

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = str(ROOT / "examples" / "shop_stats.json")


def clean_export(tmp_path):
    path = tmp_path / "clean.json"
    path.write_text(
        json.dumps(
            {
                "tables": [
                    {
                        "schema": "public",
                        "table": "small",
                        "live_tuples": 1000,
                        "dead_tuples": 0,
                        "reltuples": 1000,
                        "table_size_bytes": 65536,
                        "mod_since_analyze": 0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return str(path)


def test_text_report(capsys):
    assert main(["analyze", EXAMPLE]) == 0
    out = capsys.readouterr().out
    assert out.startswith("bloatcast - vacuum pressure report")
    assert "captured 2026-11-18T09:00:00Z | 10 tables" in out
    assert "CRITICAL public.events" in out
    assert "WARN     public.users" in out
    assert "summary: 5 critical, 1 warn, 1 info, 3 ok" in out
    assert "ALTER TABLE public.notifications SET" in out


def test_json_report(capsys):
    assert main(["analyze", EXAMPLE, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["counts"]["critical"] == 5
    assert len(payload["findings"]) == 10
    assert len(payload["recommendations"]) == 6
    first = payload["findings"][0]
    assert first["table"] == "events"
    assert first["severity"] == "critical"
    assert first["reclaimable_bytes"] > 0
    assert payload["findings"][0]["dead_ratio"] == round(9_500_000 / 39_500_000, 6)


def test_min_severity_filters(capsys):
    assert main(["analyze", EXAMPLE, "--min-severity", "critical"]) == 0
    out = capsys.readouterr().out
    assert "public.users" not in out
    assert "public.sessions" not in out
    assert "CRITICAL public.orders" in out


def test_top_limits_output(capsys):
    assert main(["analyze", EXAMPLE, "--top", "2"]) == 0
    out = capsys.readouterr().out
    assert "CRITICAL public.events" in out
    assert "public.notifications" not in out


def test_no_advice(capsys):
    assert main(["analyze", EXAMPLE, "--no-advice"]) == 0
    assert "fix " not in capsys.readouterr().out


def test_gate_fails_on_warn(capsys):
    assert main(["analyze", EXAMPLE, "--fail-on", "warn"]) == 1


def test_gate_fails_on_critical(capsys):
    assert main(["analyze", EXAMPLE, "--fail-on", "critical"]) == 1


def test_gate_passes_when_clean(tmp_path, capsys):
    assert main(["analyze", clean_export(tmp_path), "--fail-on", "critical"]) == 0
    assert "1 tables" in capsys.readouterr().out


def test_gate_none_never_fails(capsys):
    assert main(["analyze", EXAMPLE, "--fail-on", "none"]) == 0


def test_missing_file(tmp_path, capsys):
    assert main(["analyze", str(tmp_path / "missing.json")]) == 2
    assert "cannot read" in capsys.readouterr().err


def test_invalid_json(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text("{", encoding="utf-8")
    assert main(["analyze", str(path)]) == 2
    assert "not valid JSON" in capsys.readouterr().err


def test_invalid_export(tmp_path, capsys):
    path = tmp_path / "empty.json"
    path.write_text('{"tables": []}', encoding="utf-8")
    assert main(["analyze", str(path)]) == 2
    assert "non-empty list" in capsys.readouterr().err


def test_top_must_be_positive(capsys):
    assert main(["analyze", EXAMPLE, "--top", "0"]) == 2
    assert "--top must be at least 1" in capsys.readouterr().err


def test_rules(capsys):
    assert main(["rules"]) == 0
    out = capsys.readouterr().out
    assert "Severity legend" in out
    assert "autovacuum_vacuum_scale_factor" in out
