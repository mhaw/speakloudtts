# syntax=docker/dockerfile:1

# ─── Builder Stage ──────────────────────────────────────────────
FROM python:3.11-slim AS builder

# Install build tools, headers, and Node.js for frontend build
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      curl \
      ffmpeg \
      libxml2 \
      libxslt1.1 \
      libssl-dev \
      libffi-dev \
      zlib1g \
      ca-certificates && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*
    
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Install Node.js dependencies and build CSS
COPY package.json package-lock.json* tailwind.config.js ./
COPY static/css/input.css static/css/input.css
RUN npm install && \
    npm run build:css

# ─── Runner Stage ───────────────────────────────────────────────
FROM python:3.11-slim AS runner

# Install runtime libraries
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

# Copy dependencies from builder
COPY --from=builder /install /usr/local
COPY --from=builder /app/static/css/output.css /app/static/css/output.css

# Copy app code
COPY . .

COPY credentials.json /app/credentials.json


# ─── Generate Build ID ──────────────────────────────────────────
RUN BUILD_ID="$(date +%m%d%Y)_$(shuf -n1 -e wolf_blitzer jack_handey alec_baldwin bill_murray taylor_swift tony_stark rihanna lizzo the_bear morrissey joan_didion sue_bird)" && \
    echo "$BUILD_ID" > BUILD_INFO && \
    echo "export BUILD_ID=$BUILD_ID" >> /etc/profile

ENV PORT=8080 \
    PYTHONUNBUFFERED=1 \
    BUILD_ID_FILE=/app/BUILD_INFO \
    GOOGLE_APPLICATION_CREDENTIALS=/app/credentials.json

CMD ["gunicorn", "-b", "0.0.0.0:8080", "main:app", "--timeout", "300"]