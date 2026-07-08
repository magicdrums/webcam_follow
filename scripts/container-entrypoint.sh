#!/usr/bin/env bash
set -euo pipefail

# En Podman rootless el proceso suele arrancar con HOST_UID del host (compose user:).
can_write_dir() {
  local dir="$1"
  mkdir -p "$dir" 2>/dev/null || true
  local probe="${dir}/.entrypoint_write_test_$$"
  if touch "$probe" 2>/dev/null; then
    rm -f "$probe"
    return 0
  fi
  return 1
}

report_volume_error() {
  local dir="$1"
  echo "ERROR: no se puede escribir en ${dir}" >&2
  echo "Usuario del contenedor: $(id -u):$(id -g)" >&2
  ls -ldZ "$dir" 2>/dev/null || ls -ld "$dir" 2>/dev/null || true
  echo "En el host (desde el directorio del proyecto) ejecuta:" >&2
  echo "  ./scripts/fix-volume-permissions.sh" >&2
  echo "  ./scripts/compose.sh up -d" >&2
}

if [ "$(id -u)" = "0" ]; then
  for dir in /app/data /app/snapshots; do
    mkdir -p "$dir"
    chown -R appuser:appuser "$dir" 2>/dev/null || true
    chmod -R u+rwX,g+rwX "$dir" 2>/dev/null || true
    if ! can_write_dir "$dir"; then
      report_volume_error "$dir"
      exit 1
    fi
  done
  exec runuser -u appuser -- "$@"
fi

for dir in /app/data /app/snapshots; do
  if ! can_write_dir "$dir"; then
    report_volume_error "$dir"
    exit 1
  fi
done
exec "$@"
