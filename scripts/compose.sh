#!/usr/bin/env bash
# Arranca compose (Podman rootless: no fijar user: en compose).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

host_can_write() {
  local dir="$1"
  mkdir -p "$dir"
  local probe="${dir}/.compose_write_test_$$"
  if touch "$probe" 2>/dev/null; then
    rm -f "$probe"
    return 0
  fi
  return 1
}

preflight_volumes() {
  local ok=1
  for dir in data snapshots; do
    if ! host_can_write "$dir"; then
      echo "ERROR: no puedes escribir en ${dir}/ (usuario host $(id -u):$(id -g))" >&2
      ls -ldZ "$dir" 2>/dev/null || ls -ld "$dir" 2>/dev/null || true
      ok=0
    fi
  done
  if [ "$ok" -eq 0 ]; then
    echo "" >&2
    echo "  ./scripts/fix-volume-permissions.sh" >&2
    exit 1
  fi
}

case "${1:-}" in
  up|start|restart)
    preflight_volumes
    echo "Podman rootless: contenedor como root interno (mapeado a $(id -un), UID $(id -u))"
    ;;
esac

exec podman compose "$@"
