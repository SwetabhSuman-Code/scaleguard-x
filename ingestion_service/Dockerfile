# ================================================================
# ScaleGuard X — Ingestion Service
# Build context: project root (so lib/ is available)
# ================================================================
FROM python:3.11-slim

WORKDIR /app

COPY ingestion_service/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY lib/ ./lib/
COPY ingestion_service/ ./ingestion_service/

CMD ["python", "ingestion_service/main.py"]
