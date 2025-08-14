FROM python:3.11-slim
# Install dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*


RUN useradd -m appuser


RUN pip install --no-cache-dir flask
WORKDIR /app

COPY . /app

ENV OUT=tractusx-docs
RUN mkdir -p "/app/${OUT}" && chown -R appuser:appuser "/app/${OUT}"

EXPOSE 5000
USER appuser

ENV INTERVAL_HOURS=24 \
    FAST_MODE=1 \
    WORKERS=12 \
    PATHS="docs,documentation,doc,website/docs" \
    ORG="eclipse-tractusx" \
    MONTHS_BACK=6 \
    PORT=5000

CMD ["python", "app.py"]
