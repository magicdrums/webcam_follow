from __future__ import annotations

import logging
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from src.admin.models import Camera, SnapshotSettings

logger = logging.getLogger(__name__)

_FILENAME_RE = re.compile(
    r"^(\d{8})_(\d{6})_(.+)\.(jpg|mp4)$",
    re.IGNORECASE,
)


def format_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _parse_filename(name: str) -> dict[str, str]:
    match = _FILENAME_RE.match(name)
    if not match:
        return {"event_type": "", "timestamp": "", "media_type": ""}
    date_part, time_part, event, ext = match.groups()
    try:
        ts = datetime.strptime(f"{date_part}{time_part}", "%Y%m%d%H%M%S").replace(
            tzinfo=timezone.utc
        )
        iso = ts.isoformat(timespec="seconds")
    except ValueError:
        iso = ""
    return {"event_type": event, "timestamp": iso, "media_type": ext.lower()}


def _camera_dirs(snapshot_root: Path, camera_id: str | None) -> list[tuple[str, Path]]:
    if not snapshot_root.exists():
        return []
    if camera_id:
        directory = snapshot_root / camera_id
        return [(camera_id, directory)] if directory.is_dir() else []
    return [
        (path.name, path)
        for path in sorted(snapshot_root.iterdir())
        if path.is_dir()
    ]


class SnapshotService:
    def __init__(self, snapshot_root: Path) -> None:
        self.snapshot_root = snapshot_root.resolve()

    def _safe_path(self, camera_id: str, filename: str) -> Path | None:
        safe_name = Path(filename).name
        if safe_name != filename or ".." in filename:
            return None
        target = (self.snapshot_root / camera_id / safe_name).resolve()
        try:
            target.relative_to(self.snapshot_root)
        except ValueError:
            return None
        return target if target.is_file() else None

    def list_snapshots(
        self,
        cameras: list[Camera],
        *,
        camera_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        names = {camera.id: camera.name for camera in cameras}
        items: list[dict] = []

        for cam_id, directory in _camera_dirs(self.snapshot_root, camera_id):
            if not directory.exists():
                continue
            for path in sorted(
                (*directory.glob("*.jpg"), *directory.glob("*.mp4")),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            ):
                stat = path.stat()
                meta = _parse_filename(path.name)
                suffix = path.suffix.lower()
                items.append(
                    {
                        "camera_id": cam_id,
                        "camera_name": names.get(cam_id, cam_id),
                        "filename": path.name,
                        "url": f"/snapshots/{cam_id}/{path.name}",
                        "media_type": meta.get("media_type") or suffix.lstrip("."),
                        "size_bytes": stat.st_size,
                        "size_label": format_bytes(stat.st_size),
                        "mtime": datetime.fromtimestamp(
                            stat.st_mtime, tz=timezone.utc
                        ).isoformat(timespec="seconds"),
                        "event_type": meta["event_type"],
                        "timestamp": meta["timestamp"] or None,
                    }
                )

        items.sort(key=lambda row: row["mtime"], reverse=True)
        total = len(items)
        page = items[offset : offset + limit]
        return {"total": total, "offset": offset, "limit": limit, "items": page}

    def stats(self, cameras: list[Camera]) -> dict:
        listing = self.list_snapshots(cameras, limit=1_000_000)
        total_bytes = sum(item["size_bytes"] for item in listing["items"])
        by_camera: dict[str, int] = {}
        for item in listing["items"]:
            by_camera[item["camera_id"]] = by_camera.get(item["camera_id"], 0) + 1
        return {
            "total_files": listing["total"],
            "total_bytes": total_bytes,
            "total_size_label": format_bytes(total_bytes),
            "by_camera": by_camera,
        }

    def delete(self, camera_id: str, filename: str) -> bool:
        target = self._safe_path(camera_id, filename)
        if not target:
            return False
        target.unlink(missing_ok=True)
        return True

    def delete_camera(self, camera_id: str) -> int:
        directory = self.snapshot_root / camera_id
        if not directory.is_dir():
            return 0
        count = 0
        for path in sorted(
            (*directory.glob("*.jpg"), *directory.glob("*.mp4")),
            key=lambda item: item.stat().st_mtime,
        ):
            path.unlink(missing_ok=True)
            count += 1
        return count

    def apply_retention(self, settings: SnapshotSettings) -> int:
        deleted = 0
        now = time.time()
        age_cutoff = (
            now - settings.retention_days * 86400
            if settings.retention_days > 0
            else None
        )

        for _cam_id, directory in _camera_dirs(self.snapshot_root, None):
            if not directory.is_dir():
                continue
            files = sorted(
                (*directory.glob("*.jpg"), *directory.glob("*.mp4")),
                key=lambda p: p.stat().st_mtime,
            )

            for path in list(files):
                if age_cutoff is not None and path.stat().st_mtime < age_cutoff:
                    path.unlink(missing_ok=True)
                    deleted += 1

            if settings.max_per_camera > 0:
                remaining = sorted(
                    (*directory.glob("*.jpg"), *directory.glob("*.mp4")),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                for path in remaining[settings.max_per_camera :]:
                    path.unlink(missing_ok=True)
                    deleted += 1

        if deleted:
            logger.info(
                "Retención de capturas: %d archivo(s) eliminado(s)", deleted
            )
        return deleted


class SnapshotRetentionWorker(threading.Thread):
    def __init__(
        self,
        service: SnapshotService,
        settings_provider,
    ) -> None:
        super().__init__(name="snapshot-retention", daemon=True)
        self._service = service
        self._settings_provider = settings_provider
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run_once(self) -> int:
        settings = self._settings_provider()
        return self._service.apply_retention(settings)

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                settings = self._settings_provider()
                self._service.apply_retention(settings)
                wait_sec = max(60, settings.cleanup_interval_sec)
            except Exception:
                logger.exception("Error en limpieza automática de capturas")
                wait_sec = 3600
            if self._stop.wait(wait_sec):
                break
