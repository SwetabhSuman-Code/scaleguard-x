# ================================================================
# ScaleGuard X — Metrics Agent
# Build context: project root (so lib/ is available)
# ================================================================
FROM python:3.11-slim

WORKDIR /app

COPY metrics_agent/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY lib/ ./lib/
COPY metrics_agent/ .

CMD ["python", "agent.py"]
