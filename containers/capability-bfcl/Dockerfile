FROM python:3.11-slim

WORKDIR /app

ARG BFCL_UPSTREAM_REVISION=6ea57973c7a6097fd7c5915698c54c17c5b1b6c8
ENV BFCL_UPSTREAM_REVISION=${BFCL_UPSTREAM_REVISION}
ENV BFCL_DATA_PATH=/opt/bfcl/snapshot.jsonl
ENV BFCL_METADATA_PATH=/opt/bfcl/snapshot_metadata.json

COPY containers/capability-bfcl/build_snapshot.py /app/build_snapshot.py
RUN mkdir -p /opt/bfcl && python /app/build_snapshot.py

COPY containers/capability-bfcl/runner.py /app/runner.py
COPY containers/capability-bfcl/LICENSE.upstream /opt/bfcl/LICENSE.upstream

ENTRYPOINT ["python", "/app/runner.py"]
