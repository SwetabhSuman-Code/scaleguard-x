# ================================================================
# ScaleGuard X — Prediction Engine
# Build context: project root (so lib/ is available)
# ================================================================
FROM python:3.11-slim

WORKDIR /app

# statsmodels needs gcc to compile native extensions
RUN apt-get update && apt-get install -y --no-install-recommends gcc g++ && rm -rf /var/lib/apt/lists/*

COPY prediction_engine/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY lib/ ./lib/
COPY prediction_engine/ .

CMD ["python", "main.py"]
