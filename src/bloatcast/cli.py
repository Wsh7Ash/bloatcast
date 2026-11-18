"""Command line entry point for bloatcast."""

from __future__ import annotations

import argparse
import sys

from .advise import recommend_all
from .analyze import SEVERITY_ORDER, analyze
from .model import StatsError, load_export
from .render import render_json, render_text

SEVERITIES = ("ok", "info", "warn", "critical")
RULE_TEXT = """\
Severity legend (fixed, so a verdict means the same thing in every export)

  critical  past the autovacuum trigger AND at least 20% dead tuples
  warn      past the trigger, or at least 30% dead tuples
  info      at least 10% dead tuples, or rows changed past the analyze trigger
  ok        inside the trigger budget

Trigger arithmetic (PostgreSQL defaults, overridable per table via reloptions)

  autovacuum fires when dead tuples > autovacuum_vacuum_threshold
                                + autovacuum_vacuum_scale_factor * reltuples
  autoanalyze fires when modified rows > autovacuum_analyze_threshold
                                + autovacuum_analyze_scale_factor * reltuples

Recommendations target 5% dead tuples, using a per-table scale factor when
that is reachable and a lower row threshold on small tables where the 50-row
constant dominates the trigger.
"""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bloatcast", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("analyze", help="analyse a table-statistics export")
    run.add_argument("path", help="JSON export path (see docs/USAGE.md for the query)")
    run.add_argument("--json", action="store_true", help="machine-readable output")
    run.add_argument("--min-severity", choices=SEVERITIES, default="ok")
    run.add_argument("--top", type=int, default=None, help="show only the N highest-priority tables")
    run.add_argument("--no-advice", action="store_true", help="omit ALTER TABLE suggestions")
    run.add_argument(
        "--fail-on",
        choices=("none", "info", "warn", "critical"),
        default="none",
        help="exit 1 when a finding at this severity exists",
    )

    sub.add_parser("rules", help="print the severity legend and trigger arithmetic")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "rules":
        print(RULE_TEXT, end="")
        return 0

    if args.top is not None and args.top < 1:
        print("bloatcast: --top must be at least 1", file=sys.stderr)
        return 2
    try:
        export = load_export(args.path)
    except StatsError as exc:
        print(f"bloatcast: {exc}", file=sys.stderr)
        return 2

    analysis = analyze(export)
    recommendations = () if args.no_advice else recommend_all(analysis)
    renderer = render_json if args.json else render_text
    sys.stdout.write(
        renderer(analysis, recommendations, min_severity=args.min_severity, top=args.top)
    )

    if args.fail_on != "none":
        floor = SEVERITY_ORDER[args.fail_on]
        if any(SEVERITY_ORDER[f.severity] >= floor for f in analysis.findings):
            return 1
    return 0
