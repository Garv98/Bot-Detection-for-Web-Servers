# FastAPI serving image for the bot-detection API.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install only what the API runtime needs (Spark/Java not required to serve).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# The API container does not need pyspark; install the serving subset.
RUN pip install \
        "fastapi>=0.110" "uvicorn[standard]>=0.27" "slowapi>=0.1.9" \
        "pydantic>=2.0" "scikit-learn>=1.3" "joblib>=1.3" \
        "pandas>=2.0" "numpy>=1.24" "happybase>=1.2.0" "duckdb>=0.10"

COPY . .

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=5 --start-period=20s \
    CMD curl -fsS http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8000"]
