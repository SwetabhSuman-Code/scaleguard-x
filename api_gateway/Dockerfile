# ================================================================
# ScaleGuard X — API Gateway
# Build context: project root (so lib/ is available)
# ================================================================
FROM python:3.11-slim

WORKDIR /app

# Install deps first (layer cache)
COPY api_gateway/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared lib
COPY lib/ ./lib/

# Copy service source
COPY api_gateway/ .

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
