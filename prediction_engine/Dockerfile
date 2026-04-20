# ================================================================
# ScaleGuard X — Prediction Engine
# Build context: project root (so lib/ is available)
# ================================================================
FROM python:3.11-slim

WORKDIR /app

# statsmodels needs gcc to compile native extensions
RUN apt-get update && apt-get install -y --no-install-recommends gcc g++ && rm -rf /var/lib/apt/lists/*

ARG INSTALL_ML_EXTRAS=false

COPY prediction_engine/requirements.txt ./requirements.txt
COPY prediction_engine/requirements-ml.txt ./requirements-ml.txt
RUN pip install --no-cache-dir -r requirements.txt
RUN if [ "$INSTALL_ML_EXTRAS" = "true" ]; then pip install --no-cache-dir -r requirements-ml.txt; fi

COPY lib/ ./lib/
COPY prediction_engine/ ./prediction_engine/

CMD ["python", "prediction_engine/main.py"]
