FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Europe/Berlin

RUN apt-get update \
 && apt-get install -y --no-install-recommends tini ca-certificates tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY docker/healthcheck.py ./docker/healthcheck.py
COPY tests ./tests
COPY pytest.ini .

RUN useradd --create-home --uid 10001 scanner \
 && mkdir -p /app/data /app/config \
 && chown -R scanner:scanner /app
USER scanner

VOLUME ["/app/data"]

HEALTHCHECK --interval=5m --timeout=10s --start-period=1m --retries=3 \
  CMD python docker/healthcheck.py

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "app.main"]
