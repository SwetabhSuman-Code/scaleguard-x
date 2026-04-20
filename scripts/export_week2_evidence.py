"""Export week-2 load-test evidence from Locust CSVs and scaling events."""

from __future__ import annotations

import csv
import html
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "benchmarks" / "results"
IMAGES = ROOT / "docs" / "images"
SCALING_CSV = RESULTS / "week2_scaling_events.csv"

LOAD_TESTS = {
    "gradual": RESULTS / "load_test_gradual_2026-04-19_2350_stats_history.csv",
    "spike": RESULTS / "load_test_spike_2026-04-20_0006_stats_history.csv",
}


def _run(args: list[str]) -> str:
    result = subprocess.run(args, cwd=ROOT, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _read_history(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [row for row in rows if row.get("Name") == "Aggregated" and row.get("Timestamp")]


def _export_scaling_events() -> None:
    query = (
        "COPY ("
        "SELECT triggered_at, action, prev_replicas, new_replicas, reason "
        "FROM scaling_events "
        "WHERE triggered_at >= '2026-04-19T18:19:00+00:00' "
        "AND triggered_at <= '2026-04-19T18:38:00+00:00' "
        "AND action <> 'no_change' "
        "ORDER BY triggered_at ASC"
        ") TO STDOUT CSV HEADER"
    )
    output = _run(
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
            "-c",
            query,
        ]
    )
    SCALING_CSV.write_text(output + "\n", encoding="utf-8")


def _line_chart_svg(title: str, rows: list[dict[str, str]], value_key: str, output: Path) -> None:
    width, height = 900, 360
    left, right, top, bottom = 70, 25, 45, 55
    plot_width = width - left - right
    plot_height = height - top - bottom

    values = [float(row.get(value_key) or 0.0) for row in rows]
    users = [float(row.get("User Count") or 0.0) for row in rows]
    if not values:
        values = [0.0]
        users = [0.0]

    max_value = max(max(values), 1.0)
    max_users = max(max(users), 1.0)

    def point(index: int, value: float, max_y: float) -> tuple[float, float]:
        x = left + (index / max(1, len(values) - 1)) * plot_width
        y = top + plot_height - (value / max_y) * plot_height
        return x, y

    rps_points = " ".join(f"{x:.1f},{y:.1f}" for x, y in [point(i, value, max_value) for i, value in enumerate(values)])
    user_points = " ".join(
        f"{x:.1f},{y:.1f}" for x, y in [point(i, value, max_users) for i, value in enumerate(users)]
    )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="100%" height="100%" fill="#fbfaf7"/>
  <text x="{left}" y="28" font-family="Georgia, serif" font-size="22" fill="#2f2a1f">{html.escape(title)}</text>
  <line x1="{left}" y1="{top + plot_height}" x2="{width - right}" y2="{top + plot_height}" stroke="#8d8575"/>
  <line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" stroke="#8d8575"/>
  <text x="{left}" y="{height - 18}" font-family="Verdana, sans-serif" font-size="12" fill="#5f574a">time during run</text>
  <text x="12" y="{top + 12}" font-family="Verdana, sans-serif" font-size="12" fill="#5f574a">req/sec</text>
  <polyline points="{rps_points}" fill="none" stroke="#0c6b58" stroke-width="3"/>
  <polyline points="{user_points}" fill="none" stroke="#c76d2c" stroke-width="2" stroke-dasharray="6 5" opacity="0.8"/>
  <text x="{width - 220}" y="28" font-family="Verdana, sans-serif" font-size="12" fill="#0c6b58">solid: requests/sec</text>
  <text x="{width - 220}" y="46" font-family="Verdana, sans-serif" font-size="12" fill="#c76d2c">dashed: user ramp</text>
  <text x="{left}" y="{top + plot_height + 20}" font-family="Verdana, sans-serif" font-size="12" fill="#5f574a">peak rps: {max_value:.2f}</text>
</svg>
"""
    output.write_text(svg, encoding="utf-8")


def _autoscaling_svg() -> None:
    if not SCALING_CSV.exists():
        return

    with SCALING_CSV.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    width, height = 900, 320
    left, top, row_gap = 70, 65, 34
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#fbfaf7"/>',
        f'<text x="{left}" y="32" font-family="Georgia, serif" font-size="22" fill="#2f2a1f">Week 2 Autoscaling Timeline</text>',
    ]

    for index, row in enumerate(rows[:7]):
        y = top + index * row_gap
        action_color = "#0c6b58" if row["action"] == "scale_up" else "#8d4e21"
        label = f'{row["triggered_at"]}: {row["action"]} {row["prev_replicas"]} -> {row["new_replicas"]}'
        lines.extend(
            [
                f'<circle cx="{left}" cy="{y}" r="7" fill="{action_color}"/>',
                f'<text x="{left + 22}" y="{y + 5}" font-family="Verdana, sans-serif" font-size="13" fill="#2f2a1f">{html.escape(label)}</text>',
            ]
        )

    lines.append("</svg>")
    (IMAGES / "week2_autoscaling_timeline.svg").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    IMAGES.mkdir(parents=True, exist_ok=True)
    _export_scaling_events()

    for name, path in LOAD_TESTS.items():
        rows = _read_history(path)
        _line_chart_svg(
            f"Week 2 {name.title()} Load Test",
            rows,
            "Requests/s",
            IMAGES / f"week2_{name}_requests_per_second.svg",
        )

    _autoscaling_svg()
    print(f"wrote {SCALING_CSV}")
    print(f"wrote {IMAGES / 'week2_gradual_requests_per_second.svg'}")
    print(f"wrote {IMAGES / 'week2_spike_requests_per_second.svg'}")
    print(f"wrote {IMAGES / 'week2_autoscaling_timeline.svg'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
