"""Classify tables by dead-tuple pressure and estimate reclaimable space."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping

from .model import StatsExport, TableStats, effective_option

SEVERITY_ORDER: dict[str, int] = {"ok": 0, "info": 1, "warn": 2, "critical": 3}
CRITICAL_DEAD_RATIO = 0.20
WARN_DEAD_RATIO = 0.30
INFO_DEAD_RATIO = 0.10


@dataclass(frozen=True)
class Finding:
    table: TableStats
    severity: str
    code: str
    dead_ratio: float
    vacuum_trigger: int
    analyze_trigger: int
    reclaimable_bytes: int
    reasons: tuple[str, ...]

    @property
    def vacuum_overdue(self) -> bool:
        return self.table.total_tuples > 0 and self.table.dead_tuples >= self.vacuum_trigger


@dataclass(frozen=True)
class Analysis:
    export: StatsExport
    findings: tuple[Finding, ...]

    @property
    def counts(self) -> dict[str, int]:
        counts = {name: 0 for name in SEVERITY_ORDER}
        for finding in self.findings:
            counts[finding.severity] += 1
        return counts

    @property
    def reclaimable_bytes(self) -> int:
        return sum(f.reclaimable_bytes for f in self.findings if f.severity != "ok")

    def at_or_above(self, severity: str) -> tuple[Finding, ...]:
        floor = SEVERITY_ORDER[severity]
        return tuple(f for f in self.findings if SEVERITY_ORDER[f.severity] >= floor)


def vacuum_trigger(table: TableStats, settings: Mapping[str, float]) -> int:
    threshold, _ = effective_option(table, settings, "autovacuum_vacuum_threshold")
    scale, _ = effective_option(table, settings, "autovacuum_vacuum_scale_factor")
    return int(math.floor(threshold + scale * table.row_estimate))


def analyze_trigger(table: TableStats, settings: Mapping[str, float]) -> int:
    threshold, _ = effective_option(table, settings, "autovacuum_analyze_threshold")
    scale, _ = effective_option(table, settings, "autovacuum_analyze_scale_factor")
    return int(math.floor(threshold + scale * table.row_estimate))


def dead_ratio(table: TableStats) -> float:
    if table.total_tuples == 0:
        return 0.0
    return table.dead_tuples / table.total_tuples


def reclaimable_bytes(table: TableStats) -> int:
    ratio = dead_ratio(table)
    if ratio == 0:
        return 0
    return int(round(table.size_bytes * ratio))


def _reasons(table: TableStats, trigger: int, analyze_at: int, ratio: float) -> tuple[str, ...]:
    reasons: list[str] = []
    if table.dead_tuples >= trigger and table.total_tuples:
        reasons.append(
            f"dead tuples {table.dead_tuples:,} reached the autovacuum trigger {trigger:,}"
        )
    elif table.dead_tuples:
        reasons.append(
            f"dead tuples {table.dead_tuples:,} are below the trigger {trigger:,}"
        )
    if ratio >= INFO_DEAD_RATIO:
        reasons.append(f"{ratio:.1%} of tuples are dead")
    if table.mod_since_analyze >= analyze_at and table.total_tuples:
        reasons.append(
            f"{table.mod_since_analyze:,} rows changed since the last analyze "
            f"(threshold {analyze_at:,})"
        )
    last = table.last_autovacuum or table.last_vacuum
    if last:
        reasons.append(f"last vacuum recorded at {last}")
    return tuple(reasons)


def _classify(table: TableStats, trigger: int, analyze_at: int, ratio: float) -> tuple[str, str]:
    if table.total_tuples == 0:
        return "ok", "empty-table"
    overdue = table.dead_tuples >= trigger
    if overdue and ratio >= CRITICAL_DEAD_RATIO:
        return "critical", "vacuum-critical"
    if overdue:
        return "warn", "vacuum-overdue"
    if ratio >= WARN_DEAD_RATIO:
        return "warn", "dead-space"
    if ratio >= INFO_DEAD_RATIO:
        return "info", "dead-space"
    if table.mod_since_analyze >= analyze_at:
        return "info", "analyze-overdue"
    return "ok", "within-threshold"


def analyze(export: StatsExport) -> Analysis:
    findings: list[Finding] = []
    for table in export.tables:
        trigger = vacuum_trigger(table, export.settings)
        analyze_at = analyze_trigger(table, export.settings)
        ratio = dead_ratio(table)
        severity, code = _classify(table, trigger, analyze_at, ratio)
        findings.append(
            Finding(
                table=table,
                severity=severity,
                code=code,
                dead_ratio=ratio,
                vacuum_trigger=trigger,
                analyze_trigger=analyze_at,
                reclaimable_bytes=reclaimable_bytes(table),
                reasons=_reasons(table, trigger, analyze_at, ratio),
            )
        )
    findings.sort(
        key=lambda f: (-SEVERITY_ORDER[f.severity], -f.reclaimable_bytes, f.table.qualified)
    )
    return Analysis(export=export, findings=tuple(findings))
