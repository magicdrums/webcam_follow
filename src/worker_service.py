from __future__ import annotations

import logging
import sys

from src.admin.store import AdminStore
from src.config import load_config
from src.monitor_manager import MonitorManager
from src.worker.server import run_worker_server

logger = logging.getLogger(__name__)


def main() -> int:
    config = load_config()
    store = AdminStore(config.data_dir)
    manager = MonitorManager(config, store)
    manager.start()
    try:
        run_worker_server(manager, config, store)
    except KeyboardInterrupt:
        logger.info("Detenido por el usuario")
    finally:
        manager.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
