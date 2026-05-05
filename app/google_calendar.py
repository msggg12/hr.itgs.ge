from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import jwt
from fastapi import HTTPException, status

from .config import settings
from .db import Database

GOOGLE_OAUTH_SCOPE = 'openid email profile https://www.googleapis.com/auth/calendar.readonly'
GOOGLE_AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
GOOGLE_USERINFO_URL = 'https://openidconnect.googleapis.com/v1/userinfo'
GOOGLE_CALENDAR_EVENTS_URL = 'https://www.googleapis.com/calendar/v3/calendars/primary/events'


def google_calendar_is_configured() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret and google_calendar_redirect_uri())


def google_calendar_redirect_uri() -> str:
    if settings.google_redirect_uri:
        return settings.google_redirect_uri
    if settings.public_base_url:
        return f'{settings.public_base_url}/integrations/google-calendar/callback'
    return ''


def build_google_calendar_state(*, employee_id: UUID, legal_entity_id: UUID) -> str:
    issued_at = datetime.now(UTC)
    payload = {
        'sub': str(employee_id),
        'legal_entity_id': str(legal_entity_id),
        'type': 'google_calendar_state',
        'iat': int(issued_at.timestamp()),
        'exp': int((issued_at + timedelta(minutes=15)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_google_calendar_state(state_token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(state_token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Google Calendar authorization state is invalid') from exc
    if payload.get('type') != 'google_calendar_state':
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Google Calendar authorization state is invalid')
    return payload


def build_google_calendar_authorize_url(*, employee_id: UUID, legal_entity_id: UUID) -> str:
    if not google_calendar_is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail='Google Calendar integration is not configured on this server',
        )
    state_token = build_google_calendar_state(employee_id=employee_id, legal_entity_id=legal_entity_id)
    query = httpx.QueryParams(
        {
            'client_id': settings.google_client_id,
            'redirect_uri': google_calendar_redirect_uri(),
            'response_type': 'code',
            'scope': GOOGLE_OAUTH_SCOPE,
            'access_type': 'offline',
            'include_granted_scopes': 'true',
            'prompt': 'consent',
            'state': state_token,
        }
    )
    return f'{GOOGLE_AUTH_URL}?{query}'


async def exchange_google_code_for_token(code: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                'code': code,
                'client_id': settings.google_client_id,
                'client_secret': settings.google_client_secret,
                'redirect_uri': google_calendar_redirect_uri(),
                'grant_type': 'authorization_code',
            },
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Google Calendar authorization failed')
    return response.json()


async def refresh_google_access_token(refresh_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                'client_id': settings.google_client_id,
                'client_secret': settings.google_client_secret,
                'refresh_token': refresh_token,
                'grant_type': 'refresh_token',
            },
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Google Calendar token refresh failed')
    return response.json()


async def fetch_google_userinfo(access_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            GOOGLE_USERINFO_URL,
            headers={'Authorization': f'Bearer {access_token}'},
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Google Calendar account lookup failed')
    return response.json()


def _expiry_from_token_payload(payload: dict[str, Any]) -> datetime | None:
    expires_in = payload.get('expires_in')
    if expires_in in (None, ''):
        return None
    try:
        seconds = int(expires_in)
    except (TypeError, ValueError):
        return None
    return datetime.now(UTC) + timedelta(seconds=seconds)


async def save_google_calendar_connection(
    db: Database,
    *,
    employee_id: UUID,
    legal_entity_id: UUID,
    token_payload: dict[str, Any],
    userinfo: dict[str, Any],
) -> None:
    existing_refresh_token = await db.fetchval(
        'SELECT refresh_token FROM employee_google_calendar_connections WHERE employee_id = $1',
        employee_id,
    )
    refresh_token = token_payload.get('refresh_token') or existing_refresh_token
    expires_at = _expiry_from_token_payload(token_payload)
    await db.execute(
        """
        INSERT INTO employee_google_calendar_connections (
            employee_id,
            legal_entity_id,
            google_subject,
            google_email,
            calendar_id,
            access_token,
            refresh_token,
            token_type,
            scope,
            expires_at,
            connected_at,
            last_synced_at,
            sync_error,
            updated_at
        )
        VALUES ($1, $2, $3, $4, 'primary', $5, $6, $7, $8, $9, now(), now(), NULL, now())
        ON CONFLICT (employee_id) DO UPDATE
           SET legal_entity_id = EXCLUDED.legal_entity_id,
               google_subject = EXCLUDED.google_subject,
               google_email = EXCLUDED.google_email,
               calendar_id = EXCLUDED.calendar_id,
               access_token = EXCLUDED.access_token,
               refresh_token = COALESCE(EXCLUDED.refresh_token, employee_google_calendar_connections.refresh_token),
               token_type = EXCLUDED.token_type,
               scope = EXCLUDED.scope,
               expires_at = EXCLUDED.expires_at,
               connected_at = now(),
               last_synced_at = now(),
               sync_error = NULL,
               updated_at = now()
        """,
        employee_id,
        legal_entity_id,
        userinfo.get('sub'),
        userinfo.get('email'),
        token_payload.get('access_token'),
        refresh_token,
        token_payload.get('token_type'),
        token_payload.get('scope'),
        expires_at,
    )


async def disconnect_google_calendar_connection(db: Database, employee_id: UUID) -> None:
    await db.execute('DELETE FROM employee_google_calendar_connections WHERE employee_id = $1', employee_id)


async def _load_connection(db: Database, employee_id: UUID) -> Any | None:
    return await db.fetchrow(
        """
        SELECT employee_id,
               legal_entity_id,
               google_subject,
               google_email,
               calendar_id,
               access_token,
               refresh_token,
               token_type,
               scope,
               expires_at,
               connected_at,
               last_synced_at,
               sync_error
          FROM employee_google_calendar_connections
         WHERE employee_id = $1
        """,
        employee_id,
    )


async def _persist_refreshed_token(db: Database, employee_id: UUID, token_payload: dict[str, Any]) -> None:
    expires_at = _expiry_from_token_payload(token_payload)
    await db.execute(
        """
        UPDATE employee_google_calendar_connections
           SET access_token = $2,
               refresh_token = COALESCE($3, refresh_token),
               token_type = COALESCE($4, token_type),
               scope = COALESCE($5, scope),
               expires_at = $6,
               sync_error = NULL,
               updated_at = now()
         WHERE employee_id = $1
        """,
        employee_id,
        token_payload.get('access_token'),
        token_payload.get('refresh_token'),
        token_payload.get('token_type'),
        token_payload.get('scope'),
        expires_at,
    )


async def ensure_google_calendar_access_token(db: Database, employee_id: UUID) -> str | None:
    connection = await _load_connection(db, employee_id)
    if connection is None:
        return None
    expires_at = connection['expires_at']
    if connection['access_token'] and (expires_at is None or expires_at > datetime.now(UTC) + timedelta(minutes=1)):
        return str(connection['access_token'])
    refresh_token = connection['refresh_token']
    if not refresh_token:
        await db.execute(
            """
            UPDATE employee_google_calendar_connections
               SET sync_error = 'Google Calendar authorization expired. Please reconnect your account.',
                   updated_at = now()
             WHERE employee_id = $1
            """,
            employee_id,
        )
        return None
    try:
        refreshed = await refresh_google_access_token(str(refresh_token))
    except HTTPException:
        await db.execute(
            """
            UPDATE employee_google_calendar_connections
               SET sync_error = 'Google Calendar authorization expired. Please reconnect your account.',
                   updated_at = now()
             WHERE employee_id = $1
            """,
            employee_id,
        )
        return None
    await _persist_refreshed_token(db, employee_id, refreshed)
    return str(refreshed.get('access_token') or '')


async def fetch_google_calendar_events(access_token: str) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            GOOGLE_CALENDAR_EVENTS_URL,
            headers={'Authorization': f'Bearer {access_token}'},
            params={
                'maxResults': 6,
                'singleEvents': 'true',
                'orderBy': 'startTime',
                'timeMin': now.isoformat().replace('+00:00', 'Z'),
                'timeMax': (now + timedelta(days=14)).isoformat().replace('+00:00', 'Z'),
            },
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Google Calendar events could not be loaded')
    payload = response.json()
    return payload.get('items') or []


async def get_google_calendar_connection_status(db: Database, employee_id: UUID) -> dict[str, Any]:
    if not google_calendar_is_configured():
        return {
            'provider': 'google_calendar',
            'configured': False,
            'connected': False,
            'account_email': None,
            'calendar_id': None,
            'error': 'Google Calendar integration is not configured yet.',
        }
    connection = await _load_connection(db, employee_id)
    if connection is None:
        return {
            'provider': 'google_calendar',
            'configured': True,
            'connected': False,
            'account_email': None,
            'calendar_id': 'primary',
            'error': None,
        }
    access_token = await ensure_google_calendar_access_token(db, employee_id)
    refreshed = await _load_connection(db, employee_id)
    connection = refreshed or connection
    return {
        'provider': 'google_calendar',
        'configured': True,
        'connected': bool(access_token),
        'account_email': connection['google_email'],
        'calendar_id': connection['calendar_id'],
        'error': connection['sync_error'],
    }


async def get_upcoming_google_schedule(db: Database, employee_id: UUID) -> dict[str, Any]:
    if not google_calendar_is_configured():
        return {
            'provider': 'google_calendar',
            'configured': False,
            'connected': False,
            'google_email': None,
            'calendar_id': None,
            'meetings': [],
            'error': 'Google Calendar integration is not configured yet.',
        }

    connection = await _load_connection(db, employee_id)
    if connection is None:
        return {
            'provider': 'google_calendar',
            'configured': True,
            'connected': False,
            'google_email': None,
            'calendar_id': 'primary',
            'meetings': [],
            'error': None,
        }

    access_token = await ensure_google_calendar_access_token(db, employee_id)
    if not access_token:
        return {
            'provider': 'google_calendar',
            'configured': True,
            'connected': False,
            'google_email': connection['google_email'],
            'calendar_id': connection['calendar_id'],
            'meetings': [],
            'error': connection['sync_error'] or 'Google Calendar authorization expired. Please reconnect your account.',
        }

    try:
        events = await fetch_google_calendar_events(access_token)
    except HTTPException:
        return {
            'provider': 'google_calendar',
            'configured': True,
            'connected': True,
            'google_email': connection['google_email'],
            'calendar_id': connection['calendar_id'],
            'meetings': [],
            'error': 'Google Calendar meetings could not be loaded right now.',
        }

    await db.execute(
        """
        UPDATE employee_google_calendar_connections
           SET last_synced_at = now(),
               sync_error = NULL,
               updated_at = now()
         WHERE employee_id = $1
        """,
        employee_id,
    )

    organizer_emails = {
        str((event.get('organizer') or {}).get('email') or '').strip().lower()
        for event in events
        if (event.get('organizer') or {}).get('email')
    }
    employee_by_email: dict[str, Any] = {}
    if organizer_emails:
        employee_rows = await db.fetch(
            """
            SELECT id, first_name, last_name, email
              FROM employees
             WHERE legal_entity_id = $1
               AND lower(email) = ANY($2::text[])
            """,
            connection['legal_entity_id'],
            list(organizer_emails),
        )
        employee_by_email = {str(row['email']).strip().lower(): row for row in employee_rows if row['email']}

    meetings = []
    for event in events:
        start_data = event.get('start') or {}
        end_data = event.get('end') or {}
        start_at = start_data.get('dateTime') or start_data.get('date')
        end_at = end_data.get('dateTime') or end_data.get('date')
        if not start_at:
            continue
        organizer = event.get('organizer') or {}
        organizer_email = str(organizer.get('email') or '').strip().lower() or None
        employee_match = employee_by_email.get(organizer_email or '')
        meetings.append(
            {
                'id': event.get('id'),
                'title': event.get('summary') or 'Untitled meeting',
                'organizer': organizer.get('displayName') or organizer.get('email'),
                'organizer_email': organizer_email,
                'employee_id': str(employee_match['id']) if employee_match else None,
                'employee_name': f"{employee_match['first_name']} {employee_match['last_name']}" if employee_match else None,
                'employee_email': employee_match['email'] if employee_match else None,
                'start_at': start_at,
                'end_at': end_at,
                'location': event.get('location'),
                'link': event.get('htmlLink'),
                'is_all_day': bool(start_data.get('date') and not start_data.get('dateTime')),
            }
        )

    return {
        'provider': 'google_calendar',
        'configured': True,
        'connected': True,
        'google_email': connection['google_email'],
        'calendar_id': connection['calendar_id'],
        'meetings': meetings,
        'error': None,
    }
