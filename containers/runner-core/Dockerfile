FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl docker-cli \
    && rm -rf /var/lib/apt/lists/*

COPY python/runner-core/pyproject.toml /app/pyproject.toml
COPY python/runner-core/README.md /app/README.md
COPY python/runner-core/src /app/src
COPY schemas /app/schemas

RUN pip install --no-cache-dir -e .

ENTRYPOINT ["infergrade"]
