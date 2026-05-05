from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import jwt
from fastapi import HTTPException, status

from .config import settings
from .db import Database

SLACK_BOT_SCOPE = 'chat:write,users:read,users:read.email,im:write'
SLACK_AUTH_URL = 'https://slack.com/oauth/v2/authorize'
SLACK_TOKEN_URL = 'https://slack.com/api/oauth.v2.access'
SLACK_USERS_LOOKUP_URL = 'https://slack.com/api/users.lookupByEmail'
SLACK_CONVERSATIONS_OPEN_URL = 'https://slack.com/api/conversations.open'
SLACK_POST_MESSAGE_URL = 'https://slack.com/api/chat.postMessage'


def slack_redirect_uri() -> str:
    if settings.slack_redirect_uri:
        return settings.slack_redirect_uri
    if settings.public_base_url:
        return f'{settings.public_base_url}/integrations/slack/callback'
    return ''


def slack_is_configured() -> bool:
    return bool(settings.slack_client_id and settings.slack_client_secret and slack_redirect_uri())


def build_slack_state(*, employee_id: UUID, legal_entity_id: UUID) -> str:
    issued_at = datetime.now(UTC)
    payload = {
        'sub': str(employee_id),
        'legal_entity_id': str(legal_entity_id),
        'type': 'slack_state',
        'iat': int(issued_at.timestamp()),
        'exp': int((issued_at + timedelta(minutes=15)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_slack_state(state_token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(state_token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Slack authorization state is invalid') from exc
    if payload.get('type') != 'slack_state':
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Slack authorization state is invalid')
    return payload


def build_slack_authorize_url(*, employee_id: UUID, legal_entity_id: UUID) -> str:
    if not slack_is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail='Slack integration is not configured on this server',
        )
    query = httpx.QueryParams(
        {
            'client_id': settings.slack_client_id,
            'scope': SLACK_BOT_SCOPE,
            'redirect_uri': slack_redirect_uri(),
            'state': build_slack_state(employee_id=employee_id, legal_entity_id=legal_entity_id),
        }
    )
    return f'{SLACK_AUTH_URL}?{query}'


def _slack_error(payload: dict[str, Any], fallback: str) -> HTTPException:
    detail = str(payload.get('error') or fallback)
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail.replace('_', ' '))


async def exchange_slack_code_for_token(code: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            SLACK_TOKEN_URL,
            data={
                'code': code,
                'client_id': settings.slack_client_id,
                'client_secret': settings.slack_client_secret,
                'redirect_uri': slack_redirect_uri(),
            },
        )
    payload = response.json()
    if response.status_code >= 400 or not payload.get('ok'):
        raise _slack_error(payload, 'Slack authorization failed')
    return payload


async def save_slack_workspace_connection(
    db: Database,
    *,
    legal_entity_id: UUID,
    connected_by_employee_id: UUID,
    token_payload: dict[str, Any],
) -> None:
    team = token_payload.get('team') or {}
    authed_user = token_payload.get('authed_user') or {}
    access_token = str(token_payload.get('access_token') or '')
    team_id = str(team.get('id') or '')
    if not access_token or not team_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Slack authorization payload is incomplete')
    await db.execute(
        """
        INSERT INTO slack_workspace_connections (
            legal_entity_id,
            team_id,
            team_name,
            access_token,
            scope,
            bot_user_id,
            authed_user_id,
            connected_by_employee_id,
            connected_at,
            updated_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, now(), now())
        ON CONFLICT (legal_entity_id) DO UPDATE
           SET team_id = EXCLUDED.team_id,
               team_name = EXCLUDED.team_name,
               access_token = EXCLUDED.access_token,
               scope = EXCLUDED.scope,
               bot_user_id = EXCLUDED.bot_user_id,
               authed_user_id = EXCLUDED.authed_user_id,
               connected_by_employee_id = EXCLUDED.connected_by_employee_id,
               connected_at = now(),
               updated_at = now()
        """,
        legal_entity_id,
        team_id,
        team.get('name'),
        access_token,
        token_payload.get('scope'),
        token_payload.get('bot_user_id'),
        authed_user.get('id'),
        connected_by_employee_id,
    )


async def get_slack_workspace_connection(db: Database, legal_entity_id: UUID) -> Any | None:
    return await db.fetchrow(
        """
        SELECT legal_entity_id,
               team_id,
               team_name,
               access_token,
               scope,
               bot_user_id,
               authed_user_id,
               connected_by_employee_id,
               connected_at
          FROM slack_workspace_connections
         WHERE legal_entity_id = $1
        """,
        legal_entity_id,
    )


async def disconnect_slack_workspace_connection(db: Database, legal_entity_id: UUID) -> None:
    await db.execute('DELETE FROM slack_workspace_connections WHERE legal_entity_id = $1', legal_entity_id)


async def get_slack_connection_status(db: Database, legal_entity_id: UUID) -> dict[str, Any]:
    connection = await get_slack_workspace_connection(db, legal_entity_id)
    return {
        'provider': 'slack',
        'configured': slack_is_configured(),
        'connected': connection is not None,
        'team_id': connection['team_id'] if connection else None,
        'team_name': connection['team_name'] if connection else None,
        'connected_by_employee_id': str(connection['connected_by_employee_id']) if connection and connection['connected_by_employee_id'] else None,
        'error': None if slack_is_configured() else 'Slack integration is not configured yet.',
    }


async def _slack_api_get(url: str, *, token: str, params: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(url, headers={'Authorization': f'Bearer {token}'}, params=params)
    payload = response.json()
    if response.status_code >= 400 or not payload.get('ok'):
        raise _slack_error(payload, 'Slack request failed')
    return payload


async def _slack_api_post(url: str, *, token: str, payload: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(url, headers={'Authorization': f'Bearer {token}'}, json=payload)
    body = response.json()
    if response.status_code >= 400 or not body.get('ok'):
        raise _slack_error(body, 'Slack request failed')
    return body


async def send_slack_direct_message(
    db: Database,
    *,
    legal_entity_id: UUID,
    employee_email: str,
    message: str,
) -> dict[str, Any]:
    connection = await get_slack_workspace_connection(db, legal_entity_id)
    if connection is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Slack is not connected for this company')
    if not employee_email:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail='Employee email is required for Slack direct messages')
    token = str(connection['access_token'])
    lookup = await _slack_api_get(SLACK_USERS_LOOKUP_URL, token=token, params={'email': employee_email})
    user = lookup.get('user') or {}
    user_id = str(user.get('id') or '')
    if not user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Slack user could not be matched by employee email')
    conversation = await _slack_api_post(SLACK_CONVERSATIONS_OPEN_URL, token=token, payload={'users': user_id})
    channel = conversation.get('channel') or {}
    channel_id = str(channel.get('id') or '')
    if not channel_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Slack direct message channel could not be opened')
    sent = await _slack_api_post(SLACK_POST_MESSAGE_URL, token=token, payload={'channel': channel_id, 'text': message})
    return {
        'channel_id': channel_id,
        'message_ts': sent.get('ts'),
        'user_id': user_id,
        'team_id': connection['team_id'],
        'team_name': connection['team_name'],
    }
