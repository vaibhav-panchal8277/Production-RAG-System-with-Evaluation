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

EXPOSE 8001

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"]
