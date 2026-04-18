# ================================================================
# ScaleGuard X — Autoscaler
# Build context: project root (so lib/ is available)
# ================================================================
FROM python:3.11-slim

WORKDIR /app

COPY autoscaler/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY lib/ ./lib/
COPY autoscaler/ .

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import os; os.getpid()"

CMD ["python", "main.py"]
