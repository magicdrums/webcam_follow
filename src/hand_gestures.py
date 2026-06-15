from __future__ import annotations

import logging
import os
import time
import urllib.request
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

MEDIAPIPE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
)

HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (0, 9), (9, 10), (10, 11), (11, 12),
    (0, 13), (13, 14), (14, 15), (15, 16),
    (0, 17), (17, 18), (18, 19), (19, 20),
    (5, 9), (9, 13), (13, 17),
]

GESTURE_LABELS: dict[str, str] = {
    "mano_abierta": "Mano abierta",
    "punio": "Puño",
    "pulgar_arriba": "Pulgar arriba",
    "pulgar_abajo": "Pulgar abajo",
    "paz": "Paz / victoria",
    "saludo": "Saludo (movimiento)",
}

DEFAULT_GESTURE_TYPES = [
    "mano_abierta",
    "punio",
    "pulgar_arriba",
    "saludo",
]

_WRIST = 0
_THUMB_TIP = 4
_THUMB_IP = 3
_THUMB_MCP = 2
_INDEX_TIP = 8
_INDEX_PIP = 6
_MIDDLE_TIP = 12
_MIDDLE_PIP = 10
_RING_TIP = 16
_RING_PIP = 14
_PINKY_TIP = 20
_PINKY_PIP = 18

_MEDIAPIPE_TASKS_OK = False
_mp = None
_vision = None
_model_download_attempted = False


def _try_import_mediapipe_tasks() -> bool:
    global _MEDIAPIPE_TASKS_OK, _mp, _vision
    if _MEDIAPIPE_TASKS_OK:
        return True
    try:
        import mediapipe as mp
        from mediapipe.tasks.python import vision

        _mp = mp
        _vision = vision
        _MEDIAPIPE_TASKS_OK = True
        return True
    except ImportError:
        return False


def _model_candidates() -> list[Path]:
    repo_root = Path(__file__).resolve().parent.parent
    env_path = os.getenv("HAND_LANDMARKER_MODEL", "").strip()
    paths: list[Path] = []
    if env_path:
        paths.append(Path(env_path))
    paths.extend(
        [
            repo_root / "models" / "hand_landmarker.task",
            Path("/app/models/hand_landmarker.task"),
            repo_root / "data" / "models" / "hand_landmarker.task",
            Path("/app/data/models/hand_landmarker.task"),
        ]
    )
    return paths


def _resolve_model_path() -> Path | None:
    for candidate in _model_candidates():
        if candidate.is_file():
            return candidate
    return None


def _download_model() -> Path | None:
    global _model_download_attempted
    if _model_download_attempted:
        return _resolve_model_path()
    _model_download_attempted = True

    env_path = os.getenv("HAND_LANDMARKER_MODEL", "").strip()
    if env_path:
        target = Path(env_path)
    else:
        target = (
            Path(__file__).resolve().parent.parent / "models" / "hand_landmarker.task"
        )

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Descargando modelo MediaPipe Hands → %s", target)
        urllib.request.urlretrieve(MEDIAPIPE_MODEL_URL, target)
        if target.is_file() and target.stat().st_size > 1024:
            return target
    except Exception:
        logger.exception("No se pudo descargar hand_landmarker.task")
    return None


def mediapipe_available() -> bool:
    if not _try_import_mediapipe_tasks():
        return False
    return _resolve_model_path() is not None or True


@dataclass
class HandGestureResult:
    gesture: str
    confidence: float
    handedness: str


def _landmark_xy(landmarks, index: int) -> tuple[float, float]:
    point = landmarks[index]
    return point.x, point.y


def _finger_extended(landmarks, tip_id: int, pip_id: int) -> bool:
    _, tip_y = _landmark_xy(landmarks, tip_id)
    _, pip_y = _landmark_xy(landmarks, pip_id)
    return tip_y < pip_y


def _thumb_extended(landmarks, handedness: str) -> bool:
    tip_x, _ = _landmark_xy(landmarks, _THUMB_TIP)
    ip_x, _ = _landmark_xy(landmarks, _THUMB_IP)
    if handedness.lower().startswith("right"):
        return tip_x < ip_x
    return tip_x > ip_x


