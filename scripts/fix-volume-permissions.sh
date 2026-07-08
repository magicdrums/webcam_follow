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
mkdir -p data snapshots
chown_tree
chmod -R u+rwX data snapshots
# Asegura que el directorio en sí es transitable/escribible
chmod u+rwX data snapshots

if command -v chcon >/dev/null 2>&1 && [ "$(getenforce 2>/dev/null || echo Disabled)" = "Enforcing" ]; then
  echo "SELinux: etiqueta compartida container_file_t:s0 (sin categoría privada cXXX)..."
  if chcon -R -t container_file_t -l s0 data snapshots 2>/dev/null; then
    :
  else
    sudo chcon -R -t container_file_t -l s0 data snapshots
  fi
fi

echo ""
echo "Prueba de escritura en el host..."
for dir in data snapshots; do
  probe="${dir}/.perm_test_$$"
  if ! touch "$probe" 2>/dev/null; then
    echo "ERROR: aún no se puede escribir en ${dir}/" >&2
    ls -ldZ "$dir" 2>/dev/null || ls -ld "$dir" >&2
    exit 1
  fi
  rm -f "$probe"
done
echo "OK: data/ y snapshots/ escribibles por ${UID_NUM}:${GID_NUM}"
echo ""
echo "Levanta el stack con:"
echo "  ./scripts/compose.sh up -d"
echo ""
echo "Si .env tiene HOST_UID/HOST_GID, elimínalos (obsoletos; compose usa PUID/PGID de tu sesión)."
