# ================================================================
# ScaleGuard X — Worker Cluster
# Build context: project root (so lib/ is available)
# ================================================================
FROM python:3.11-slim

WORKDIR /app

COPY worker_cluster/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY lib/ ./lib/
COPY worker_cluster/ ./worker_cluster/

CMD ["python", "worker_cluster/worker.py"]
