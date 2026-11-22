FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /bin/
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev
COPY frontdesk ./frontdesk
COPY migrations ./migrations
COPY scripts ./scripts
RUN useradd --create-home --uid 10001 frontdesk && chown -R frontdesk:frontdesk /app
USER frontdesk
ENV PATH="/app/.venv/bin:$PATH" PORT=8000
EXPOSE 8000
# Startup migrates and provisions demo credentials before dropping DB privileges.
CMD ["python", "-m", "scripts.start"]
