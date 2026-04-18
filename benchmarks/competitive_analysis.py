"""
Generate an honest comparison table using local benchmark artifacts.

This script does not pretend to benchmark third-party tools automatically.
Instead, it combines measured ScaleGuard results with external comparison slots
that teams can fill in after running equivalent tests against other products.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


RESULTS_DIR = Path(__file__).resolve().parent / "results"


@dataclass
class ComparisonRow:
    metric: str
    scaleguard: str
    kubernetes_hpa: str
    datadog: str
    notes: str


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text())


def build_rows() -> list[ComparisonRow]:
    health = _load_json(RESULTS_DIR / "latency_health_endpoint.json")
    throughput = _load_json(RESULTS_DIR / "throughput_1k_metrics_per_sec.json")
    memory = _load_json(RESULTS_DIR / "memory_at_rest.json")

    scaleguard_health = "pending"
    if health:
        scaleguard_health = f"p99 {health['p99_ms']} ms (/health)"

    scaleguard_throughput = "pending rerun"
    if throughput and throughput.get("success"):
        scaleguard_throughput = f"{throughput['achieved_rps']} metrics/sec"
    elif throughput:
        scaleguard_throughput = "invalid run recorded"

    scaleguard_memory = "pending"
    if memory:
        peak = memory["profile"]["memory"]["peak_mb"]
        scaleguard_memory = f"{peak:.1f} MB idle process peak"

    return [
        ComparisonRow(
            metric="Health latency",
            scaleguard=scaleguard_health,
            kubernetes_hpa="not comparable directly",
            datadog="vendor-managed / out of repo scope",
            notes="Use the same probe path and region before comparing.",
        ),
        ComparisonRow(
            metric="Metric ingestion throughput",
            scaleguard=scaleguard_throughput,
            kubernetes_hpa="needs external benchmark",
            datadog="needs external benchmark",
            notes="The repo now exposes POST /api/metrics; rerun the load suite before publishing numbers.",
        ),
        ComparisonRow(
            metric="Idle memory footprint",
            scaleguard=scaleguard_memory,
            kubernetes_hpa="controller-managed",
            datadog="agent-specific",
            notes="Measure equivalent single-node footprints before comparing.",
        ),
        ComparisonRow(
            metric="Customization",
            scaleguard="full source access",
            kubernetes_hpa="controller config only",
            datadog="limited managed workflows",
            notes="This is a qualitative comparison, not a benchmark.",
        ),
    ]


def render_markdown(rows: list[ComparisonRow]) -> str:
    lines = [
        "# Competitive Analysis",
        "",
        "| Metric | ScaleGuard X | Kubernetes HPA | Datadog | Notes |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row.metric} | {row.scaleguard} | {row.kubernetes_hpa} | {row.datadog} | {row.notes} |"
        )
    lines.append("")
    lines.append(
        "External tool columns are placeholders until equivalent tests are run in matching environments."
    )
    return "\n".join(lines)


def main() -> None:
    rows = build_rows()
    print(render_markdown(rows))


if __name__ == "__main__":
    main()
