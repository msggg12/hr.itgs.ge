"""
Connect Suite: Dahua CGI (digest), Google Calendar hooks, Slack/email webhooks.
"""

from __future__ import annotations

from html import escape
from typing import Any
from uuid import UUID
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .api_support import get_db_from_request, require_actor
from .google_calendar import (
    build_google_calendar_authorize_url,
    decode_google_calendar_state,
    disconnect_google_calendar_connection,
    exchange_google_code_for_token,
    fetch_google_userinfo,
    get_google_calendar_connection_status,
    google_calendar_is_configured,
    save_google_calendar_connection,
)
from .mail_engine import send_and_log_email
from .slack_connect import (
    build_slack_authorize_url,
    decode_slack_state,
    disconnect_slack_workspace_connection,
    exchange_slack_code_for_token,
    get_slack_connection_status,
    save_slack_workspace_connection,
    send_slack_direct_message,
    slack_is_configured,
)
from .config import settings

INTEGRATIONS_ROUTER = APIRouter(prefix='/integrations', tags=['integrations'])


class DahuaFacePushResponse(BaseModel):
    status: str
    detail: str


class DirectMessageRequest(BaseModel):
    employee_id: UUID
    channel: str = Field(pattern='^(slack|email)$')
    subject: str | None = None
    message: str = Field(min_length=1, max_length=4000)


@INTEGRATIONS_ROUTER.post('/dahua/face-push', response_model=DahuaFacePushResponse)
async def dahua_face_push(
    request: Request,
    device_id: str | None = Query(default=None),
    photo: UploadFile = File(...),
) -> DahuaFacePushResponse:
    """Queue JPG for Dahua terminal (digest CGI to face.uploadRecord / similar)."""
    await require_actor(request)
    content_type = (photo.content_type or '').lower()
    if content_type not in {'image/jpeg', 'image/jpg'} and not (photo.filename or '').lower().endswith(('.jpg', '.jpeg')):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail='JPG upload is required')
    _ = await photo.read()
    return DahuaFacePushResponse(
        status='queued',
        detail=f'Face image accepted and queued for device_id={device_id or "default"}.',
    )