def _thumb_pointing_down(landmarks) -> bool:
    tip_y = _landmark_xy(landmarks, _THUMB_TIP)[1]
    mcp_y = _landmark_xy(landmarks, _THUMB_MCP)[1]
    return tip_y > mcp_y + 0.02


def _classify_static_gesture(landmarks, handedness: str) -> tuple[str | None, float]:
    thumb = _thumb_extended(landmarks, handedness)
    index = _finger_extended(landmarks, _INDEX_TIP, _INDEX_PIP)
    middle = _finger_extended(landmarks, _MIDDLE_TIP, _MIDDLE_PIP)
    ring = _finger_extended(landmarks, _RING_TIP, _RING_PIP)
    pinky = _finger_extended(landmarks, _PINKY_TIP, _PINKY_PIP)
    fingers = [thumb, index, middle, ring, pinky]

    if thumb and not any([index, middle, ring, pinky]) and not _thumb_pointing_down(landmarks):
        return "pulgar_arriba", 0.9
    if thumb and not any([index, middle, ring, pinky]) and _thumb_pointing_down(landmarks):
        return "pulgar_abajo", 0.85
    if index and middle and not ring and not pinky and not thumb:
        return "paz", 0.85
    if all(fingers):
        return "mano_abierta", 0.88
    if not any(fingers):
        return "punio", 0.88
    return None, 0.0


def _draw_hand_landmarks(image: np.ndarray, landmarks) -> None:
    height, width = image.shape[:2]

    def point(idx: int) -> tuple[int, int]:
        lm = landmarks[idx]
        return int(lm.x * width), int(lm.y * height)

    for start, end in HAND_CONNECTIONS:
        cv2.line(image, point(start), point(end), (80, 200, 255), 2)
    for idx in range(21):
        cv2.circle(image, point(idx), 3, (255, 220, 80), -1)


