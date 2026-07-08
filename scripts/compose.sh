#!/usr/bin/env bash
# Arranca compose con UID/GID del host (necesario con docker-compose + Podman).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export HOST_UID="$(id -u)"
export HOST_GID="$(id -g)"

exec podman compose "$@"
