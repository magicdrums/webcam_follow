from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass
class HotZone:
    row: int
    col: int
    intensity: float
    x_pct: float
    y_pct: float

    def to_dict(self) -> dict:
        return {
            "row": self.row,
            "col": self.col,
            "intensity": round(self.intensity, 3),
            "x_pct": round(self.x_pct, 1),
            "y_pct": round(self.y_pct, 1),
        }


@dataclass
class MotionPrediction:
    active: bool = False
    from_x: float = 0.0
    from_y: float = 0.0
    to_x: float = 0.0
    to_y: float = 0.0
    speed: float = 0.0
    direction_deg: float = 0.0

    def to_dict(self) -> dict:
        return {
            "active": self.active,
            "from_x": round(self.from_x, 1),
            "from_y": round(self.from_y, 1),
            "to_x": round(self.to_x, 1),
            "to_y": round(self.to_y, 1),
            "speed": round(self.speed, 1),
            "direction_deg": round(self.direction_deg, 0),
        }


@dataclass
class MotionAnalyticsSnapshot:
    hot_zones: list[HotZone] = field(default_factory=list)
    prediction: MotionPrediction = field(default_factory=MotionPrediction)
    peak_intensity: float = 0.0

    def to_dict(self) -> dict:
        return {
            "hot_zones": [zone.to_dict() for zone in self.hot_zones],
            "prediction": self.prediction.to_dict(),
            "peak_intensity": round(self.peak_intensity, 3),
        }


