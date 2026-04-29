FROM python:3.11-slim

WORKDIR /app

ARG MMLU_PRO_DATASET_REVISION=54611cde22c74cca43dd78732198de6abe971398
ENV MMLU_PRO_DATASET_REVISION=${MMLU_PRO_DATASET_REVISION}
ENV MMLU_PRO_DATA_PATH=/opt/mmlu_pro/test.jsonl

RUN pip install --no-cache-dir "datasets==2.19.2"

COPY containers/capability-mmlu-pro/build_snapshot.py /app/build_snapshot.py

RUN mkdir -p /opt/mmlu_pro \
    && python /app/build_snapshot.py

COPY containers/capability-mmlu-pro/runner.py /app/runner.py

ENTRYPOINT ["python", "/app/runner.py"]
