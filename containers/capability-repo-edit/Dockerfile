FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends patch \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY containers/capability-repo-edit/fixtures.json /opt/infergrade/repository-edit/fixtures.json
COPY containers/capability-repo-edit/runner.py /app/runner.py

ENTRYPOINT ["python", "/app/runner.py"]
