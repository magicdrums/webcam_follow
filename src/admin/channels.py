from __future__ import annotations

from src.admin.models import NotificationChannels
from src.config import AppConfig, EmailConfig, TelegramConfig, WebhookConfig, WhatsAppConfig, _env_bool, _env_str

SECRET_PLACEHOLDER = "__UNCHANGED__"
MASK = "••••••••"


def channels_from_app_config(config: AppConfig) -> NotificationChannels:
    return NotificationChannels(
        email_enabled=config.email.enabled,
        smtp_host=config.email.smtp_host,
        smtp_port=config.email.smtp_port,
        smtp_user=config.email.smtp_user,
        smtp_password=config.email.smtp_password,
        email_from=config.email.email_from,
        email_to=config.email.email_to,
        telegram_enabled=config.telegram.enabled,
        telegram_bot_token=config.telegram.bot_token,
        telegram_chat_id=config.telegram.chat_id,
        whatsapp_enabled=config.whatsapp.enabled,
        twilio_account_sid=config.whatsapp.account_sid,
        twilio_auth_token=config.whatsapp.auth_token,
        twilio_whatsapp_from=config.whatsapp.from_number,
        whatsapp_to=config.whatsapp.to_number,
        webhook_enabled=_env_bool("WEBHOOK_ENABLED", False),
        webhook_url=_env_str("WEBHOOK_URL", ""),
        webhook_secret=_env_str("WEBHOOK_SECRET", ""),
    )


def channels_to_email_config(channels: NotificationChannels) -> EmailConfig:
    return EmailConfig(
        enabled=channels.email_enabled,
        smtp_host=channels.smtp_host,
        smtp_port=channels.smtp_port,
        smtp_user=channels.smtp_user,
        smtp_password=channels.smtp_password,
        email_from=channels.email_from,
        email_to=channels.email_to,
    )


def channels_to_telegram_config(channels: NotificationChannels) -> TelegramConfig:
    return TelegramConfig(
        enabled=channels.telegram_enabled,
        bot_token=channels.telegram_bot_token,
        chat_id=channels.telegram_chat_id,
    )


def channels_to_whatsapp_config(channels: NotificationChannels) -> WhatsAppConfig:
    return WhatsAppConfig(
        enabled=channels.whatsapp_enabled,
        account_sid=channels.twilio_account_sid,
        auth_token=channels.twilio_auth_token,
        from_number=channels.twilio_whatsapp_from,
        to_number=channels.whatsapp_to,
    )


def channels_to_webhook_config(channels: NotificationChannels) -> WebhookConfig:
    return WebhookConfig(
        enabled=channels.webhook_enabled,
        url=channels.webhook_url,
        secret=channels.webhook_secret,
    )


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return MASK
    return value[:2] + MASK + value[-2:]


def channels_to_public_dict(channels: NotificationChannels) -> dict:
    data = channels.to_dict()
    data["smtp_password"] = MASK if channels.smtp_password else ""
    data["smtp_password_set"] = bool(channels.smtp_password)
    data["telegram_bot_token"] = mask_secret(channels.telegram_bot_token)
    data["telegram_bot_token_set"] = bool(channels.telegram_bot_token)
    data["twilio_auth_token"] = MASK if channels.twilio_auth_token else ""
    data["twilio_auth_token_set"] = bool(channels.twilio_auth_token)
    data["webhook_secret"] = MASK if channels.webhook_secret else ""
    data["webhook_secret_set"] = bool(channels.webhook_secret)
    return data


def merge_channel_updates(
    current: NotificationChannels, payload: dict
) -> NotificationChannels:
    data = current.to_dict()
    for key, value in payload.items():
        if key not in data or key == "updated_at":
            continue
        if key in {"smtp_password", "twilio_auth_token", "telegram_bot_token", "webhook_secret"}:
            text = str(value).strip()
            if not text or text == MASK or MASK in text:
                continue
        data[key] = value
    from src.admin.models import _now_iso

    data["updated_at"] = _now_iso()
    return NotificationChannels.from_dict(data)
