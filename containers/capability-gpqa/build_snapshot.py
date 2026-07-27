"""Fetch and verify the official GPQA dataset archive during image build."""

import hashlib
import io
import os
import urllib.request
import zipfile


DATASET_URL = (
    "https://raw.githubusercontent.com/idavidrein/gpqa/"
    "%s/dataset.zip" % os.environ["GPQA_REPOSITORY_REVISION"]
)
EXPECTED_SHA256 = os.environ["GPQA_DATASET_SHA256"]
ARCHIVE_PASSWORD = b"deserted-untie-orchid"
OUTPUT_PATH = os.environ["GPQA_DATA_PATH"]


with urllib.request.urlopen(DATASET_URL, timeout=60) as response:
    payload = response.read()
actual_sha256 = hashlib.sha256(payload).hexdigest()
if actual_sha256 != EXPECTED_SHA256:
    raise RuntimeError("GPQA dataset archive SHA-256 mismatch: %s" % actual_sha256)

with zipfile.ZipFile(io.BytesIO(payload)) as archive:
    dataset = archive.read("dataset/gpqa_diamond.csv", pwd=ARCHIVE_PASSWORD)
    license_text = archive.read("dataset/license.txt", pwd=ARCHIVE_PASSWORD).decode("utf-8")
if "Creative Commons Attribution 4.0" not in license_text:
    raise RuntimeError("GPQA dataset license marker is missing")

with open(OUTPUT_PATH, "wb") as handle:
    handle.write(dataset)
