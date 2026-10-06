#!/usr/bin/env python3
"""Resolve official semver releases to their digest-verified binary nightly."""
import argparse
import hashlib
import json
import os
import pathlib
import re
import ssl
import urllib.request

API = "https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/"

def read_url(url, limit):
    headers = {"User-Agent": "InferGrade-Runtime-Intake/1"}
    if url.startswith(API) and os.environ.get("GH_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GH_TOKEN"]
    context = ssl.create_default_context(cafile="/etc/ssl/cert.pem" if pathlib.Path("/etc/ssl/cert.pem").exists() else None)
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60, context=context) as response:
        body = response.read(limit + 1)
    if len(body) > limit:
        raise ValueError("Release metadata exceeds size limit")
    return body

def resolve_release(release, read=read_url):
    tag = release.get("tag_name", "")
    if re.fullmatch(r"b[0-9]+", tag):
        return release
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        raise ValueError("Expected bNNNN or vMAJOR.MINOR.PATCH release")
    assets = [a for a in release.get("assets", []) if a.get("name") == "nightly-tag.txt"]
    if len(assets) != 1:
        raise ValueError("Semver release must contain one nightly-tag.txt")
    asset = assets[0]
    expected_url = f"https://github.com/ggml-org/llama.cpp/releases/download/{tag}/nightly-tag.txt"
    if asset.get("browser_download_url") != expected_url or not 0 < int(asset.get("size", 0)) <= 128:
        raise ValueError("Invalid nightly pointer asset")
    body = read(expected_url, 128)
    if len(body) != asset["size"] or asset.get("digest") != "sha256:" + hashlib.sha256(body).hexdigest():
        raise ValueError("Nightly pointer checksum or length mismatch")
    nightly = body.decode("ascii").strip()
    if not re.fullmatch(r"b[0-9]+", nightly):
        raise ValueError("Invalid binary nightly tag")
    binary = json.loads(read(API + nightly, 2 * 1024 * 1024))
    if binary.get("tag_name") != nightly or binary.get("draft"):
        raise ValueError("Binary release does not match nightly pointer")
    binary["semantic_release"] = {"tag": tag, "url": release.get("html_url"), "pointer_sha256": asset["digest"]}
    return binary

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-json", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    result = resolve_release(json.loads(args.release_json.read_text()))
    args.output.write_text(json.dumps(result, indent=2) + "\n")
