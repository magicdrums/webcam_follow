from __future__ import annotations

from src.admin.models import TuyaConfig

MASK = "••••••••"


def tuya_to_public_dict(config: TuyaConfig) -> dict:
    data = config.to_dict()
    data["access_key"] = MASK if config.access_key else ""
    data["access_key_set"] = bool(config.access_key)
    return data


def merge_tuya_updates(current: TuyaConfig, payload: dict) -> TuyaConfig:
    data = current.to_dict()
    for key, value in payload.items():
        if key not in data or key == "updated_at":
            continue
        if key == "access_key":
            text = str(value).strip()
            if not text or text == MASK or MASK in text:
                continue
        data[key] = value
    from src.admin.models import _now_iso

    data["updated_at"] = _now_iso()
    return TuyaConfig.from_dict(data)
