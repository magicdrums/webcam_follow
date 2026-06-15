from __future__ import annotations

from dataclasses import replace

from src.admin.models import YoloSettings
from src.config import DEFAULT_DETECT_CLASSES, DetectionConfig, _parse_detect_classes

# Dataset COCO (80 clases) — IDs estándar YOLOv8
COCO_CLASSES: list[dict[str, str | int]] = [
    {"id": 0, "name": "person", "label": "Persona"},
    {"id": 1, "name": "bicycle", "label": "Bicicleta"},
    {"id": 2, "name": "car", "label": "Coche"},
    {"id": 3, "name": "motorcycle", "label": "Moto"},
    {"id": 4, "name": "airplane", "label": "Avión"},
    {"id": 5, "name": "bus", "label": "Autobús"},
    {"id": 6, "name": "train", "label": "Tren"},
    {"id": 7, "name": "truck", "label": "Camión"},
    {"id": 8, "name": "boat", "label": "Barco"},
    {"id": 14, "name": "bird", "label": "Pájaro"},
    {"id": 15, "name": "cat", "label": "Gato"},
    {"id": 16, "name": "dog", "label": "Perro"},
    {"id": 17, "name": "horse", "label": "Caballo"},
    {"id": 18, "name": "sheep", "label": "Oveja"},
    {"id": 19, "name": "cow", "label": "Vaca"},
    {"id": 20, "name": "elephant", "label": "Elefante"},
    {"id": 21, "name": "bear", "label": "Oso"},
    {"id": 22, "name": "zebra", "label": "Cebra"},
    {"id": 23, "name": "giraffe", "label": "Jirafa"},
    {"id": 24, "name": "backpack", "label": "Mochila"},
    {"id": 25, "name": "umbrella", "label": "Paraguas"},
    {"id": 26, "name": "handbag", "label": "Bolso"},
    {"id": 27, "name": "tie", "label": "Corbata"},
    {"id": 28, "name": "suitcase", "label": "Maleta"},
    {"id": 32, "name": "sports ball", "label": "Pelota"},
    {"id": 39, "name": "bottle", "label": "Botella"},
    {"id": 41, "name": "cup", "label": "Taza"},
    {"id": 56, "name": "chair", "label": "Silla"},
    {"id": 57, "name": "couch", "label": "Sofá"},
    {"id": 58, "name": "potted plant", "label": "Planta"},
    {"id": 59, "name": "bed", "label": "Cama"},
    {"id": 60, "name": "dining table", "label": "Mesa"},
    {"id": 62, "name": "tv", "label": "TV"},
    {"id": 63, "name": "laptop", "label": "Portátil"},
    {"id": 64, "name": "mouse", "label": "Ratón"},
    {"id": 65, "name": "remote", "label": "Mando"},
    {"id": 66, "name": "keyboard", "label": "Teclado"},
    {"id": 67, "name": "cell phone", "label": "Móvil"},
    {"id": 72, "name": "refrigerator", "label": "Nevera"},
    {"id": 73, "name": "book", "label": "Libro"},
]

DETECT_PRESETS = {
    "default": {
        "label": "Vigilancia (predeterminado)",
        "mode": "default",
        "ids": DEFAULT_DETECT_CLASSES,
    },
    "people": {
        "label": "Solo personas",
        "mode": "custom",
        "ids": "0",
    },
    "people_vehicles": {
        "label": "Personas y vehículos",
        "mode": "custom",
        "ids": "0,1,2,3,5,7",
    },
    "all": {
        "label": "Todas las clases COCO (80)",
        "mode": "all",
        "ids": "",
    },
}


def resolve_detect_classes(settings: YoloSettings) -> list[int] | None:
    mode = settings.detect_classes_mode
    if mode == "all":
        return None
    if mode == "custom":
        raw = settings.detect_classes_custom.strip()
        if not raw:
            return _parse_detect_classes(DEFAULT_DETECT_CLASSES)
        return _parse_detect_classes(raw)
    return _parse_detect_classes(DEFAULT_DETECT_CLASSES)


def build_detection_config(
    base: DetectionConfig, settings: YoloSettings
) -> DetectionConfig:
    return replace(
        base,
        motion_threshold=settings.motion_threshold,
        min_motion_area=settings.min_motion_area,
        yolo_confidence=settings.yolo_confidence,
        detection_interval_sec=settings.detection_interval_sec,
        save_snapshots=settings.save_snapshots,
        snapshot_event_types=tuple(settings.snapshot_event_types),
        snapshot_cooldown_sec=settings.snapshot_cooldown_sec,
        snapshot_min_persons=settings.snapshot_min_persons,
        yolo_model=settings.yolo_model,
        yolo_device=settings.yolo_device,
        yolo_imgsz=settings.yolo_imgsz,
        yolo_on_motion_only=settings.yolo_on_motion_only,
        detect_classes=resolve_detect_classes(settings),
        hand_gesture_enabled=settings.hand_gesture_enabled,
        hand_gesture_min_confidence=settings.hand_gesture_min_confidence,
        hand_gesture_cooldown_sec=settings.hand_gesture_cooldown_sec,
        hand_gesture_on_motion_only=settings.hand_gesture_on_motion_only,
        hand_gesture_types=tuple(settings.hand_gesture_types),
        hand_max_num_hands=settings.hand_max_num_hands,
    )


def yolo_settings_to_public_dict(settings: YoloSettings) -> dict:
    data = settings.to_dict()
    data["detect_class_ids"] = resolve_detect_classes(settings)
    return data


def merge_yolo_updates(current: YoloSettings, payload: dict) -> YoloSettings:
    data = current.to_dict()
    allowed = {
        "yolo_confidence",
        "yolo_imgsz",
        "yolo_on_motion_only",
        "yolo_model",
        "yolo_device",
        "detect_classes_mode",
        "detect_classes_custom",
        "motion_threshold",
        "min_motion_area",
        "detection_interval_sec",
        "save_snapshots",
        "snapshot_event_types",
        "snapshot_cooldown_sec",
        "snapshot_min_persons",
        "motion_recording_enabled",
        "motion_recording_duration_sec",
        "motion_recording_cooldown_sec",
        "heatmap_enabled",
        "heatmap_opacity",
        "heatmap_decay",
        "motion_prediction_enabled",
        "hand_gesture_enabled",
        "hand_gesture_min_confidence",
        "hand_gesture_cooldown_sec",
        "hand_gesture_on_motion_only",
        "hand_gesture_types",
        "hand_max_num_hands",
    }
    for key in allowed:
        if key in payload:
            data[key] = payload[key]
    from src.admin.models import _now_iso

    data["updated_at"] = _now_iso()
    return YoloSettings.from_dict(data)
