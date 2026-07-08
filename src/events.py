from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class EventType(str, Enum):
    MOTION = "movimiento"
    OBJECT = "objeto_detectado"
    OBJECT_CHANGE = "cambio_objetos"
    SCENE_CHANGE = "cambio_escena"
    HAND_GESTURE = "gesto_mano"


@dataclass
class DetectionEvent:
    event_type: EventType
    message: str
    object_counts: dict[str, int] = field(default_factory=dict)
    motion_area: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    gesture: str | None = None
    gesture_confidence: float = 0.0

    @property
    def person_count(self) -> int:
        return self.object_counts.get("person", 0)
