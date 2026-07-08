#!/usr/bin/env bash
# Corrige propiedad y SELinux de data/ y snapshots/ para worker + web (Podman rootless, Fedora).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

UID_NUM="$(id -u)"
GID_NUM="$(id -g)"

chown_tree() {
  if chown -R "${UID_NUM}:${GID_NUM}" data snapshots 2>/dev/null; then
    return 0
  fi
  echo "Archivos root:root detectados; se usa sudo..."
  sudo chown -R "${UID_NUM}:${GID_NUM}" data snapshots
}

echo "Ajustando propietario a ${UID_NUM}:${GID_NUM}..."
chown_tree
chmod -R u+rwX data snapshots

if command -v chcon >/dev/null 2>&1 && [ "$(getenforce 2>/dev/null || echo Disabled)" = "Enforcing" ]; then
  echo "SELinux: etiqueta compartida container_file_t:s0 (sin categoría privada cXXX)..."
  if chcon -R -t container_file_t -l s0 data snapshots 2>/dev/null; then
    :
  else
    sudo chcon -R -t container_file_t -l s0 data snapshots
  fi
fi

echo ""
echo "Añade a tu .env (UID/GID de tu usuario en el host):"
echo "  HOST_UID=${UID_NUM}"
echo "  HOST_GID=${GID_NUM}"
echo ""
echo "Listo. Reinicia el stack:"
echo "  podman compose down && podman compose up -d"
