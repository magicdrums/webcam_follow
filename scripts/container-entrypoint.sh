#!/usr/bin/env bash
set -euo pipefail

# Rootless Podman: UID 0 del contenedor = usuario del host en bind mounts (ver /proc/self/uid_map).
is_rootless_userns() {
  local host_uid
  host_uid="$(awk '$1 == 0 { print $2; exit }' /proc/self/uid_map 2>/dev/null || true)"
  [ -n "$host_uid" ] && [ "$host_uid" != "0" ]
}

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
  echo "Usuario efectivo: $(id -u):$(id -g)" >&2
  ls -ldZ "$dir" 2>/dev/null || ls -ld "$dir" 2>/dev/null || true
  echo "En el host:" >&2
  echo "  ./scripts/fix-volume-permissions.sh" >&2
  echo "  ./scripts/compose.sh up -d" >&2
  echo "No uses 'user: 1000:1000' en compose con Podman rootless." >&2
}

run_app() {
  if [ "$(id -u)" = "0" ] && is_rootless_userns; then
    # Rootless: mantener UID 0 (mapeado al usuario del host en volúmenes).
    exec "$@"
  fi
  if [ "$(id -u)" = "0" ]; then
    exec runuser -u appuser -- "$@"
  fi
  exec "$@"
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
  run_app "$@"
fi

for dir in /app/data /app/snapshots; do
  if ! can_write_dir "$dir"; then
    report_volume_error "$dir"
    exit 1
  fi
done
run_app "$@"
