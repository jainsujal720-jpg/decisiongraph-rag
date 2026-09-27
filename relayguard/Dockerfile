FROM python:3.12-slim AS builder
WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

FROM python:3.12-slim
WORKDIR /app
RUN groupadd --system app && useradd --system --gid app app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app src ./src
ENV PATH="/opt/venv/bin:$PATH" PYTHONPATH="/app/src" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER app
EXPOSE 8100
CMD ["uvicorn", "relayguard.api.main:app", "--host", "0.0.0.0", "--port", "8100"]
