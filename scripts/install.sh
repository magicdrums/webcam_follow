#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

is_rpi() {
    if [[ -f /proc/device-tree/model ]] && grep -qi raspberry /proc/device-tree/model 2>/dev/null; then
        return 0
    fi
    local machine
    machine="$(uname -m)"
    [[ "$machine" == "armv7l" || "$machine" == "armv6l" || "$machine" == "aarch64" ]]
}

python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip wheel

if is_rpi; then
    echo "==> Instalando para Raspberry Pi (ARM, headless)..."
    pip install -r requirements-rpi.txt --extra-index-url https://www.piwheels.org/simple
else
    echo "==> Instalando para PC x86_64..."
    pip install -r requirements-x86.txt
fi

echo ""
echo "Instalación completada."
echo "Para streams RTSP instala ffmpeg: sudo apt install ffmpeg"
echo "Siguiente paso:"
echo "  cp .env.example .env   # configura STREAM_URL"
echo "  python main.py"
