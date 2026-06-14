from __future__ import annotations

import logging
import os
import platform
import sys
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class PlatformKind(str, Enum):
    X86 = "x86"
    RPI = "rpi"


@dataclass(frozen=True)
class PlatformProfile:
    kind: PlatformKind
    label: str
    camera_width: int
    camera_height: int
    detection_interval_sec: float
    yolo_imgsz: int
    yolo_device: str
    yolo_on_motion_only: bool
    show_preview: bool
    yolo_model: str = "yolov8n.pt"
    min_motion_area: int = 1500
    person_confidence: float = 0.45
    camera_backend: str = "auto"


def is_raspberry_pi() -> bool:
    try:
        with open("/proc/device-tree/model", "rb") as device_model:
            return b"raspberry pi" in device_model.read().lower()
    except OSError:
        return False


def has_display() -> bool:
    if sys.platform in {"win32", "darwin"}:
        return True
    return bool(os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"))


def detect_platform_kind() -> PlatformKind:
    override = os.getenv("PLATFORM", "auto").strip().lower()
    if override in {"rpi", "raspberry", "raspberry_pi"}:
        return PlatformKind.RPI
    if override in {"x86", "x86_64", "desktop", "pc"}:
        return PlatformKind.X86
    if is_raspberry_pi():
        return PlatformKind.RPI
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64", "i686", "i386"}:
        return PlatformKind.X86
    if machine in {"aarch64", "armv7l", "armv6l"}:
        return PlatformKind.RPI
    return PlatformKind.X86


def profile_for(kind: PlatformKind) -> PlatformProfile:
    if kind == PlatformKind.RPI:
        return PlatformProfile(
            kind=PlatformKind.RPI,
            label="Raspberry Pi (ARM)",
            camera_width=416,
            camera_height=312,
            detection_interval_sec=2.0,
            yolo_imgsz=320,
            yolo_device="cpu",
            yolo_on_motion_only=True,
            show_preview=False,
            min_motion_area=800,
            person_confidence=0.40,
            camera_backend="v4l2",
        )

    return PlatformProfile(
        kind=PlatformKind.X86,
        label="PC x86_64",
        camera_width=640,
        camera_height=480,
        detection_interval_sec=0.5,
        yolo_imgsz=640,
        yolo_device="auto",
        yolo_on_motion_only=False,
        show_preview=True,
        camera_backend="auto",
    )


def is_container() -> bool:
    if os.getenv("CONTAINER", "").strip().lower() in {"1", "true", "yes", "on"}:
        return True
    return os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv")


def get_platform_profile() -> PlatformProfile:
    profile = profile_for(detect_platform_kind())
    if is_container():
        from dataclasses import replace

        profile = replace(profile, label=f"{profile.label} · contenedor")
    return profile


def resolve_yolo_device(device: str) -> str:
    if device != "auto":
        return device
    try:
        import torch

        if torch.cuda.is_available():
            return "0"
    except ImportError:
        pass
    return "cpu"


def log_platform_info(profile: PlatformProfile) -> None:
    logger.info(
        "Plataforma: %s | YOLO: %s en %s | Movimiento: OpenCV MOG2 | Objetos: YOLOv8",
        profile.label,
        profile.yolo_model,
        resolve_yolo_device(profile.yolo_device),
    )
    if profile.yolo_on_motion_only:
        logger.info(
            "YOLO solo se ejecuta cuando hay movimiento (optimizado para ARM)"
        )
