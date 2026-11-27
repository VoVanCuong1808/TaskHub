FROM python:3.12-slim AS dependencies
COPY --from=ghcr.io/astral-sh/uv:0.11.26 /uv /uvx /bin/
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.12-slim AS runtime
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN useradd --create-home --uid 10001 taskhub
COPY --from=dependencies --chown=taskhub:taskhub /app/.venv /app/.venv
COPY --chown=taskhub:taskhub app ./app
COPY --chown=taskhub:taskhub alembic ./alembic
COPY --chown=taskhub:taskhub alembic.ini ./
USER taskhub
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
