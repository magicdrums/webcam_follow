from __future__ import annotations

import logging
import sys

from src.admin.store import AdminStore
from src.config import load_config
from src.runtime_backend import create_backend
from src.web.server import run_server

logger = logging.getLogger(__name__)


def main() -> int:
    config = load_config()
    store = AdminStore(config.data_dir)
    backend = create_backend(config)
    try:
        run_server(backend, config, store)
    except KeyboardInterrupt:
        logger.info("Detenido por el usuario")
    return 0


if __name__ == "__main__":
    sys.exit(main())
