FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080 \
    SMRITI_ENV=prod \
    SMRITI_REQUIRE_AUTH=true

WORKDIR /app

RUN groupadd --system smriti && useradd --system --gid smriti --create-home smriti

COPY pyproject.toml AGENTS.md ./
COPY core ./core
COPY domains ./domains

RUN pip install --upgrade pip && \
    pip install ".[gcp]" && \
    chown -R smriti:smriti /app

USER smriti

EXPOSE 8080

CMD ["sh", "-c", "uvicorn core.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
