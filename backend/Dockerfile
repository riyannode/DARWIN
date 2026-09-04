FROM python:3.14-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv==0.12.9 && uv sync --frozen --no-dev
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH=/app/src
CMD ["uvicorn", "darwinspot.main:app", "--host", "0.0.0.0", "--port", "8000"]
