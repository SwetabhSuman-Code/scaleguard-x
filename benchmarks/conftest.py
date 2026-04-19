"""
Pytest configuration and fixtures for benchmark suite
"""

import pytest
import asyncio
import httpx
import json
from datetime import datetime
import logging


# Enable asyncio for all tests
@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def api_client():
    """HTTP client for making API requests"""
    return httpx.Client(base_url="http://localhost:8000", timeout=30.0, verify=False)


@pytest.fixture
async def async_api_client():
    """Async HTTP client for concurrent requests"""
    async with httpx.AsyncClient(
        base_url="http://localhost:8000", timeout=30.0, verify=False
    ) as client:
        yield client


@pytest.fixture
def benchmark_results_dir():
    """Directory for benchmark results"""
    import os

    results_dir = "benchmarks/results"
    os.makedirs(results_dir, exist_ok=True)
    return results_dir


@pytest.fixture
def logger():
    """Configured logger for benchmark tests"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    return logging.getLogger("benchmarks")


@pytest.fixture
def save_benchmark_result(benchmark_results_dir):
    """Helper to save benchmark results to JSON"""

    def _save(name: str, data: dict):
        filepath = f"{benchmark_results_dir}/{name}.json"
        with open(filepath, "w") as f:
            # Add metadata
            data["_metadata"] = {
                "timestamp": datetime.utcnow().isoformat(),
                "test_name": name,
                "version": "1.0",
            }
            json.dump(data, f, indent=2, default=str)
        return filepath

    return _save
