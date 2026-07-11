"""Docker image helpers for InferGrade runtime and capability containers."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Dict, Optional

from infergrade import __version__


LOCAL_IMAGE_DOCKERFILES: Dict[str, str] = {
    "infergrade-llama-cpp": "containers/llama-cpp/Dockerfile",
    "infergrade-ifeval": "containers/capability-ifeval/Dockerfile",
    "infergrade-evalplus": "containers/capability-evalplus/Dockerfile",
    "infergrade-mmlu-pro": "containers/capability-mmlu-pro/Dockerfile",
    "infergrade-runner-core": "containers/runner-core/Dockerfile",
}
RUNNER_CORE_IMAGE = "infergrade-runner-core:local"


def docker_image_exists(image: str) -> bool:
    """Return whether a Docker image is already available locally."""
    try:
        completed = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return False
    return completed.returncode == 0


def install_image(
    image: str,
    *,
    prefer_local_build: bool = True,
    pull_if_missing: bool = True,
    rebuild: bool = False,
) -> Dict[str, str]:
    """Ensure a Docker image is available, building or pulling when possible."""
    repository, _, tag = image.rpartition(":")
    known_repository = _known_repository_name(repository)
    if rebuild and prefer_local_build and known_repository:
        build_result = _try_build_local_image(known_repository, image)
        if build_result:
            build_result["action"] = "rebuilt"
            return build_result

    if docker_image_exists(image):
        return {"image": image, "action": "present"}

    if prefer_local_build and known_repository:
        build_result = _try_build_local_image(known_repository, image)
        if build_result:
            return build_result

    if pull_if_missing:
        completed = subprocess.run(
            ["docker", "pull", image],
            capture_output=True,
            text=True,
        )
        if completed.returncode == 0:
            return {"image": image, "action": "pulled"}
        message = (completed.stderr or completed.stdout or "").strip()
        if tag == "local":
            raise RuntimeError(
                "Docker image %s is not available locally. Build it with `infergrade install-images --image %s` "
                "or `./scripts/build_release_images.sh`. Docker also failed to pull it: %s"
                % (image, image, message or "unknown error")
            )
        raise RuntimeError(
            "Failed to pull Docker image %s: %s"
            % (image, message or "unknown error")
        )

    raise RuntimeError(
        "Docker image %s is not available locally."
        % image
    )


def install_known_images(image: Optional[str] = None, rebuild: bool = False) -> Dict[str, Dict[str, str]]:
    """Build all known local images, or one specific image, from local source."""
    targets = _expand_install_targets(image)
    installed = {}
    for target in targets:
        installed[target] = install_image(
            target,
            prefer_local_build=True,
            pull_if_missing=True,
            rebuild=rebuild,
        )
    return installed


def local_build_command(image: str) -> Optional[str]:
    """Return the local build command for a known image when source is available."""
    repository, _, _tag = image.rpartition(":")
    dockerfile = LOCAL_IMAGE_DOCKERFILES.get(_known_repository_name(repository))
    root = _repo_root()
    if not dockerfile or not root:
        return None
    return "docker build -t %s -f %s %s" % (
        image,
        os.path.join(root, dockerfile),
        root,
    )


def _try_build_local_image(repository: str, full_image: str) -> Optional[Dict[str, str]]:
    """Build a known local image from the checked-out runner repo."""
    dockerfile = LOCAL_IMAGE_DOCKERFILES.get(repository)
    root = _repo_root()
    if not dockerfile or not root:
        return None
    dockerfile_path = os.path.join(root, dockerfile)
    completed = subprocess.run(
        ["docker", "build", "-t", full_image, "-f", dockerfile_path, root],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(
            "Failed to build local Docker image %s from %s: %s"
            % (full_image, dockerfile_path, message or "unknown error")
        )
    return {"image": full_image, "action": "built", "dockerfile": dockerfile_path}


def _expand_install_targets(image: Optional[str]) -> list[str]:
    """Expand a requested install target into the images needed for the local flow."""
    if not image:
        return ["ghcr.io/bfogels/%s:%s" % (name, __version__) for name in LOCAL_IMAGE_DOCKERFILES]
    targets = []
    repository, _, tag = image.partition(":")
    if tag == "local" and repository != "infergrade-runner-core":
        targets.append(RUNNER_CORE_IMAGE)
    targets.append(image)
    deduped = []
    for target in targets:
        if target not in deduped:
            deduped.append(target)
    return deduped


def _known_repository_name(repository: str) -> Optional[str]:
    candidate = str(repository or "").rsplit("/", 1)[-1]
    return candidate if candidate in LOCAL_IMAGE_DOCKERFILES else None


def container_image_identity(image: str) -> Dict[str, object]:
    """Return the exact local image identity used by a capability scorer."""
    payload: Dict[str, object] = {"container_image": image, "container_image_id": None, "container_repo_digests": []}
    if not image:
        return payload
    try:
        completed = subprocess.run(
            ["docker", "image", "inspect", image, "--format", "{{json .}}"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return payload
    if completed.returncode != 0:
        return payload
    try:
        import json

        inspected = json.loads((completed.stdout or "").strip())
    except (TypeError, ValueError):
        return payload
    payload["container_image_id"] = inspected.get("Id")
    payload["container_repo_digests"] = list(inspected.get("RepoDigests") or [])
    return payload


def _repo_root() -> Optional[str]:
    """Find the checked-out infergrade-runner repository root when available."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "containers").exists() and (parent / "python" / "runner-core").exists():
            return str(parent)
    return None
