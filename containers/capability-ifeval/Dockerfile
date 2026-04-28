FROM python:3.11-slim

WORKDIR /app

COPY third_party/instruction_following_eval /opt/instruction_following_eval
COPY containers/capability-ifeval/runner.py /app/runner.py

RUN pip install --no-cache-dir -r /opt/instruction_following_eval/requirements.txt

ENV NLTK_DATA=/usr/local/share/nltk_data

RUN mkdir -p /opt/instruction_following_eval/data \
    && python -c "from urllib.request import urlretrieve; urlretrieve('https://raw.githubusercontent.com/google-research/google-research/ceea2f13fd823c3493d6e6f232f334d083671c94/instruction_following_eval/data/input_data.jsonl', '/opt/instruction_following_eval/data/input_data.jsonl')"

RUN python -c "import nltk; [nltk.download(package, download_dir='/usr/local/share/nltk_data', quiet=True) for package in ('punkt', 'punkt_tab')]"

ENTRYPOINT ["python", "/app/runner.py"]
