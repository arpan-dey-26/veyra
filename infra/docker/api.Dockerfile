# VEYRA API image
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app

COPY apps/api/pyproject.toml apps/api/uv.lock* ./
RUN uv sync --no-dev --no-install-project $( [ -f uv.lock ] && echo --frozen )

COPY apps/api/ ./
RUN useradd --create-home --uid 10001 veyra && chown -R veyra /app
USER veyra

EXPOSE 8000
# Apply migrations, then serve. (Migrations move to a one-off job before hosted deploys.)
CMD ["sh", "-c", "uv run --no-sync alembic upgrade head && uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers"]
