#!/usr/bin/env bash
# Construye imagen multi-arquitectura (x86_64 + arm64) con Podman.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

IMAGE="${IMAGE:-localhost/webcam-follow:latest}"
PLATFORMS="${PLATFORMS:-linux/amd64,linux/arm64}"
PUSH="${PUSH:-false}"

echo "==> Imagen:  $IMAGE"
echo "==> Arquitecturas: $PLATFORMS"

if podman manifest exists "$IMAGE" 2>/dev/null; then
    podman manifest rm "$IMAGE" || true
fi

podman manifest create "$IMAGE"

IFS=',' read -ra ARCH_LIST <<< "$PLATFORMS"
for platform in "${ARCH_LIST[@]}"; do
    platform="${platform// /}"
    arch="${platform#linux/}"
    tag="${IMAGE}-${arch}"

    echo ""
    echo "==> Construyendo $platform ..."
    podman build \
        --platform "$platform" \
        --tag "$tag" \
        -f Containerfile \
        .

    podman manifest add "$IMAGE" "$tag"
done

echo ""
echo "==> Manifest listo: $IMAGE"
podman manifest inspect "$IMAGE" | grep -E '"architecture"|"os"' || true

if [[ "$PUSH" == "true" ]]; then
    if [[ -z "${REGISTRY:-}" ]]; then
        echo "ERROR: define REGISTRY para publicar (ej. REGISTRY=ghcr.io/usuario)" >&2
        exit 1
    fi
    REMOTE="${REGISTRY}/webcam-follow:latest"
    podman tag "$IMAGE" "$REMOTE"
    podman push "$REMOTE"
    echo "Publicado en $REMOTE"
fi

echo ""
echo "Ejecutar localmente:"
echo "  podman run --rm --env-file .env -v ./snapshots:/app/snapshots $IMAGE"
echo "  podman compose up -d"
