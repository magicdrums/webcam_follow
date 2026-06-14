#!/usr/bin/env bash
# Build simple para la arquitectura actual (más rápido que multi-arch).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

IMAGE="${IMAGE:-localhost/webcam-follow:latest}"

podman build -t "$IMAGE" -f Containerfile .
echo "Listo: $IMAGE"
echo "  podman run --rm --env-file .env -v ./snapshots:/app/snapshots $IMAGE"
