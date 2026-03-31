FROM python:3.11-slim

WORKDIR /app

COPY python/runner-core/pyproject.toml /app/pyproject.toml
COPY python/runner-core/README.md /app/README.md
COPY python/runner-core/src /app/src

RUN pip install --no-cache-dir -e .

ENTRYPOINT ["infergrade"]
