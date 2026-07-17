#!/usr/bin/env python3
"""Verify public InferGrade container tags through the anonymous OCI API."""

from __future__ import annotations

import argparse
import json
import ssl
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


IMAGE_NAMES = (
    "infergrade-runner-core",
    "infergrade-llama-cpp",
    "infergrade-ifeval",
    "infergrade-evalplus",
    "infergrade-mmlu-pro",
)
INDEX_ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)
MANIFEST_ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)


@dataclass(frozen=True)
class ImageProof:
    reference: str
    manifest_digest: str
    platform_manifest_digest: str
    config_digest: str


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="verify_release_images")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--registry-prefix", default="ghcr.io/bfogels")
    return parser


def parse_registry_prefix(value: str) -> tuple[str, str]:
    normalized = value.strip()
    for prefix in ("https://", "http://"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
    normalized = normalized.strip("/")
    registry, separator, namespace = normalized.partition("/")
    if not separator or not registry or not namespace or "/" in namespace:
        raise ValueError("Registry prefix must look like ghcr.io/owner.")
    return registry, namespace


def _json_request(url: str, *, token: str = "", accept: str = "application/json") -> tuple[dict, dict[str, str]]:
    headers = {"Accept": accept, "User-Agent": "infergrade-release-verifier"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    default_paths = ssl.get_default_verify_paths()
    system_ca = Path("/etc/ssl/cert.pem")
    context = None
    if not default_paths.cafile and system_ca.is_file():
        context = ssl.create_default_context(cafile=str(system_ca))
    with urlopen(Request(url, headers=headers), timeout=30, context=context) as response:
        payload = json.loads(response.read().decode("utf-8"))
        response_headers = {name.lower(): value for name, value in response.headers.items()}
    if not isinstance(payload, dict):
        raise ValueError(f"Registry response was not an object: {url}")
    return payload, response_headers


def _manifest_request(registry: str, repository: str, reference: str, token: str, accept: str) -> tuple[dict, str]:
    payload, headers = _json_request(
        f"https://{registry}/v2/{repository}/manifests/{reference}", token=token, accept=accept
    )
    digest = headers.get("docker-content-digest", "").strip()
    if not digest.startswith("sha256:"):
        raise ValueError(f"Registry omitted an immutable manifest digest for {repository}:{reference}.")
    return payload, digest


def _linux_amd64_descriptor(payload: dict) -> dict:
    manifests = payload.get("manifests")
    if not isinstance(manifests, list):
        raise ValueError("OCI index is missing manifests.")
    for descriptor in manifests:
        platform = descriptor.get("platform") if isinstance(descriptor, dict) else None
        if isinstance(platform, dict) and platform.get("os") == "linux" and platform.get("architecture") == "amd64":
            return descriptor
    raise ValueError("OCI index does not contain a linux/amd64 image.")


def verify_image(registry: str, namespace: str, image: str, tag: str) -> ImageProof:
    repository = f"{namespace}/{image}"
    token_payload, _ = _json_request(
        f"https://{registry}/token?{urlencode({'scope': f'repository:{repository}:pull'})}"
    )
    token = str(token_payload.get("token") or "").strip()
    if not token:
        raise ValueError(f"Anonymous pull token was not issued for {repository}.")

    payload, manifest_digest = _manifest_request(registry, repository, tag, token, INDEX_ACCEPT)
    media_type = str(payload.get("mediaType") or "")
    platform_manifest_digest = manifest_digest
    if media_type.endswith("image.index.v1+json") or media_type.endswith("manifest.list.v2+json"):
        descriptor = _linux_amd64_descriptor(payload)
        platform_manifest_digest = str(descriptor.get("digest") or "")
        if not platform_manifest_digest.startswith("sha256:"):
            raise ValueError(f"linux/amd64 descriptor is missing a digest for {repository}:{tag}.")
        payload, fetched_digest = _manifest_request(
            registry, repository, platform_manifest_digest, token, MANIFEST_ACCEPT
        )
        if fetched_digest != platform_manifest_digest:
            raise ValueError(f"Platform manifest digest drifted for {repository}:{tag}.")

    config = payload.get("config")
    config_digest = str(config.get("digest") if isinstance(config, dict) else "")
    if not config_digest.startswith("sha256:"):
        raise ValueError(f"Image manifest is missing a config digest for {repository}:{tag}.")
    return ImageProof(
        reference=f"{registry}/{repository}:{tag}",
        manifest_digest=manifest_digest,
        platform_manifest_digest=platform_manifest_digest,
        config_digest=config_digest,
    )


def main() -> int:
    args = build_parser().parse_args()
    try:
        registry, namespace = parse_registry_prefix(args.registry_prefix)
        proofs = [verify_image(registry, namespace, image, args.tag) for image in IMAGE_NAMES]
    except Exception as error:
        raise SystemExit(f"Anonymous image verification failed: {error}") from error
    for proof in proofs:
        print(
            f"{proof.reference}\tmanifest:{proof.manifest_digest}"
            f"\tlinux_amd64:{proof.platform_manifest_digest}\tconfig:{proof.config_digest}"
        )
    print(f"Verified anonymous registry access for {len(proofs)} InferGrade images at {args.tag}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
