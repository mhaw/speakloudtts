# Dockerfile

FROM python:3.10-slim

# install ffmpeg & ca-certs
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ffmpeg \
      ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# copy source
COPY . .

# set Flask env
ENV PORT=8080
ENV PYTHONUNBUFFERED=1

# run
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "app:app"]