# Backend API + websocket (Railway / any container host).
# Build context = this `backend/` directory (set Railway's root dir to /backend).
# MUST run a single process/worker — the APScheduler poller + websocket connection
# manager are single-instance (see docs/AI_LANDMINES.md). The `ml` extra is omitted
# (the API server doesn't need LightGBM/SHAP) to keep the image lean.
FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --extra export --extra api --frozen

ENV PORT=8000
EXPOSE 8000
# Set TWELVEDATA_API_KEY / POLYGON_API_KEY etc. in the host's env (never bake them in).
CMD ["sh", "-c", "uv run intradayx serve --host 0.0.0.0 --port ${PORT}"]
