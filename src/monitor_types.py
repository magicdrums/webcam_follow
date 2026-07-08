from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LiveStatus:
    camera_id: str = ""
    camera_name: str = ""
    motion_detected: bool = False
    motion_area: int = 0
    object_counts: dict[str, int] = field(default_factory=dict)
    person_count: int = 0
    total_objects: int = 0
    yolo_active: bool = False
    fps: float = 0.0
    video_label: str = ""
    platform_label: str = ""
    stream_url: str = ""
    connected: bool = False
    last_update: str = ""
    hot_zones: list[dict] = field(default_factory=list)
    motion_prediction: dict = field(default_factory=dict)
    heatmap_peak: float = 0.0
    heatmap_enabled: bool = True
    surveillance_armed: bool = True


@dataclass
class AlertRecord:
    camera_id: str
    camera_name: str
    timestamp: str
    event_type: str
    message: str
    object_counts: dict[str, int]
    snapshot: str | None = None
