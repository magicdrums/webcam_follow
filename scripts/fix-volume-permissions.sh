#!/usr/bin/env bash
# Corrige propiedad y SELinux de data/ y snapshots/ para worker + web (Podman rootless, Fedora).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

UID_NUM="$(id -u)"
GID_NUM="$(id -g)"

echo "Ajustando propietario a ${UID_NUM}:${GID_NUM}..."
chown -R "${UID_NUM}:${GID_NUM}" data snapshots
chmod -R u+rwX data snapshots

if command -v chcon >/dev/null 2>&1 && [ "$(getenforce 2>/dev/null || echo Disabled)" = "Enforcing" ]; then
  echo "SELinux: etiqueta compartida container_file_t (varios contenedores)..."
  chcon -Rt container_file_t data snapshots
fi

echo "Listo. Reinicia el stack:"
echo "  podman compose down && podman compose up -d"
