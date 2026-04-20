"""Validate that metrics sent through the API reach Postgres and drain from Redis."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE_URL = os.getenv("SCALEGUARD_BASE_URL", "http://localhost:8000")
DEFAULT_STREAM_KEY = os.getenv("METRICS_STREAM_KEY", "metrics_stream")
DEFAULT_METRIC_COUNT = int(os.getenv("VALIDATION_METRIC_COUNT", "100"))
DEFAULT_WAIT_TIMEOUT = int(os.getenv("VALIDATION_WAIT_TIMEOUT_SECONDS", "20"))


def _load_dotenv() -> dict[str, str]:
    env = {}
    env_path = ROOT / ".env"
    if not env_path.exists():
        return env

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def _http_json(method: str, url: str, payload: dict | None = None) -> dict:
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=10) as response:
        body = response.read().decode("utf-8")
        return json.loads(body) if body else {}


def _run_command(args: list[str]) -> str:
    result = subprocess.run(
        args,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _get_metric_count(dotenv: dict[str, str], node_prefix: str | None = None) -> int:
    user = os.getenv("POSTGRES_USER", dotenv.get("POSTGRES_USER", "scaleguard"))
    database = os.getenv("POSTGRES_DB", dotenv.get("POSTGRES_DB", "scaleguard"))
    query = "SELECT COUNT(*) FROM metrics;"
    if node_prefix:
        query = f"SELECT COUNT(*) FROM metrics WHERE node_id LIKE '{node_prefix}%';"
    output = _run_command(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "postgres_db",
            "psql",
            "-U",
            user,
            "-d",
            database,
            "-t",
            "-A",
            "-c",
            query,
        ]
    )
    return int(output.splitlines()[-1])


def _get_redis_depth() -> int:
    output = _run_command(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "redis_queue",
            "redis-cli",
            "XLEN",
            DEFAULT_STREAM_KEY,
        ]
    )
    return int(output.splitlines()[-1])


def _send_metrics(base_url: str, count: int, run_prefix: str) -> None:
    for index in range(count):
        payload = {
            "node_id": f"{run_prefix}{index}",
            "cpu": 50.0 + index,
            "memory": 60.0,
            "latency_ms": 100.0,
            "rps": 200.0,
            "disk_usage": 40.0,
        }
        _http_json("POST", f"{base_url}/api/metrics", payload)


def main() -> int:
    dotenv = _load_dotenv()
    base_url = DEFAULT_BASE_URL.rstrip("/")
    run_prefix = f"validator-{int(time.time())}-"

    print("Checking API health...")
    health = _http_json("GET", f"{base_url}/health")
    print(f"Health response: {health}")

    start_count = _get_metric_count(dotenv, run_prefix)
    start_depth = _get_redis_depth()
    print(f"Starting metric count for {run_prefix}*: {start_count}")
    print(f"Starting Redis stream depth: {start_depth}")

    print(f"Sending {DEFAULT_METRIC_COUNT} metrics through the API...")
    _send_metrics(base_url, DEFAULT_METRIC_COUNT, run_prefix)

    deadline = time.time() + DEFAULT_WAIT_TIMEOUT
    end_count = start_count
    while time.time() < deadline:
        end_count = _get_metric_count(dotenv, run_prefix)
        if end_count - start_count >= int(DEFAULT_METRIC_COUNT * 0.95):
            break
        time.sleep(1)

    end_depth = _get_redis_depth()
    ingested = end_count - start_count
    success_rate = ingested / DEFAULT_METRIC_COUNT

    print(f"Ending metric count for {run_prefix}*: {end_count}")
    print(f"Ending Redis stream depth: {end_depth}")
    print(f"Ingested metrics: {ingested}/{DEFAULT_METRIC_COUNT} ({success_rate:.1%})")

    if ingested < int(DEFAULT_METRIC_COUNT * 0.95):
        print("Pipeline validation failed: too many metrics were lost.", file=sys.stderr)
        return 1

    if end_depth > start_depth + DEFAULT_METRIC_COUNT:
        print("Pipeline validation failed: Redis queue depth is still growing.", file=sys.stderr)
        return 1

    print("Pipeline validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
