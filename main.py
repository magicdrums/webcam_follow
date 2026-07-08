#!/usr/bin/env python3
"""Punto de entrada: SERVICE_MODE=monolith|web|worker (default: monolith)."""

import os
import sys


def main() -> int:
    mode = os.getenv("SERVICE_MODE", "monolith").strip().lower()
    if mode == "web":
        from src.web_service import main as web_main

        return web_main()
    if mode == "worker":
        from src.worker_service import main as worker_main

        return worker_main()
    from src.app import main as monolith_main

    return monolith_main()


if __name__ == "__main__":
    raise SystemExit(main())