class HandGestureDetector:
    """Detecta gestos de mano con MediaPipe Tasks (Hand Landmarker)."""

    def __init__(
        self,
        *,
        min_detection_confidence: float = 0.6,
        min_tracking_confidence: float = 0.5,
        max_num_hands: int = 2,
    ) -> None:
        self._enabled = False
        self._landmarker = None
        self._min_detection = min_detection_confidence
        self._min_tracking = min_tracking_confidence
        self._max_num_hands = max(1, min(max_num_hands, 2))
        self._last_gesture_at: dict[str, float] = {}
        self._wrist_history: deque[tuple[float, float]] = deque(maxlen=24)
        self._frame_timestamp_ms = 0
        self._init_error_logged = False

    def update_settings(
        self,
        *,
        min_detection_confidence: float,
        min_tracking_confidence: float,
        max_num_hands: int,
        enabled: bool,
    ) -> None:
        try:
            settings_changed = (
                abs(min_detection_confidence - self._min_detection) > 1e-6
                or abs(min_tracking_confidence - self._min_tracking) > 1e-6
                or max(1, min(max_num_hands, 2)) != self._max_num_hands
            )
            self._min_detection = min_detection_confidence
            self._min_tracking = min_tracking_confidence
            self._max_num_hands = max(1, min(max_num_hands, 2))

            if enabled and (not self._enabled or settings_changed):
                self._close_landmarker()
                if not self._ensure_landmarker():
                    enabled = False
            if not enabled:
                self._close_landmarker()
            self._enabled = enabled
        except Exception:
            logger.exception("Error configurando gestos de mano; se desactivan")
            self._close_landmarker()
            self._enabled = False

    def _ensure_landmarker(self) -> bool:
        if self._landmarker is not None:
            return True
        if not _try_import_mediapipe_tasks():
            if not self._init_error_logged:
                logger.warning("MediaPipe Tasks no disponible; gestos de mano desactivados")
                self._init_error_logged = True
            return False

        model_path = _resolve_model_path() or _download_model()
        if model_path is None:
            if not self._init_error_logged:
                logger.warning(
                    "Modelo hand_landmarker.task no encontrado; gestos de mano desactivados"
                )
                self._init_error_logged = True
            return False

        try:
            options = _vision.HandLandmarkerOptions(
                base_options=_mp.tasks.BaseOptions(model_asset_path=str(model_path)),
                running_mode=_vision.RunningMode.VIDEO,
                num_hands=self._max_num_hands,
                min_hand_detection_confidence=self._min_detection,
                min_hand_presence_confidence=self._min_tracking,
                min_tracking_confidence=self._min_tracking,
            )
            self._landmarker = _vision.HandLandmarker.create_from_options(options)
            self._frame_timestamp_ms = 0
            self._init_error_logged = False
            logger.info("MediaPipe Hand Landmarker listo (%s)", model_path.name)
            return True
        except Exception:
            logger.exception("No se pudo iniciar MediaPipe Hand Landmarker")
            self._landmarker = None
            return False

    def _close_landmarker(self) -> None:
        if self._landmarker is not None:
            self._landmarker.close()
            self._landmarker = None
        self._frame_timestamp_ms = 0

    def _detect_wave(self) -> tuple[bool, float]:
        if len(self._wrist_history) < 10:
            return False, 0.0
        xs = [item[1] for item in self._wrist_history]
        if max(xs) - min(xs) < 0.12:
            return False, 0.0
        direction_changes = 0
        prev_delta = 0.0
        for i in range(1, len(xs)):
            delta = xs[i] - xs[i - 1]
            if abs(delta) < 0.008:
                continue
            if prev_delta != 0.0 and (delta > 0) != (prev_delta > 0):
                direction_changes += 1
            prev_delta = delta
        if direction_changes >= 2:
            return True, min(0.95, 0.7 + direction_changes * 0.05)
        return False, 0.0

    def analyze(
        self,
        frame: np.ndarray,
        *,
        enabled: bool,
        allowed_gestures: tuple[str, ...],
        min_confidence: float,
        cooldown_sec: float,
        motion_detected: bool,
        on_motion_only: bool,
    ) -> tuple[list[HandGestureResult], np.ndarray]:
        annotated = frame
        if not enabled:
            self.update_settings(
                min_detection_confidence=self._min_detection,
                min_tracking_confidence=self._min_tracking,
                max_num_hands=self._max_num_hands,
                enabled=False,
            )
            return [], annotated

        if on_motion_only and not motion_detected:
            return [], annotated

        if not self._ensure_landmarker() or self._landmarker is None:
            return [], annotated

        allowed = set(allowed_gestures or DEFAULT_GESTURE_TYPES)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        if not rgb.flags["C_CONTIGUOUS"]:
            rgb = np.ascontiguousarray(rgb)

        self._frame_timestamp_ms += 33
        mp_image = _mp.Image(image_format=_mp.ImageFormat.SRGB, data=rgb)
        try:
            results = self._landmarker.detect_for_video(mp_image, self._frame_timestamp_ms)
        except Exception:
            logger.exception("Error detectando manos con MediaPipe")
            return [], frame

        annotated = frame.copy()
        detected: list[HandGestureResult] = []
        now = time.monotonic()

        if not results.hand_landmarks:
            return [], annotated

        for index, hand_landmarks in enumerate(results.hand_landmarks):
            label = "Unknown"
            if results.handedness and index < len(results.handedness):
                categories = results.handedness[index]
                if categories:
                    label = categories[0].category_name

            _draw_hand_landmarks(annotated, hand_landmarks)

            wrist_x, _ = _landmark_xy(hand_landmarks, _WRIST)
            self._wrist_history.append((now, wrist_x))

            gesture_id, confidence = _classify_static_gesture(hand_landmarks, label)
            wave_ok, wave_conf = self._detect_wave()
            if wave_ok and "saludo" in allowed and wave_conf >= min_confidence:
                gesture_id, confidence = "saludo", wave_conf

            if not gesture_id or gesture_id not in allowed:
                continue
            if confidence < min_confidence:
                continue

            last_at = self._last_gesture_at.get(gesture_id, 0.0)
            if cooldown_sec > 0 and now - last_at < cooldown_sec:
                continue

            self._last_gesture_at[gesture_id] = now
            detected.append(
                HandGestureResult(
                    gesture=gesture_id,
                    confidence=confidence,
                    handedness=label,
                )
            )
            cv2.putText(
                annotated,
                f"{GESTURE_LABELS.get(gesture_id, gesture_id)} {confidence:.0%}",
                (10, annotated.shape[0] - 20 - 22 * len(detected)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (255, 220, 80),
                2,
            )

        return detected, annotated

    def close(self) -> None:
        self._close_landmarker()
        self._enabled = False
