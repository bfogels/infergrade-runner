FROM python:3.11-slim

WORKDIR /app

COPY third_party/instruction_following_eval /opt/instruction_following_eval
COPY containers/capability-ifeval/runner.py /app/runner.py

RUN pip install --no-cache-dir -r /opt/instruction_following_eval/requirements.txt

ENTRYPOINT ["python", "/app/runner.py"]
