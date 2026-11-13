FROM python:3.11-slim

WORKDIR /app

# System deps (needed for torch/sentence-transformers to run cleanly on CPU)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    # replace torch with CPU-only build (dramatically smaller image)
    && pip uninstall -y torch \
    && pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.5.1

# App code
COPY . .

# Run unprivileged: a container escape from the app process should not land as
# root. HF_HOME must be writable by that user for the MiniLM model cache.
ENV HF_HOME=/home/appuser/.cache/huggingface \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p "$HF_HOME" \
    && chown -R appuser:appuser /app /home/appuser
USER appuser

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD curl -fsS http://localhost:8001/api/ || exit 1

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"]
