from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass

import cv2
import numpy as np

logger = logging.getLogger(__name__)

try:
    import mediapipe as mp

    MEDIAPIPE_AVAILABLE = True
except ImportError:  # pragma: no cover
    MEDIAPIPE_AVAILABLE = False
    mp = None  # type: ignore[assignment]

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

# Índices MediaPipe Hands
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


@dataclass
class HandGestureResult:
    gesture: str
    confidence: float
    handedness: str


def mediapipe_available() -> bool:
    return MEDIAPIPE_AVAILABLE


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


class HandGestureDetector:
    """Detecta gestos de mano con MediaPipe Hands (rule-based sobre landmarks)."""

    def __init__(
        self,
        *,
        min_detection_confidence: float = 0.6,
        min_tracking_confidence: float = 0.5,
        max_num_hands: int = 2,
    ) -> None:
        self._enabled = False
        self._hands = None
        self._min_detection = min_detection_confidence
        self._min_tracking = min_tracking_confidence
        self._max_num_hands = max(1, min(max_num_hands, 2))
        self._last_gesture_at: dict[str, float] = {}
        self._wrist_history: deque[tuple[float, float]] = deque(maxlen=24)

    def update_settings(
        self,
        *,
        min_detection_confidence: float,
        min_tracking_confidence: float,
        max_num_hands: int,
        enabled: bool,
    ) -> None:
        self._min_detection = min_detection_confidence
        self._min_tracking = min_tracking_confidence
        self._max_num_hands = max(1, min(max_num_hands, 2))
        if enabled and not self._enabled:
            self._ensure_hands()
        if not enabled and self._hands is not None:
            self._hands.close()
            self._hands = None
        self._enabled = enabled

    def _ensure_hands(self) -> bool:
        if not MEDIAPIPE_AVAILABLE:
            return False
        if self._hands is None:
            self._hands = mp.solutions.hands.Hands(
                static_image_mode=False,
                max_num_hands=self._max_num_hands,
                min_detection_confidence=self._min_detection,
                min_tracking_confidence=self._min_tracking,
            )
        return True

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

        if not MEDIAPIPE_AVAILABLE:
            return [], annotated

        if not self._ensure_hands():
            return [], annotated

        allowed = set(allowed_gestures or DEFAULT_GESTURE_TYPES)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self._hands.process(rgb)
        annotated = frame.copy()
        detected: list[HandGestureResult] = []
        now = time.monotonic()

        if not results.multi_hand_landmarks:
            return [], annotated

        mp_drawing = mp.solutions.drawing_utils
        mp_styles = mp.solutions.drawing_styles

        for hand_landmarks, handedness in zip(
            results.multi_hand_landmarks,
            results.multi_handedness or [],
        ):
            label = handedness.classification[0].label if handedness else "Unknown"
            mp_drawing.draw_landmarks(
                annotated,
                hand_landmarks,
                mp.solutions.hands.HAND_CONNECTIONS,
                mp_styles.get_default_hand_landmarks_style(),
                mp_styles.get_default_hand_connections_style(),
            )

            wrist_x, _ = _landmark_xy(hand_landmarks.landmark, _WRIST)
            self._wrist_history.append((now, wrist_x))

            gesture_id, confidence = _classify_static_gesture(
                hand_landmarks.landmark, label
            )
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
        if self._hands is not None:
            self._hands.close()
            self._hands = None
        self._enabled = False
