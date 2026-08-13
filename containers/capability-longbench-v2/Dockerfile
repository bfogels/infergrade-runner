FROM python:3.11-slim

WORKDIR /app

ARG LONGBENCH_V2_DATASET_REVISION=2b48e494f2c7a2f0af81aae178e05c7e1dde0fe9
ARG LONGBENCH_V2_DATASET_SHA256=15d61c22d92c96900b3c4948b6aeea218d3214b676a65df48e7b8555604c7fe2
ENV LONGBENCH_V2_DATASET_REVISION=${LONGBENCH_V2_DATASET_REVISION}
ENV LONGBENCH_V2_DATASET_SHA256=${LONGBENCH_V2_DATASET_SHA256}
ENV LONGBENCH_V2_DATA_PATH=/opt/longbench-v2/snapshot.jsonl
ENV LONGBENCH_V2_METADATA_PATH=/opt/longbench-v2/snapshot_metadata.json

COPY containers/capability-longbench-v2/build_snapshot.py /app/build_snapshot.py
RUN mkdir -p /opt/longbench-v2 && python /app/build_snapshot.py

COPY containers/capability-longbench-v2/runner.py /app/runner.py
COPY containers/capability-longbench-v2/LICENSE.dataset /opt/longbench-v2/LICENSE.dataset

ENTRYPOINT ["python", "/app/runner.py"]
