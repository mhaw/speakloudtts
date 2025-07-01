# syntax=docker/dockerfile:1

# ─── Builder Stage ───────────────────────────────────────────────────────
FROM python:3.10-slim AS builder

# Install build tools + headers for cryptography, lxml, etc.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential \
      gcc \
      libffi-dev \
      libssl-dev \
      libxml2-dev \
      libxslt1-dev \
      zlib1g-dev \
      ffmpeg \
      ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /install

COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ─── Final Stage ─────────────────────────────────────────────────────────
FROM python:3.10-slim AS runner

# Install only runtime deps
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ffmpeg \
      libxml2 \
      libxslt1.1 \
      libssl3 \
      libffi8 \
      zlib1g \
      ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Add Python dependencies
COPY --from=builder /install /usr/local

# Copy app code
COPY . .

# ─── Generate Build ID ───────────────────────────────────────────────────
# This uses sh to generate a build id like '07012025_wolf_blitzer'
RUN BUILD_ID="$(date +%m%d%Y)_$(shuf -n1 -e wolf_blitzer jack_handey alec_baldwin bill_murray taylor_swift tony_stark rihanna lizzo the_bear morrissey joan_didion sue_bird)" && \
    echo "$BUILD_ID" > BUILD_INFO && \
    echo "export BUILD_ID=$BUILD_ID" >> /etc/profile

ENV PORT=8080 \
    PYTHONUNBUFFERED=1 \
    BUILD_ID_FILE=/app/BUILD_INFO

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "app:app"]