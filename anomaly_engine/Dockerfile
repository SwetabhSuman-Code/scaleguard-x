# ================================================================
# ScaleGuard X — Anomaly Detection Engine
# Build context: project root (so lib/ is available)
# ================================================================
FROM python:3.11-slim

WORKDIR /app

COPY anomaly_engine/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY lib/ ./lib/
COPY anomaly_engine/ ./anomaly_engine/

CMD ["python", "main.py"]
