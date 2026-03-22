#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUTPUT_DIR="${1:-$REPO_ROOT/dist}"
IMAGE_NAME="${2:-ulanzi-clock}"
IMAGE_TAG="${3:-$(date +%F)}"

mkdir -p "$OUTPUT_DIR"

docker image inspect "$IMAGE_NAME:$IMAGE_TAG" >/dev/null

docker save -o "$OUTPUT_DIR/$IMAGE_NAME-$IMAGE_TAG.tar" "$IMAGE_NAME:$IMAGE_TAG"
cp "$REPO_ROOT/config.json" "$OUTPUT_DIR/config.json"

if [[ -f "$REPO_ROOT/.env" ]]; then
    cp "$REPO_ROOT/.env" "$OUTPUT_DIR/.env"
fi

ls -lh "$OUTPUT_DIR"
