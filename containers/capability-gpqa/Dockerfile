FROM python:3.11-slim

WORKDIR /app

ARG GPQA_REPOSITORY_REVISION=56686c06f5e19865c153de0fdb11be3890014df7
ARG GPQA_DATASET_SHA256=461ae7329f15a3e35f8184d2dac24b990f34fdf12f366ca4062d8e6638cd08dc
ENV GPQA_REPOSITORY_REVISION=${GPQA_REPOSITORY_REVISION}
ENV GPQA_DATASET_SHA256=${GPQA_DATASET_SHA256}
ENV GPQA_DATA_PATH=/opt/gpqa/gpqa_diamond.csv

COPY containers/capability-gpqa/build_snapshot.py /app/build_snapshot.py
RUN mkdir -p /opt/gpqa && python /app/build_snapshot.py

COPY containers/capability-gpqa/runner.py /app/runner.py
COPY containers/capability-gpqa/LICENSE.dataset /opt/gpqa/LICENSE.dataset

ENTRYPOINT ["python", "/app/runner.py"]
