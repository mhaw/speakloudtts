# syntax=docker/dockerfile:1

# ─── Builder Stage ───────────────────────────────────────────────────────
FROM python:3.10-slim AS builder

# Install build-tools + runtime deps (we’ll need ffmpeg later, too)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential \
      ffmpeg \
      ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /install

# Copy just requirements & install them into /install
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ─── Final Stage ─────────────────────────────────────────────────────────
FROM python:3.10-slim AS runner

# Install only runtime bits
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ffmpeg \
      ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Pull in the Python packages we installed in builder
COPY --from=builder /install /usr/local

# Copy your application code
COPY . .

# Expose & launch
ENV PORT=8080 \
    PYTHONUNBUFFERED=1

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "app:app"]