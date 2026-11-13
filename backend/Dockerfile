FROM python:3.11-slim

WORKDIR /app

# curl is only for the HEALTHCHECK below. Every Python dependency ships as a
# wheel, so no compiler is needed.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FASTEMBED_CACHE_PATH=/opt/fastembed \
    PORT=8001

# Bake the MiniLM ONNX model into the image. Free hosting tiers have no
# persistent disk, so without this every cold start would download it again.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('sentence-transformers/all-MiniLM-L6-v2', cache_dir='/opt/fastembed')"

# App code
COPY . .

# Run unprivileged: a container escape from the app process should not land as
# root.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app /opt/fastembed
USER appuser

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS "http://localhost:${PORT}/api/" || exit 1

# Hosts such as Render inject $PORT. --proxy-headers makes the app see the
# scheme/client address from the host's proxy; the rate limiter reads
# X-Forwarded-For itself.
CMD ["sh", "-c", "exec uvicorn server:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
