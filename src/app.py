from __future__ import annotations

import logging
import sys

import cv2

from src.admin.store import AdminStore
from src.config import load_config
from src.monitor_manager import MonitorManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> int:
    config = load_config()
    store = AdminStore(config.data_dir)
    manager = MonitorManager(config, store)

    if config.web.enabled:
        manager.start()
        try:
            from src.web.server import run_server

            run_server(manager, config, store)
        except KeyboardInterrupt:
            logger.info("Detenido por el usuario")
        finally:
            manager.stop()
        return 0

    manager.start()
    try:
        if config.detection.show_preview:
            return _run_with_opencv_preview(manager)
        import time

        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Detenido por el usuario")
    finally:
        manager.stop()
    return 0


def _run_with_opencv_preview(manager: MonitorManager) -> int:
    import time

    logger.info("Vista previa OpenCV activa (pulsa 'q' para salir)")
    try:
        while True:
            frame_bytes = manager.get_jpeg_frame()
            if frame_bytes:
                import numpy as np

                arr = np.frombuffer(frame_bytes, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if frame is not None:
                    cv2.imshow("Webcam Follow", frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
            time.sleep(0.03)
    except KeyboardInterrupt:
        logger.info("Detenido por el usuario")
    finally:
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
