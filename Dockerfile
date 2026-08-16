FROM node:22-alpine AS frontend

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml alembic.ini ./
COPY migrations migrations
COPY src src
COPY --from=frontend /frontend/dist src/kmoe_subscriptions/static
RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data /downloads \
    && chown -R app:app /data /downloads
USER app

EXPOSE 8000
CMD ["uvicorn", "kmoe_subscriptions.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
