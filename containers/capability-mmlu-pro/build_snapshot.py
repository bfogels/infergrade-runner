import json
import os

from datasets import load_dataset


def main() -> int:
    revision = os.environ["MMLU_PRO_DATASET_REVISION"]
    rows = load_dataset("TIGER-Lab/MMLU-Pro", split="test", revision=revision)
    with open(os.environ["MMLU_PRO_DATA_PATH"], "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
