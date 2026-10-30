FROM python:3.12.10-slim-bookworm

ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/server

WORKDIR /app
COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip-marketlens-v3 \
    python -m pip install --index-url "$PIP_INDEX_URL" --retries 20 --timeout 120 --requirement requirements.txt

COPY market_core ./market_core
COPY server/app ./server/app
COPY server/migrations ./server/migrations
COPY server/config.example.json ./server/config.example.json

RUN groupadd --gid 10001 marketlens \
    && useradd --uid 10001 --gid marketlens --no-create-home marketlens \
    && mkdir -p /app/server/data \
    && chown -R marketlens:marketlens /app/server/data

USER marketlens
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
