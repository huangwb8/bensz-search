FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 LITELLM_LOCAL_MODEL_COST_MAP=True \
    LITELLM_TELEMETRY=False
WORKDIR /app
RUN pip install --no-cache-dir uv==0.11.14
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable
COPY config ./config
COPY demo ./demo
RUN useradd --uid 10001 --create-home appuser && mkdir /app/data && chown -R appuser:appuser /app
USER appuser
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/liveliness', timeout=3)"
CMD ["uvicorn", "bensz_search.server:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--limit-concurrency", "64", "--timeout-graceful-shutdown", "30"]
