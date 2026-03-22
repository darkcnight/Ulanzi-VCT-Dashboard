#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VLRGGAPI_DIR="${VLRGGAPI_DIR:-$HOME/Downloads/vlrggapi}"
BUILD_ROOT="$REPO_ROOT/.docker-build/combined"
IMAGE_NAME="${1:-ulanzi-clock}"
IMAGE_TAG="${2:-$(date +%F)}"

if [[ ! -d "$VLRGGAPI_DIR" ]]; then
    echo "vlrggapi repo not found at: $VLRGGAPI_DIR" >&2
    exit 1
fi

if [[ -f "$REPO_ROOT/.env" ]]; then
    echo "Note: .env is excluded from the image build context."
    echo "Mount it at /app/dashboard/.env on the deployment target."
fi

export REPO_ROOT
export VLRGGAPI_DIR
export BUILD_ROOT

python3 <<'PY'
from pathlib import Path
import os
import shutil

repo_root = Path(os.environ["REPO_ROOT"])
vlrggapi_dir = Path(os.environ["VLRGGAPI_DIR"])
build_root = Path(os.environ["BUILD_ROOT"])

dashboard_dst = build_root / "dashboard"
vlrggapi_dst = build_root / "vlrggapi"

if build_root.exists():
    shutil.rmtree(build_root)

dashboard_ignore = shutil.ignore_patterns(
    ".git",
    ".github",
    ".cursor",
    ".docker-build",
    "venv",
    ".venv",
    "__pycache__",
    "*.pyc",
    "*.pyo",
    ".env",
    "config.json",
    "*.tar",
)

vlrggapi_ignore = shutil.ignore_patterns(
    ".git",
    ".github",
    "venv",
    ".venv",
    "__pycache__",
    "*.pyc",
    "*.pyo",
    "tests",
)

shutil.copytree(repo_root, dashboard_dst, ignore=dashboard_ignore)
shutil.copytree(vlrggapi_dir, vlrggapi_dst, ignore=vlrggapi_ignore)

docker_dir = repo_root / "docker"
shutil.copy2(docker_dir / "Dockerfile.combined", build_root / "Dockerfile")
shutil.copy2(docker_dir / "requirements-combined.txt", build_root / "requirements-combined.txt")
shutil.copy2(docker_dir / "combined-entrypoint.sh", build_root / "combined-entrypoint.sh")
PY

docker build -t "$IMAGE_NAME:$IMAGE_TAG" "$BUILD_ROOT"