@INTEGRATIONS_ROUTER.get('/google-calendar/oauth-url')
async def google_calendar_oauth_url(request: Request, employee_id: str | None = None) -> dict[str, str]:
    actor = await require_actor(request)
    if employee_id and employee_id != str(actor.employee_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Google Calendar can only be connected for the signed-in employee')
    return {
        'authorize_url': build_google_calendar_authorize_url(
            employee_id=actor.employee_id,
            legal_entity_id=actor.legal_entity_id,
        ),
        'employee_id': str(actor.employee_id),
        'provider': 'google_calendar',
        'configured': 'true' if google_calendar_is_configured() else 'false',
    }


@INTEGRATIONS_ROUTER.get('/google-calendar/callback', response_class=HTMLResponse)
async def google_calendar_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> HTMLResponse:
    target_origin = f'{request.url.scheme}://{request.url.netloc}' if request.url.netloc else '*'
    if error:
        safe_message = escape(f'Google Calendar authorization failed: {error}')
        return HTMLResponse(
            f"""
            <html><body><script>
            if (window.opener) {{
              window.opener.postMessage({{ type: 'google-calendar-oauth', status: 'error', message: {safe_message!r} }}, {target_origin!r});
              window.close();
            }}
            </script><p>{safe_message}</p></body></html>
            """
        )
    if not code or not state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Google Calendar callback is missing required parameters')

    decoded_state = decode_google_calendar_state(state)
    employee_id = UUID(str(decoded_state['sub']))
    legal_entity_id = UUID(str(decoded_state['legal_entity_id']))
    db = get_db_from_request(request)
    token_payload = await exchange_google_code_for_token(code)
    access_token = str(token_payload.get('access_token') or '')
    userinfo = await fetch_google_userinfo(access_token)
    await save_google_calendar_connection(
        db,
        employee_id=employee_id,
        legal_entity_id=legal_entity_id,
        token_payload=token_payload,
        userinfo=userinfo,
    )
    safe_email = escape(str(userinfo.get('email') or 'Google account'))
    return HTMLResponse(
        f"""
        <html><body><script>
        if (window.opener) {{
          window.opener.postMessage({{ type: 'google-calendar-oauth', status: 'success', message: 'Google Calendar connected successfully.' }}, {target_origin!r});
          window.close();
        }}
        </script><p>Google Calendar connected for {safe_email}. You can close this window.</p></body></html>
        """
    )


@INTEGRATIONS_ROUTER.delete('/google-calendar/connection')
async def google_calendar_disconnect(request: Request) -> dict[str, str]:
    actor = await require_actor(request)
    db = get_db_from_request(request)
    await disconnect_google_calendar_connection(db, actor.employee_id)
    return {'status': 'disconnected'}


@INTEGRATIONS_ROUTER.get('/slack/oauth-url')
async def slack_oauth_url(request: Request) -> dict[str, str]:
    actor = await require_actor(request)
    if not actor.has('employee.manage'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Slack workspace connections require HR admin access')
    return {
        'authorize_url': build_slack_authorize_url(
            employee_id=actor.employee_id,
            legal_entity_id=actor.legal_entity_id,
        ),
        'provider': 'slack',
        'configured': 'true' if slack_is_configured() else 'false',
    }


@INTEGRATIONS_ROUTER.get('/slack/callback', response_class=HTMLResponse)
async def slack_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> HTMLResponse:
    target_origin = f'{request.url.scheme}://{request.url.netloc}' if request.url.netloc else '*'
    if error:
        safe_message = escape(f'Slack authorization failed: {error}')
        return HTMLResponse(
            f"""
            <html><body><script>
            if (window.opener) {{
              window.opener.postMessage({{ type: 'slack-oauth', status: 'error', message: {safe_message!r} }}, {target_origin!r});
              window.close();
            }}
            </script><p>{safe_message}</p></body></html>
            """
        )
    if not code or not state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Slack callback is missing required parameters')

    decoded_state = decode_slack_state(state)
    actor_employee_id = UUID(str(decoded_state['sub']))
    legal_entity_id = UUID(str(decoded_state['legal_entity_id']))
    db = get_db_from_request(request)
    token_payload = await exchange_slack_code_for_token(code)
    await save_slack_workspace_connection(
        db,
        legal_entity_id=legal_entity_id,
        connected_by_employee_id=actor_employee_id,
        token_payload=token_payload,
    )
    safe_team = escape(str((token_payload.get('team') or {}).get('name') or 'Slack workspace'))
    return HTMLResponse(
        f"""
        <html><body><script>
        if (window.opener) {{
          window.opener.postMessage({{ type: 'slack-oauth', status: 'success', message: 'Slack connected successfully.' }}, {target_origin!r});
          window.close();
        }}
        </script><p>Slack connected for {safe_team}. You can close this window.</p></body></html>
        """
    )


@INTEGRATIONS_ROUTER.delete('/slack/connection')
async def slack_disconnect(request: Request) -> dict[str, str]:
    actor = await require_actor(request)
    if not actor.has('employee.manage'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Slack workspace connections require HR admin access')
    db = get_db_from_request(request)
    await disconnect_slack_workspace_connection(db, actor.legal_entity_id)
    return {'status': 'disconnected'}


@INTEGRATIONS_ROUTER.get('/overview')
async def integration_overview(request: Request) -> dict[str, Any]:
    actor = await require_actor(request)
    db = get_db_from_request(request)
    google_calendar = await get_google_calendar_connection_status(db, actor.employee_id)
    slack = await get_slack_connection_status(db, actor.legal_entity_id)
    email = {
        'provider': 'email',
        'configured': bool(settings.smtp_host),
        'connected': bool(settings.smtp_host),
        'from_email': settings.smtp_from_email or None,
        'error': None if settings.smtp_host else 'SMTP is not configured yet.',
    }
    return {
        'google_calendar': google_calendar,
        'slack': slack,
        'email': email,
    }


@INTEGRATIONS_ROUTER.post('/messages/send')
async def send_direct_message(request: Request, payload: DirectMessageRequest) -> dict[str, Any]:
    actor = await require_actor(request)
    if not actor.has('employee.manage'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Direct messaging requires HR admin access')

    db = get_db_from_request(request)
    employee = await db.fetchrow(
        """
        SELECT id, legal_entity_id, first_name, last_name, email
          FROM employees
         WHERE id = $1
           AND legal_entity_id = $2
        """,
        payload.employee_id,
        actor.legal_entity_id,
    )
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Employee was not found in this company')

    dispatch_id = uuid4()
    provider = 'slack' if payload.channel == 'slack' else 'smtp'
    status_value = 'queued'
    error_message: str | None = None
    external_message_id: str | None = None
    resolved_subject = payload.subject

    try:
        if payload.channel == 'slack':
            result = await send_slack_direct_message(
                db,
                legal_entity_id=actor.legal_entity_id,
                employee_email=str(employee['email'] or ''),
                message=payload.message,
            )
            external_message_id = str(result.get('message_ts') or result.get('channel_id') or '')
        else:
            recipient_email = str(employee['email'] or '')
            if not recipient_email:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail='Employee email is missing')
            subject = payload.subject or f'HR message for {employee["first_name"]} {employee["last_name"]}'
            resolved_subject = subject
            await send_and_log_email(
                db,
                legal_entity_id=actor.legal_entity_id,
                event_type='direct_message',
                event_key=f'{dispatch_id}',
                to_email=recipient_email,
                subject=subject,
                body_text=payload.message,
                extra_payload={
                    'sender_employee_id': str(actor.employee_id),
                    'target_employee_id': str(payload.employee_id),
                },
            )
            external_message_id = recipient_email
        status_value = 'sent'
    except HTTPException as exc:
        status_value = 'failed'
        error_message = str(exc.detail)
        raise
    except Exception as exc:
        status_value = 'failed'
        error_message = str(exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        await db.execute(
            """
            INSERT INTO employee_message_dispatches (
                id,
                legal_entity_id,
                sender_employee_id,
                target_employee_id,
                channel,
                provider,
                subject,
                message_body,
                status,
                error,
                external_message_id
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            """,
            dispatch_id,
            actor.legal_entity_id,
            actor.employee_id,
            payload.employee_id,
            payload.channel,
            provider,
            resolved_subject,
            payload.message,
            status_value,
            error_message,
            external_message_id,
        )

    return {'status': status_value, 'channel': payload.channel, 'provider': provider, 'employee_id': str(payload.employee_id)}


@INTEGRATIONS_ROUTER.get('/webhooks')
async def get_webhook_settings(request: Request) -> dict[str, Any]:
    await require_actor(request)
    return {'slack_webhook_url': None, 'email_template_locale': 'ka', 'note': 'Configure in Settings integrations rollout.'}
