"""Render an analysis as text or JSON."""

from __future__ import annotations

import json
from typing import Iterable

from .advise import Recommendation
from .analyze import SEVERITY_ORDER, Analysis, Finding


def human_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            if unit == "B":
                return f"{int(size)} B"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{value} B"


def _settings_line(analysis: Analysis) -> str:
    settings = analysis.export.settings
    return (
        f"global trigger {settings['autovacuum_vacuum_threshold']:.0f} + "
        f"{settings['autovacuum_vacuum_scale_factor']:.2f} x rows"
    )


def render_text(
    analysis: Analysis,
    recommendations: Iterable[Recommendation] = (),
    *,
    min_severity: str = "ok",
    top: int | None = None,
) -> str:
    floor = SEVERITY_ORDER[min_severity]
    findings = [f for f in analysis.findings if SEVERITY_ORDER[f.severity] >= floor]
    if top is not None:
        findings = findings[:top]
    by_table = {rec.table: rec for rec in recommendations}

    lines = [
        "bloatcast - vacuum pressure report",
        f"captured {analysis.export.captured_at or 'unknown'} | "
        f"{len(analysis.export.tables)} tables | {_settings_line(analysis)}",
        "",
    ]
    if not findings:
        lines.append(f"no tables at or above severity {min_severity}")
    for finding in findings:
        table = finding.table
        lines.append(
            f"{finding.severity.upper():8} {table.qualified:<34} "
            f"{finding.dead_ratio:6.1%} dead | {human_bytes(finding.reclaimable_bytes):>9} reclaimable"
        )
        lines.append(
            f"         rows live {table.live_tuples:,} / dead {table.dead_tuples:,} | "
            f"trigger {finding.vacuum_trigger:,} | size {human_bytes(table.size_bytes)}"
        )
        for reason in finding.reasons:
            lines.append(f"         - {reason}")
        rec = by_table.get(table.qualified)
        if rec is not None:
            lines.append(f"         fix {rec.sql}")
            lines.append(f"             {rec.note}")
        lines.append("")

    counts = analysis.counts
    lines.append(
        f"summary: {counts['critical']} critical, {counts['warn']} warn, "
        f"{counts['info']} info, {counts['ok']} ok | "
        f"~{human_bytes(analysis.reclaimable_bytes)} estimated reclaimable"
    )
    lines.append(
        "note: ratios come from pg_stat_user_tables estimates; VACUUM makes space reusable, "
        "it does not return it to the filesystem (VACUUM FULL / pg_repack do)."
    )
    return "\n".join(lines) + "\n"


def _finding_json(finding: Finding) -> dict:
    table = finding.table
    return {
        "schema": table.schema,
        "table": table.table,
        "severity": finding.severity,
        "code": finding.code,
        "dead_ratio": round(finding.dead_ratio, 6),
        "live_tuples": table.live_tuples,
        "dead_tuples": table.dead_tuples,
        "reltuples": table.reltuples,
        "size_bytes": table.size_bytes,
        "vacuum_trigger": finding.vacuum_trigger,
        "analyze_trigger": finding.analyze_trigger,
        "reclaimable_bytes": finding.reclaimable_bytes,
        "reasons": list(finding.reasons),
    }


def render_json(
    analysis: Analysis,
    recommendations: Iterable[Recommendation] = (),
    *,
    min_severity: str = "ok",
    top: int | None = None,
) -> str:
    floor = SEVERITY_ORDER[min_severity]
    findings = [f for f in analysis.findings if SEVERITY_ORDER[f.severity] >= floor]
    if top is not None:
        findings = findings[:top]
    kept = {f.table.qualified for f in findings}
    payload = {
        "captured_at": analysis.export.captured_at,
        "settings": dict(analysis.export.settings),
        "summary": {
            "counts": analysis.counts,
            "tables": len(analysis.export.tables),
            "reclaimable_bytes": analysis.reclaimable_bytes,
        },
        "findings": [_finding_json(f) for f in findings],
        "recommendations": [
            {"table": r.table, "setting": r.setting, "sql": r.sql, "note": r.note}
            for r in recommendations
            if r.table in kept
        ],
    }
    return json.dumps(payload, indent=2) + "\n"
