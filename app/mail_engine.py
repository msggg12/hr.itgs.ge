from __future__ import annotations

import asyncio
import json
import smtplib
from email.message import EmailMessage
from typing import Any
from uuid import UUID

from .config import settings
from .db import Database


async def send_email(
    *,
    to_email: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
) -> None:
    if not settings.smtp_host:
        raise RuntimeError('SMTP is not configured')

    message = EmailMessage()
    message['Subject'] = subject
    message['From'] = settings.smtp_from_email
    message['To'] = to_email
    message.set_content(body_text)
    if body_html:
        message.add_alternative(body_html, subtype='html')

    def _deliver() -> None:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as client:
            if settings.smtp_use_tls:
                client.starttls()
            if settings.smtp_username:
                client.login(settings.smtp_username, settings.smtp_password)
            client.send_message(message)

    await asyncio.to_thread(_deliver)


async def send_and_log_email(
    db: Database,
    *,
    legal_entity_id: UUID,
    event_type: str,
    event_key: str,
    to_email: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
    extra_payload: dict[str, Any] | None = None,
) -> None:
    payload = {
        'channel': 'smtp',
        'to_email': to_email,
        'subject': subject,
        **(extra_payload or {}),
    }
    try:
        await send_email(to_email=to_email, subject=subject, body_text=body_text, body_html=body_html)
        payload['status'] = 'sent'
    except Exception as exc:
        payload['status'] = 'failed'
        payload['error'] = str(exc)
        raise
    finally:
        await db.execute(
            """
            INSERT INTO automation_dispatch_log (legal_entity_id, event_type, event_key, payload)
            VALUES ($1, $2, $3, $4::jsonb)
            ON CONFLICT (event_type, event_key) DO UPDATE
               SET payload = EXCLUDED.payload,
                   dispatched_at = now()
            """,
            legal_entity_id,
            event_type,
            event_key,
            json.dumps(payload),
        )
