FROM python:3.11-slim

WORKDIR /app

ARG LIVECODEBENCH_DATASET_REVISION=0fe84c3912ea0c4d4a78037083943e8f0c4dd505
ARG LIVECODEBENCH_DATASET_SHA256=bb4c364f71921c4495a6ad15abe1a927350b720009f4933e2e71f8af0f6fd1f5
ENV LIVECODEBENCH_DATASET_REVISION=${LIVECODEBENCH_DATASET_REVISION}
ENV LIVECODEBENCH_DATASET_SHA256=${LIVECODEBENCH_DATASET_SHA256}
ENV LIVECODEBENCH_DATA_PATH=/opt/livecodebench/snapshot.jsonl
ENV LIVECODEBENCH_METADATA_PATH=/opt/livecodebench/snapshot_metadata.json

COPY containers/capability-livecodebench/build_snapshot.py /app/build_snapshot.py
RUN mkdir -p /opt/livecodebench && python /app/build_snapshot.py

COPY containers/capability-livecodebench/runner.py /app/runner.py
COPY containers/capability-livecodebench/SOURCE-NOTICE.txt /opt/livecodebench/SOURCE-NOTICE.txt

ENTRYPOINT ["python", "/app/runner.py"]
