"""Turn findings into per-table autovacuum settings.

The recommendation targets autovacuum firing when a table is 5% dead. That is a
policy choice, not a PostgreSQL default: the point is to make the trigger
explicit and reachable for the tables that are actually dead-heavy.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .analyze import SEVERITY_ORDER, Analysis, Finding
from .model import effective_option

TARGET_DEAD_RATIO = 0.05
MIN_SCALE_FACTOR = 0.01
MIN_THRESHOLD = 10

_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_$]*$")


def quote_ident(name: str) -> str:
    if _IDENTIFIER.match(name):
        return name
    return '"' + name.replace('"', '""') + '"'


@dataclass(frozen=True)
class Recommendation:
    finding: Finding
    sql: str
    setting: str
    note: str

    @property
    def table(self) -> str:
        return self.finding.table.qualified


def recommend(finding: Finding, settings) -> Recommendation | None:
    """Return a setting change, or None when the table already meets the target."""
    if SEVERITY_ORDER[finding.severity] < SEVERITY_ORDER["warn"]:
        return None
    table = finding.table
    rows = max(table.row_estimate, 1.0)
    threshold, _ = effective_option(table, settings, "autovacuum_vacuum_threshold")
    scale, _ = effective_option(table, settings, "autovacuum_vacuum_scale_factor")
    target = TARGET_DEAD_RATIO

    if (threshold + scale * rows) / rows <= target:
        # The effective trigger already fires at or below the target ratio.
        return None

    factor = target - threshold / rows
    if factor >= MIN_SCALE_FACTOR:
        new_scale = math.floor(factor * 100) / 100
        if new_scale >= scale:
            return None
        trigger = int(math.floor(threshold + new_scale * rows))
        sql = (
            f"ALTER TABLE {quote_ident(table.schema)}.{quote_ident(table.table)} "
            f"SET (autovacuum_vacuum_scale_factor = {new_scale:.2f});"
        )
        note = (
            f"triggers at {trigger:,} dead tuples ({target:.0%} of ~{int(rows):,} rows) "
            f"instead of {finding.vacuum_trigger:,}"
        )
        return Recommendation(finding, sql, "autovacuum_vacuum_scale_factor", note)

    new_threshold = max(MIN_THRESHOLD, int(round(target * rows)))
    if new_threshold >= threshold:
        return None
    trigger = int(math.floor(new_threshold + scale * rows))
    sql = (
        f"ALTER TABLE {quote_ident(table.schema)}.{quote_ident(table.table)} "
        f"SET (autovacuum_vacuum_threshold = {new_threshold});"
    )
    note = (
        f"row threshold dominates on this small table; triggers at {trigger:,} dead tuples "
        f"instead of {finding.vacuum_trigger:,}"
    )
    return Recommendation(finding, sql, "autovacuum_vacuum_threshold", note)


def recommend_all(analysis: Analysis) -> tuple[Recommendation, ...]:
    out = []
    for finding in analysis.findings:
        rec = recommend(finding, analysis.export.settings)
        if rec is not None:
            out.append(rec)
    return tuple(out)
