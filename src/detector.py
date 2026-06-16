from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

import cv2
import numpy as np

from src.config import DetectionConfig
from src.hand_gestures import (
    DEFAULT_GESTURE_TYPES,
    GESTURE_LABELS,
    HandGestureDetector,
)
from src.platform import resolve_yolo_device

try:
    from ultralytics import YOLO
except ImportError:  # pragma: no cover
    YOLO = None  # type: ignore[misc, assignment]

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    MOTION = "movimiento"
    OBJECT = "objeto_detectado"
    OBJECT_CHANGE = "cambio_objetos"
    SCENE_CHANGE = "cambio_escena"
    HAND_GESTURE = "gesto_mano"


@dataclass
class DetectedObject:
    label: str
    confidence: float
    bbox: tuple[int, int, int, int]


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


@dataclass
class DetectionState:
    last_object_counts: dict[str, int] = field(default_factory=dict)
    last_scene_hash: int | None = None


def _format_object_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "ninguno"
    return ", ".join(f"{label}: {count}" for label, count in sorted(counts.items()))


class VisionDetector:
    """
    Movimiento: OpenCV MOG2.
    Personas y objetos: YOLOv8 (clases COCO configurables).
    Gestos de mano: MediaPipe Hands (opcional).
    """

    def __init__(self, config: DetectionConfig) -> None:
        self.config = config
        self._device = resolve_yolo_device(config.yolo_device)
        self._bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=500, varThreshold=16, detectShadows=True
        )
        self._state = DetectionState()
        self._model = self._load_model()
        self._hand_gestures = HandGestureDetector(
            max_num_hands=config.hand_max_num_hands,
        )
        self._sync_hand_gesture_settings()

    def _load_model(self):
        if YOLO is None:
            raise RuntimeError(
                "ultralytics no está instalado. Ejecuta: ./scripts/install.sh"
            )
        return YOLO(self.config.yolo_model)

    def update_config(self, config: DetectionConfig) -> None:
        model_changed = config.yolo_model != self.config.yolo_model
        device_changed = config.yolo_device != self.config.yolo_device
        self.config = config
        if device_changed:
            self._device = resolve_yolo_device(config.yolo_device)
        if model_changed:
            self._model = self._load_model()
        self._sync_hand_gesture_settings()

    def _sync_hand_gesture_settings(self) -> None:
        try:
            self._hand_gestures.update_settings(
                min_detection_confidence=0.6,
                min_tracking_confidence=0.5,
                max_num_hands=self.config.hand_max_num_hands,
                enabled=self.config.hand_gesture_enabled
                and self.config.surveillance_armed,
            )
        except Exception:
            logger.exception("No se pudo sincronizar gestos de mano; se desactivan temporalmente")

    def _detect_motion(self, frame: np.ndarray) -> tuple[bool, int, np.ndarray]:
        fg_mask = self._bg_subtractor.apply(frame)
        _, thresh = cv2.threshold(
            fg_mask, self.config.motion_threshold, 255, cv2.THRESH_BINARY
        )
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=2)
        thresh = cv2.dilate(thresh, kernel, iterations=2)

        contours, _ = cv2.findContours(
            thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        total_area = 0
        for contour in contours:
            area = cv2.contourArea(contour)
            if area >= self.config.min_motion_area:
                total_area += int(area)

        motion_detected = total_area >= self.config.min_motion_area
        return motion_detected, total_area, thresh

    def _detect_objects(self, frame: np.ndarray) -> tuple[dict[str, int], list[DetectedObject]]:
        predict_kwargs: dict = {
            "verbose": False,
            "conf": self.config.yolo_confidence,
            "device": self._device,
            "imgsz": self.config.yolo_imgsz,
        }
        if self.config.detect_classes is not None:
            predict_kwargs["classes"] = self.config.detect_classes

        results = self._model.predict(frame, **predict_kwargs)
        counts: dict[str, int] = {}
        objects: list[DetectedObject] = []

        for result in results:
            if result.boxes is None:
                continue
            names = result.names
            for box in result.boxes:
                cls_id = int(box.cls[0])
                label = names[cls_id]
                confidence = float(box.conf[0])
                x1, y1, x2, y2 = map(int, box.xyxy[0].cpu().numpy())
                counts[label] = counts.get(label, 0) + 1
                objects.append(
                    DetectedObject(
                        label=label,
                        confidence=confidence,
                        bbox=(x1, y1, x2, y2),
                    )
                )

        return counts, objects

    def _scene_hash(self, frame: np.ndarray) -> int:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (32, 32))
        return int(small.mean() * 1000 + small.std() * 10)

    def analyze(
        self, frame: np.ndarray
    ) -> tuple[list[DetectionEvent], np.ndarray, np.ndarray | None]:
        motion_detected, motion_area, motion_mask = self._detect_motion(frame)
        annotated = frame.copy()

        if not self.config.surveillance_armed:
            events: list[DetectionEvent] = []
            if motion_detected:
                events.append(
                    DetectionEvent(
                        event_type=EventType.MOTION,
                        message=f"Movimiento detectado (área: {motion_area}px)",
                        object_counts={},
                        motion_area=motion_area,
                    )
                )
            return events, annotated, motion_mask

        events: list[DetectionEvent] = []

        run_yolo = motion_detected or not self.config.yolo_on_motion_only
        if run_yolo:
            object_counts, detected_objects = self._detect_objects(frame)
        else:
            object_counts = dict(self._state.last_object_counts)
            detected_objects = []

        scene_hash = self._scene_hash(frame)
        total_objects = sum(object_counts.values())

        if motion_detected:
            events.append(
                DetectionEvent(
                    event_type=EventType.MOTION,
                    message=f"Movimiento detectado (área: {motion_area}px)",
                    object_counts=object_counts,
                    motion_area=motion_area,
                )
            )

        if total_objects > 0:
            prev_total = sum(self._state.last_object_counts.values())
            if prev_total == 0:
                events.append(
                    DetectionEvent(
                        event_type=EventType.OBJECT,
                        message=f"Objetos detectados: {_format_object_counts(object_counts)}",
                        object_counts=object_counts,
                        motion_area=motion_area,
                    )
                )

        if object_counts != self._state.last_object_counts and (
            self._state.last_object_counts or object_counts
        ):
            events.append(
                DetectionEvent(
                    event_type=EventType.OBJECT_CHANGE,
                    message=(
                        f"Cambio de objetos: "
                        f"{_format_object_counts(self._state.last_object_counts)} → "
                        f"{_format_object_counts(object_counts)}"
                    ),
                    object_counts=object_counts,
                    motion_area=motion_area,
                )
            )

        if (
            self._state.last_scene_hash is not None
            and abs(scene_hash - self._state.last_scene_hash) > 500
            and motion_detected
        ):
            events.append(
                DetectionEvent(
                    event_type=EventType.SCENE_CHANGE,
                    message="Cambio significativo en la escena",
                    object_counts=object_counts,
                    motion_area=motion_area,
                )
            )

        self._state.last_object_counts = dict(object_counts)
        self._state.last_scene_hash = scene_hash

        gesture_results, annotated = self._hand_gestures.analyze(
            annotated,
            enabled=self.config.hand_gesture_enabled,
            allowed_gestures=self.config.hand_gesture_types,
            min_confidence=self.config.hand_gesture_min_confidence,
            cooldown_sec=self.config.hand_gesture_cooldown_sec,
            motion_detected=motion_detected,
            on_motion_only=self.config.hand_gesture_on_motion_only,
        )
        for result in gesture_results:
            label = GESTURE_LABELS.get(result.gesture, result.gesture)
            events.append(
                DetectionEvent(
                    event_type=EventType.HAND_GESTURE,
                    message=(
                        f"Gesto detectado: {label} "
                        f"({result.handedness}, {result.confidence:.0%})"
                    ),
                    object_counts=object_counts,
                    motion_area=motion_area,
                    gesture=result.gesture,
                    gesture_confidence=result.confidence,
                )
            )

        for obj in detected_objects:
            x1, y1, x2, y2 = obj.bbox
            color = (0, 255, 0) if obj.label == "person" else (0, 165, 255)
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
            cv2.putText(
                annotated,
                f"{obj.label} {obj.confidence:.0%}",
                (x1, max(y1 - 8, 0)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                1,
            )

        yolo_status = "YOLO activo" if run_yolo else "YOLO en reposo"
        status = (
            f"Objetos: {total_objects} | "
            f"Movimiento: {'SI' if motion_detected else 'NO'} | {yolo_status}"
        )
        cv2.putText(
            annotated,
            status,
            (10, 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            2,
        )

        return events, annotated, motion_mask if motion_detected else None
