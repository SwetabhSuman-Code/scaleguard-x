"""Summarize Locust CSV artifacts and relevant scaling events into markdown."""

from __future__ import annotations

import csv
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
RESULT_PREFIX = Path(os.getenv("LOAD_TEST_PREFIX", "benchmarks/results/load_test"))
REPORT_PATH = Path(
    os.getenv(
        "LOAD_TEST_REPORT",
        f"benchmarks/results/LOAD_TEST_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.md",
    )
)
BATCH_SIZE = max(1, int(os.getenv("LOAD_TEST_BATCH_SIZE", "1")))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _run_command(args: list[str]) -> str:
    result = subprocess.run(
        args,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _test_window(history_rows: list[dict[str, str]]) -> tuple[datetime | None, datetime | None]:
    aggregated_rows = [
        row for row in history_rows if row["Name"] == "Aggregated" and row["Timestamp"]
    ]
    if not aggregated_rows:
        return None, None

    start_at = datetime.fromtimestamp(int(aggregated_rows[0]["Timestamp"]), tz=timezone.utc)
    end_at = datetime.fromtimestamp(int(aggregated_rows[-1]["Timestamp"]), tz=timezone.utc)
    return start_at, end_at


def _scaling_events(start_at: datetime | None, end_at: datetime | None) -> list[dict[str, str]]:
    filters = ["action <> 'no_change'", "prev_replicas <> new_replicas"]
    if start_at is not None:
        filters.append(f"triggered_at >= '{start_at.isoformat()}'")
    if end_at is not None:
        filters.append(f"triggered_at <= '{end_at.isoformat()}'")

    try:
        output = _run_command(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "postgres_db",
                "psql",
                "-U",
                os.getenv("POSTGRES_USER", "scaleguard"),
                "-d",
                os.getenv("POSTGRES_DB", "scaleguard"),
                "-t",
                "-A",
                "-F",
                "|",
                "-c",
                (
                    "SELECT triggered_at || '|' || action || '|' || prev_replicas || '|' || new_replicas || '|' || reason "
                    f"FROM scaling_events WHERE {' AND '.join(filters)} "
                    "ORDER BY triggered_at ASC LIMIT 20;"
                ),
            ]
        )
    except Exception:
        return []

    rows = []
    for line in output.splitlines():
        if not line.strip():
            continue
        triggered_at, action, prev_rep, new_rep, reason = line.split("|", 4)
        rows.append(
            {
                "triggered_at": triggered_at,
                "action": action,
                "prev_replicas": prev_rep,
                "new_replicas": new_rep,
                "reason": reason,
            }
        )
    return rows


def main() -> int:
    stats_path = ROOT / f"{RESULT_PREFIX}_stats.csv"
    history_path = ROOT / f"{RESULT_PREFIX}_stats_history.csv"

    if not stats_path.exists():
        print(f"Missing stats CSV: {stats_path}", file=sys.stderr)
        return 1

    stats_rows = _read_csv(stats_path)
    history_rows = _read_csv(history_path) if history_path.exists() else []
    aggregated = next((row for row in stats_rows if row["Name"] == "Aggregated"), None)
    if aggregated is None:
        print("Could not find aggregated Locust stats row.", file=sys.stderr)
        return 1

    peak_rps = 0.0
    peak_users = 0
    for row in history_rows:
        if row["Name"] == "Aggregated":
            peak_rps = max(peak_rps, float(row["Requests/s"] or 0.0))
            peak_users = max(peak_users, int(row["User Count"] or 0))

    start_at, end_at = _test_window(history_rows)
    scaling_rows = _scaling_events(start_at, end_at)
    estimated_metrics_ingested = 0

    report = [
        f"# Load Test Results - {datetime.now().strftime('%B %d, %Y')}",
        "",
        "## Summary",
        f"- Batch size: {BATCH_SIZE}",
        f"- Peak users: {peak_users}",
        f"- Total requests: {aggregated['Request Count']}",
        f"- Failures: {aggregated['Failure Count']}",
        f"- Average response time: {float(aggregated['Average Response Time']):.2f} ms",
        f"- P95 latency: {aggregated['95%']} ms",
        f"- P99 latency: {aggregated['99%']} ms",
        f"- Sustained throughput: {float(aggregated['Requests/s']):.2f} req/sec",
        f"- Peak throughput: {peak_rps:.2f} req/sec",
        "",
        "## Endpoints",
    ]

    for row in stats_rows:
        if row["Name"] == "Aggregated":
            continue
        if row["Type"] == "POST" and row["Name"] == "/api/metrics/bulk":
            estimated_metrics_ingested += int(row["Request Count"]) * BATCH_SIZE
        elif row["Type"] == "POST" and row["Name"] == "/api/metrics":
            estimated_metrics_ingested += int(row["Request Count"])

        report.append(
            f"- {row['Type']} {row['Name']}: {row['Request Count']} requests, "
            f"{row['Failure Count']} failures, p95 {row['95%']} ms, p99 {row['99%']} ms"
        )

    report.extend(
        [
            "",
            "## Pipeline Impact",
            f"- Estimated metrics ingested: {estimated_metrics_ingested}",
            "",
            "## Scaling Events",
        ]
    )

    if scaling_rows:
        for row in scaling_rows:
            report.append(
                f"- {row['triggered_at']}: {row['action']} {row['prev_replicas']} -> "
                f"{row['new_replicas']} ({row['reason']})"
            )
    else:
        report.append("- No scale transitions recorded during the test window.")

    output_path = ROOT / REPORT_PATH
    output_path.write_text("\n".join(report) + "\n", encoding="utf-8")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
