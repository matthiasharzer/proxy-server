FROM python:3.15-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY . /app
WORKDIR /app

RUN uv sync
ENV PATH="/app/.venv/bin:$PATH"

CMD ["uvicorn", "proxy.server:app", "--host", "0.0.0.0", "--port", "8080"]