class MotionAnalytics:
    """Mapa de calor acumulativo y predicción lineal del centro de movimiento."""

    GRID_COLS = 48
    GRID_ROWS = 27
    HISTORY_LEN = 12
    PREDICT_AHEAD_SEC = 0.8

    def __init__(self, decay: float = 0.96) -> None:
        self.decay = decay
        self._grid = np.zeros((self.GRID_ROWS, self.GRID_COLS), dtype=np.float32)
        self._centroid_history: deque[tuple[float, float, float]] = deque(
            maxlen=self.HISTORY_LEN
        )
        self._last_snapshot = MotionAnalyticsSnapshot()

    def reset(self) -> None:
        self._grid.fill(0)
        self._centroid_history.clear()
        self._last_snapshot = MotionAnalyticsSnapshot()

    @property
    def snapshot(self) -> MotionAnalyticsSnapshot:
        return self._last_snapshot

    def update(
        self,
        motion_mask: np.ndarray | None,
        frame_shape: tuple[int, ...],
        *,
        decay: float | None = None,
        enable_prediction: bool = True,
    ) -> MotionAnalyticsSnapshot:
        decay_rate = decay if decay is not None else self.decay
        self._grid *= decay_rate

        if motion_mask is not None and motion_mask.size > 0:
            small = cv2.resize(
                motion_mask,
                (self.GRID_COLS, self.GRID_ROWS),
                interpolation=cv2.INTER_AREA,
            )
            contribution = small.astype(np.float32) / 255.0
            self._grid = np.minimum(self._grid + contribution * 0.35, 1.0)
            self._track_centroid(motion_mask, frame_shape)

        prediction = (
            self._predict_motion() if enable_prediction else MotionPrediction()
        )
        hot_zones = self._top_zones()
        peak = float(self._grid.max()) if self._grid.size else 0.0

        self._last_snapshot = MotionAnalyticsSnapshot(
            hot_zones=hot_zones,
            prediction=prediction,
            peak_intensity=peak,
        )
        return self._last_snapshot

    def _track_centroid(
        self, motion_mask: np.ndarray, frame_shape: tuple[int, ...]
    ) -> None:
        contours, _ = cv2.findContours(
            motion_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        if not contours:
            return

        largest = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(largest)
        if area < 100:
            return

        moments = cv2.moments(largest)
        if moments["m00"] <= 0:
            return

        height, width = frame_shape[:2]
        cx = moments["m10"] / moments["m00"]
        cy = moments["m01"] / moments["m00"]
        self._centroid_history.append((time.monotonic(), cx / width * 100, cy / height * 100))

    def _predict_motion(self) -> MotionPrediction:
        if len(self._centroid_history) < 2:
            return MotionPrediction()

        t0, x0, y0 = self._centroid_history[0]
        t1, x1, y1 = self._centroid_history[-1]
        dt = t1 - t0
        if dt < 0.05:
            return MotionPrediction()

        vx = (x1 - x0) / dt
        vy = (y1 - y0) / dt
        speed = float(np.hypot(vx, vy))
        direction = float(np.degrees(np.arctan2(vy, vx)))

        ahead = self.PREDICT_AHEAD_SEC
        pred_x = max(0.0, min(100.0, x1 + vx * ahead))
        pred_y = max(0.0, min(100.0, y1 + vy * ahead))

        return MotionPrediction(
            active=speed > 0.5,
            from_x=x1,
            from_y=y1,
            to_x=pred_x,
            to_y=pred_y,
            speed=speed,
            direction_deg=direction,
        )

    def _top_zones(self, limit: int = 5) -> list[HotZone]:
        flat = self._grid.ravel()
        if flat.max() <= 0.01:
            return []

        indices = np.argpartition(flat, -limit)[-limit:]
        indices = indices[np.argsort(flat[indices])[::-1]]

        zones: list[HotZone] = []
        for idx in indices:
            value = float(flat[idx])
            if value < 0.05:
                continue
            row, col = divmod(int(idx), self.GRID_COLS)
            zones.append(
                HotZone(
                    row=row,
                    col=col,
                    intensity=value,
                    x_pct=(col + 0.5) / self.GRID_COLS * 100,
                    y_pct=(row + 0.5) / self.GRID_ROWS * 100,
                )
            )
        return zones

    def render_overlay(
        self,
        frame: np.ndarray,
        opacity: float = 0.45,
        prediction: MotionPrediction | None = None,
        show_heatmap: bool = True,
        show_prediction: bool = True,
    ) -> np.ndarray:
        output = frame.copy()
        height, width = output.shape[:2]

        if show_heatmap and self._grid.max() > 0.01:
            heat = cv2.resize(
                self._grid,
                (width, height),
                interpolation=cv2.INTER_LINEAR,
            )
            heat_u8 = (heat * 255).astype(np.uint8)
            colored = cv2.applyColorMap(heat_u8, cv2.COLORMAP_JET)
            mask = (heat > 0.08).astype(np.float32)[..., np.newaxis]
            blend = opacity * mask
            output = (
                output.astype(np.float32) * (1 - blend) + colored.astype(np.float32) * blend
            ).astype(np.uint8)

        pred = prediction or self._last_snapshot.prediction
        if show_prediction and pred.active:
            x1 = int(pred.from_x / 100 * width)
            y1 = int(pred.from_y / 100 * height)
            x2 = int(pred.to_x / 100 * width)
            y2 = int(pred.to_y / 100 * height)
            cv2.arrowedLine(output, (x1, y1), (x2, y2), (0, 255, 255), 2, tipLength=0.25)
            cv2.circle(output, (x2, y2), 8, (0, 255, 255), 2)
            cv2.putText(
                output,
                "pred",
                (x2 + 6, y2 - 6),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (0, 255, 255),
                1,
            )

        return output

    def render_heatmap_image(self) -> np.ndarray | None:
        if self._grid.max() <= 0.01:
            return None
        heat_u8 = (self._grid / max(self._grid.max(), 1e-6) * 255).astype(np.uint8)
        colored = cv2.applyColorMap(heat_u8, cv2.COLORMAP_JET)
        scale = 8
        return cv2.resize(
            colored,
            (self.GRID_COLS * scale, self.GRID_ROWS * scale),
            interpolation=cv2.INTER_NEAREST,
        )
