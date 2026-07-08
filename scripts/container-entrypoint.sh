#!/usr/bin/env bash
set -euo pipefail

# En Podman rootless, root dentro del contenedor = usuario del host en volúmenes bind.
ensure_volume() {
  local dir="$1"
  mkdir -p "$dir"
  chown -R appuser:appuser "$dir" 2>/dev/null || true
  chmod -R u+rwX,g+rwX "$dir" 2>/dev/null || true
  if [ ! -w "$dir" ]; then
    echo "ERROR: no se puede escribir en ${dir}" >&2
    echo "En el host ejecuta:" >&2
    echo "  chown -R \$(id -u):\$(id -g) data snapshots" >&2
    echo "  chmod -R u+rwX data snapshots" >&2
    echo "En Fedora con SELinux:" >&2
    echo "  chcon -Rt container_file_t data snapshots" >&2
    exit 1
  fi
}

if [ "$(id -u)" = "0" ]; then
  ensure_volume /app/data
  ensure_volume /app/snapshots
  exec runuser -u appuser -- "$@"
fi

# Fallback si la imagen se ejecuta directamente como appuser (sin root)
for dir in /app/data /app/snapshots; do
  mkdir -p "$dir" 2>/dev/null || true
  if [ ! -w "$dir" ]; then
    echo "ERROR: no se puede escribir en ${dir}. Reconstruye la imagen o ajusta permisos en el host." >&2
    exit 1
  fi
done
exec "$@"
