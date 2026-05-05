from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from .api_support import get_db_from_request, require_actor
from .config import settings
from .db import Database
from .labor_engine import _fetch_resolved_shifts, seed_public_holidays
from .monitoring import mark_background_job
from .rbac import ensure_permission

MATTERMOST_ROUTER = APIRouter(prefix='/integrations/mattermost', tags=['mattermost'])
GEORGIA_TZ = ZoneInfo('Asia/Tbilisi')


@dataclass(slots=True)
class MattermostConfig:
    legal_entity_id: UUID
    enabled: bool
    server_base_url: str | None
    incoming_webhook_url: str | None
    hr_webhook_url: str | None
    general_webhook_url: str | None
    it_webhook_url: str | None
    bot_access_token: str | None
    command_token: str | None
    action_secret: str | None
    default_team: str | None
    hr_channel: str | None
    general_channel: str | None
    it_channel: str | None


@dataclass(slots=True)
class MattermostLaunchContext:
    login_url: str
    login_id: str
    password: str
    channel_url: str | None


class ExpenseClaimLine(BaseModel):
    expense_date: date
    category_code: str
    description: str
    amount: Decimal = Field(ge=0)
    attachment_url: str | None = None


class LeaveRequestCreate(BaseModel):
    employee_id: UUID | None = None
    leave_type_id: UUID
    start_date: date
    end_date: date
    requested_days: Decimal | None = Field(default=None, ge=0)
    reason: str


class ExpenseClaimCreate(BaseModel):
    employee_id: UUID | None = None
    claim_date: date = Field(default_factory=date.today)
    currency_code: str = 'GEL'
    items: list[ExpenseClaimLine]


async def _default_config_for_entity(db: Database, legal_entity_id: UUID) -> MattermostConfig | None:
    if not settings.mattermost_public_url:
        return None
    trade_name = await db.fetchval(
        """
        SELECT trade_name
          FROM legal_entities
         WHERE id = $1
        """,
        legal_entity_id,
    )
    default_team = _mattermost_team_name(trade_name or settings.tenant_label or 'hrms')
    return MattermostConfig(
        legal_entity_id=legal_entity_id,
        enabled=True,
        server_base_url=settings.mattermost_public_url.rstrip('/'),
        incoming_webhook_url=None,
        hr_webhook_url=None,
        general_webhook_url=None,
        it_webhook_url=None,
        bot_access_token=settings.mattermost_bot_access_token or None,
        command_token=None,
        action_secret=None,
        default_team=default_team,
        hr_channel='town-square',
        general_channel='town-square',
        it_channel='town-square',
    )


async def _fetch_config(db: Database, legal_entity_id: UUID) -> MattermostConfig | None:
    row = await db.fetchrow(
        """
        SELECT legal_entity_id, enabled, server_base_url, incoming_webhook_url, hr_webhook_url,
               general_webhook_url, it_webhook_url, bot_access_token, command_token,
               action_secret, default_team, hr_channel, general_channel, it_channel
          FROM mattermost_integrations
         WHERE legal_entity_id = $1
        """,
        legal_entity_id,
    )
    if row:
        return MattermostConfig(**dict(row))
    return await _default_config_for_entity(db, legal_entity_id)


async def _fetch_config_by_command_token(db: Database, command_token: str) -> MattermostConfig | None:
    row = await db.fetchrow(
        """
        SELECT legal_entity_id, enabled, server_base_url, incoming_webhook_url, hr_webhook_url,
               general_webhook_url, it_webhook_url, bot_access_token, command_token,
               action_secret, default_team, hr_channel, general_channel, it_channel
          FROM mattermost_integrations
         WHERE command_token = $1
        """,
        command_token,
    )
    return MattermostConfig(**dict(row)) if row else None


async def _resolve_public_base_url(db: Database, legal_entity_id: UUID) -> str:
    value = await db.fetchval(
        'SELECT hrms.resolve_public_base_url($1, $2)',
        legal_entity_id,
        settings.public_base_url or None,
    )
    return (value or settings.public_base_url or '').rstrip('/')


@MATTERMOST_ROUTER.get('/launch', response_class=HTMLResponse)
async def launch_chat(request: Request) -> HTMLResponse:
    actor = await require_actor(request)
    db = get_db_from_request(request)
    config = await _fetch_config(db, actor.legal_entity_id)
    if config is None or not config.enabled:
        raise HTTPException(status_code=404, detail='Chat is not enabled for this tenant')
    launch_context = await build_mattermost_launch_context(db, actor.employee_id)
    if launch_context is None:
        fallback_url = (config.server_base_url or settings.mattermost_public_url or '').rstrip('/')
        return HTMLResponse(
            f'<html><body><script>window.location.href={json.dumps(fallback_url)};</script></body></html>'
        )
    return HTMLResponse(_launch_html(launch_context))


class MattermostClient:
    async def api_request(
        self,
        config: MattermostConfig,
        method: str,
        path: str,
        *,
        json_payload: dict[str, Any] | None = None,
    ) -> Any:
        api_base_url = (settings.mattermost_site_url or config.server_base_url or '').rstrip('/')
        if not api_base_url or not config.bot_access_token:
            raise HTTPException(status_code=400, detail='Mattermost bot token or server URL is missing')
        url = f"{api_base_url}/api/v4{path}"
        headers = {'Authorization': f'Bearer {config.bot_access_token}'}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.request(method, url, json=json_payload, headers=headers)
            if response.status_code >= 400:
                response.raise_for_status()
            if not response.content:
                return None
            return response.json()

    async def post_webhook(
        self,
        webhook_url: str,
        *,
        text: str,
        channel: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        props: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {'text': text}
        if channel:
            payload['channel'] = channel
        if attachments:
            payload['attachments'] = attachments
        if props:
            payload['props'] = props
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(webhook_url, json=payload)
            response.raise_for_status()


MM_CLIENT = MattermostClient()


def _launch_html(context: MattermostLaunchContext) -> str:
    channel_url = context.channel_url or ''
    return f"""
    <!DOCTYPE html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width,initial-scale=1" />
        <title>Launching Mattermost</title>
      </head>
      <body style="font-family:Segoe UI,Arial,sans-serif;background:#0f172a;color:#e2e8f0;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;">
        <div style="max-width:560px;background:#111c35;border:1px solid rgba(255,255,255,0.1);border-radius:20px;padding:32px;box-shadow:0 20px 60px rgba(2,6,23,0.45);">
          <h1 style="margin:0 0 12px;font-size:24px;">Launching company chat...</h1>
          <p style="margin:0 0 18px;line-height:1.7;color:#cbd5e1;">Your HRMS session is preparing a Mattermost sign-in for this tenant. If the workspace does not open automatically, use the fallback link below.</p>
          <form id="mattermost-login" method="post" action="{context.login_url}">
            <input type="hidden" name="login_id" value="{context.login_id}" />
            <input type="hidden" name="loginId" value="{context.login_id}" />
            <input type="hidden" name="email" value="{context.login_id}" />
            <input type="hidden" name="password" value="{context.password}" />
          </form>
          <a href="{channel_url}" style="display:inline-flex;align-items:center;gap:8px;padding:12px 18px;border-radius:12px;background:#2563eb;color:white;text-decoration:none;font-weight:600;">Open Mattermost</a>
        </div>
        <script>
          const form = document.getElementById('mattermost-login');
          setTimeout(() => form.submit(), 150);
          setTimeout(() => {{
            if ({json.dumps(bool(channel_url))}) {{
              window.location.href = {json.dumps(channel_url)};
            }}
          }}, 1800);
        </script>
      </body>
    </html>
    """.strip()


def _mattermost_username_seed(email: str | None, employee_number: str | None, first_name: str | None, last_name: str | None) -> str:
    if email and '@' in email:
        seed = email.split('@', 1)[0]
    elif employee_number:
        seed = employee_number
    else:
        seed = f'{first_name or "user"}-{last_name or "employee"}'
    normalized = ''.join(char.lower() if char.isalnum() else '-' for char in seed)
    normalized = '-'.join(part for part in normalized.split('-') if part)
    return (normalized or 'hrms-user')[:22]


def _mattermost_team_name(seed: str | None) -> str:
    normalized = ''.join(char.lower() if char.isalnum() else '-' for char in (seed or 'hrms'))
    normalized = '-'.join(part for part in normalized.split('-') if part)
    return (normalized or 'hrms')[:32]


async def _ensure_team_membership(config: MattermostConfig, team_id: str, user_id: str) -> None:
    try:
        await MM_CLIENT.api_request(
            config,
            'POST',
            f"/teams/{team_id}/members",
            json_payload={'team_id': team_id, 'user_id': user_id},
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 400:
            raise


async def _ensure_team(config: MattermostConfig, *, display_name: str, team_name: str) -> dict[str, Any]:
    team = None
    try:
        team = await MM_CLIENT.api_request(config, 'GET', f"/teams/name/{team_name}")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            raise
    if team is None:
        team = await MM_CLIENT.api_request(
            config,
            'POST',
            '/teams',
            json_payload={
                'name': team_name,
                'display_name': display_name[:64],
                'type': 'I',
            },
        )
    return team


async def _ensure_department_channel_membership(
    config: MattermostConfig,
    *,
    team_id: str,
    user_id: str,
    department_name: str | None,
) -> str | None:
    if not department_name:
        return None
    channel_name = _mattermost_team_name(department_name)
    channel = None
    try:
        channel = await MM_CLIENT.api_request(config, 'GET', f"/teams/{team_id}/channels/name/{channel_name}")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            raise
    if channel is None:
        channel = await MM_CLIENT.api_request(
            config,
            'POST',
            '/channels',
            json_payload={
                'team_id': team_id,
                'name': channel_name,
                'display_name': department_name[:64],
                'type': 'O',
            },
        )
    try:
        await MM_CLIENT.api_request(
            config,
            'POST',
            f"/channels/{channel['id']}/members",
            json_payload={'user_id': user_id},
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 400:
            raise
    return channel_name


async def ensure_mattermost_account_for_employee(db: Database, employee_id: UUID) -> dict[str, Any] | None:
    row = await db.fetchrow(
        """
        SELECT e.id,
               e.legal_entity_id,
               e.employee_number,
               e.email,
               e.first_name,
               e.last_name,
               le.trade_name,
               coalesce(d.name_ka, d.name_en) AS department_name
          FROM employees e
          JOIN legal_entities le ON le.id = e.legal_entity_id
          LEFT JOIN departments d ON d.id = e.department_id
         WHERE e.id = $1
           AND e.deleted_at IS NULL
         LIMIT 1
        """,
        employee_id,
    )
    if row is None or not row['email']:
        return None
    config = await _fetch_config(db, row['legal_entity_id'])
    if config is None or not config.enabled or not config.server_base_url or not config.bot_access_token:
        return None

    username = _mattermost_username_seed(row['email'], row['employee_number'], row['first_name'], row['last_name'])
    mattermost_user = None
    try:
        mattermost_user = await MM_CLIENT.api_request(config, 'GET', f"/users/email/{row['email']}")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            raise
    if mattermost_user is None:
        mattermost_user = await MM_CLIENT.api_request(
            config,
            'POST',
            '/users',
            json_payload={
                'email': row['email'],
                'username': username,
                'first_name': row['first_name'] or '',
                'last_name': row['last_name'] or '',
                'password': secrets.token_urlsafe(18),
            },
        )
    else:
        await MM_CLIENT.api_request(
            config,
            'PUT',
            f"/users/{mattermost_user['id']}/patch",
            json_payload={
                'first_name': row['first_name'] or '',
                'last_name': row['last_name'] or '',
                'email': row['email'],
            },
        )

    team_name = _mattermost_team_name(f"{settings.mattermost_default_team_prefix}-{config.default_team or row['trade_name']}" if settings.mattermost_default_team_prefix else (config.default_team or row['trade_name']))
    team = await _ensure_team(config, display_name=row['trade_name'], team_name=team_name)
    team_id = team['id']
    await _ensure_team_membership(config, team_id, mattermost_user['id'])
    department_channel = await _ensure_department_channel_membership(
        config,
        team_id=team_id,
        user_id=mattermost_user['id'],
        department_name=row['department_name'],
    )

    await db.execute(
        """
        INSERT INTO employee_chat_accounts (employee_id, mattermost_user_id, mattermost_username)
        VALUES ($1, $2, $3)
        ON CONFLICT (employee_id) DO UPDATE
           SET mattermost_user_id = EXCLUDED.mattermost_user_id,
               mattermost_username = EXCLUDED.mattermost_username,
               updated_at = now()
        """,
        employee_id,
        mattermost_user['id'],
        mattermost_user['username'],
    )
    return {
        'mattermost_user_id': mattermost_user['id'],
        'mattermost_username': mattermost_user['username'],
        'team_name': team_name,
        'department_channel': department_channel,
        'server_base_url': config.server_base_url,
    }


async def ensure_mattermost_teams_for_all_tenants(db: Database) -> None:
    rows = await db.fetch(
        """
        SELECT id, trade_name
          FROM legal_entities
         ORDER BY trade_name
        """
    )
    for row in rows:
        config = await _fetch_config(db, row['id'])
        if config is None or not config.enabled or not config.server_base_url or not config.bot_access_token:
            continue
        team_name = _mattermost_team_name(
            f"{settings.mattermost_default_team_prefix}-{config.default_team or row['trade_name']}"
            if settings.mattermost_default_team_prefix
            else (config.default_team or row['trade_name'])
        )
        await _ensure_team(config, display_name=row['trade_name'], team_name=team_name)


async def sync_mattermost_password_for_employee(db: Database, employee_id: UUID, new_password: str) -> bool:
    account = await db.fetchrow(
        """
        SELECT eca.mattermost_user_id, e.legal_entity_id
          FROM employee_chat_accounts eca
          JOIN employees e ON e.id = eca.employee_id
         WHERE eca.employee_id = $1
        """,
        employee_id,
    )
    if account is None:
        account_info = await ensure_mattermost_account_for_employee(db, employee_id)
        if account_info is None:
            return False
        mattermost_user_id = str(account_info['mattermost_user_id'])
        legal_entity_id = await db.fetchval('SELECT legal_entity_id FROM employees WHERE id = $1', employee_id)
    else:
        mattermost_user_id = account['mattermost_user_id']
        legal_entity_id = account['legal_entity_id']
    config = await _fetch_config(db, legal_entity_id)
    if config is None or not config.enabled or not config.server_base_url or not config.bot_access_token:
        return False
    await MM_CLIENT.api_request(
        config,
        'PUT',
        f"/users/{mattermost_user_id}/password",
        json_payload={'new_password': new_password},
    )
    return True


async def build_mattermost_launch_context(db: Database, employee_id: UUID) -> MattermostLaunchContext | None:
    employee = await db.fetchrow(
        """
        SELECT e.id,
               e.email,
               e.legal_entity_id,
               le.trade_name
          FROM employees e
          JOIN legal_entities le ON le.id = e.legal_entity_id
         WHERE e.id = $1
           AND e.deleted_at IS NULL
        """,
        employee_id,
    )
    if employee is None or not employee['email']:
        return None
    config = await _fetch_config(db, employee['legal_entity_id'])
    if config is None or not config.enabled or not config.server_base_url or not config.bot_access_token:
        return None
    account_info = await ensure_mattermost_account_for_employee(db, employee_id)
    if account_info is None:
        return None
    one_time_password = secrets.token_urlsafe(18)
    await sync_mattermost_password_for_employee(db, employee_id, one_time_password)
    channel_name = account_info.get('department_channel') or config.general_channel or config.hr_channel or 'town-square'
    team_name = account_info.get('team_name') or _mattermost_team_name(config.default_team or employee['trade_name'])
    channel_url = f"{str(config.server_base_url).rstrip('/')}/{team_name}/channels/{channel_name}"
    return MattermostLaunchContext(
        login_url=f"{str(config.server_base_url).rstrip('/')}/login",
        login_id=str(employee['email']),
        password=one_time_password,
        channel_url=channel_url,
    )


def _signature(secret: str, legal_entity_id: UUID, entity_type: str, entity_id: UUID, decision: str) -> str:
    message = f'{legal_entity_id}:{entity_type}:{entity_id}:{decision}'.encode('utf-8')
    return hmac.new(secret.encode('utf-8'), message, hashlib.sha256).hexdigest()


def _build_action(secret: str, legal_entity_id: UUID, entity_type: str, entity_id: UUID, decision: str, callback_url: str) -> dict[str, Any]:
    return {
        'id': f'{entity_type}_{decision}',
        'type': 'button',
        'name': 'Approve' if decision == 'approved' else 'Reject',
        'style': 'primary' if decision == 'approved' else 'danger',
        'integration': {
            'url': callback_url,
            'context': {
                'legal_entity_id': str(legal_entity_id),
                'entity_type': entity_type,
                'entity_id': str(entity_id),
                'decision': decision,
                'signature': _signature(secret, legal_entity_id, entity_type, entity_id, decision),
            },
        },
    }


async def _resolve_employee_from_mattermost(db: Database, mattermost_user_id: str | None, mattermost_username: str | None) -> tuple[UUID, UUID] | None:
    row = await db.fetchrow(
        """
        SELECT e.id AS employee_id, e.legal_entity_id
          FROM employee_chat_accounts eca
          JOIN employees e ON e.id = eca.employee_id
         WHERE ($1::text IS NOT NULL AND eca.mattermost_user_id = $1)
            OR ($2::citext IS NOT NULL AND eca.mattermost_username = $2)
         LIMIT 1
        """,
        mattermost_user_id,
        mattermost_username,
    )
    if row is None:
        return None
    return row['employee_id'], row['legal_entity_id']


async def _leave_business_days(db: Database, start_date: date, end_date: date) -> Decimal:
    await seed_public_holidays(db, start_date.year)
    if end_date.year != start_date.year:
        await seed_public_holidays(db, end_date.year)
    holiday_rows = await db.fetch(
        'SELECT holiday_date FROM public_holidays_ge WHERE holiday_date BETWEEN $1 AND $2',
        start_date,
        end_date,
    )
    holidays = {row['holiday_date'] for row in holiday_rows}
    current = start_date
    total = Decimal('0.00')
    while current <= end_date:
        if current.weekday() < 5 and current not in holidays:
            total += Decimal('1.00')
        current += timedelta(days=1)
    return total


async def send_leave_approval_request(db: Database, leave_request_id: UUID) -> None:
    row = await db.fetchrow(
        """
        SELECT lr.id, lr.employee_id, lr.manager_employee_id, lr.start_date, lr.end_date, lr.requested_days,
               lr.approval_stage,
               lr.reason, le.id AS legal_entity_id,
               e.first_name || ' ' || e.last_name AS employee_name,
               mca.mattermost_username AS manager_username,
               lt.name_en AS leave_type_name
          FROM leave_requests lr
          JOIN employees e ON e.id = lr.employee_id
          JOIN legal_entities le ON le.id = e.legal_entity_id
          JOIN leave_types lt ON lt.id = lr.leave_type_id
          LEFT JOIN employee_chat_accounts mca ON mca.employee_id = lr.manager_employee_id
         WHERE lr.id = $1
        """,
        leave_request_id,
    )
    if row is None:
        return
    config = await _fetch_config(db, row['legal_entity_id'])
    if config is None or not config.enabled or not config.action_secret:
        return
    webhook_url = config.hr_webhook_url or config.incoming_webhook_url
    if not webhook_url:
        return
    callback_base = await _resolve_public_base_url(db, row['legal_entity_id'])
    if not callback_base:
        return
    callback_url = f'{callback_base}/integrations/mattermost/actions'
    manager_stage = row['approval_stage'] == 'manager_pending'
    channel = f"@{row['manager_username']}" if manager_stage and row['manager_username'] else config.hr_channel
    attachments = [
        {
            'fallback': f"Leave request for {row['employee_name']} from {row['start_date']} to {row['end_date']}",
            'pretext': ':handshake: Manager approval request' if manager_stage else ':office: HR final approval',
            'text': (
                f"**{row['employee_name']}** requested **{row['leave_type_name']}**\n"
                f"Dates: {row['start_date']} → {row['end_date']}\n"
                f"Days: {row['requested_days']}\n"
                f"Reason: {row['reason']}"
            ),
            'actions': [
                _build_action(config.action_secret, row['legal_entity_id'], 'leave_request', row['id'], 'approved', callback_url),
                _build_action(config.action_secret, row['legal_entity_id'], 'leave_request', row['id'], 'rejected', callback_url),
            ],
        }
    ]
    await MM_CLIENT.post_webhook(webhook_url, text='Leave approval request', channel=channel, attachments=attachments)


async def send_expense_approval_request(db: Database, expense_claim_id: UUID) -> None:
    row = await db.fetchrow(
        """
        SELECT ec.id, ec.employee_id, ec.manager_employee_id, ec.claim_date, ec.total_amount, ec.currency_code,
               le.id AS legal_entity_id,
               e.first_name || ' ' || e.last_name AS employee_name,
               mca.mattermost_username AS manager_username
          FROM expense_claims ec
          JOIN employees e ON e.id = ec.employee_id
          JOIN legal_entities le ON le.id = e.legal_entity_id
          LEFT JOIN employee_chat_accounts mca ON mca.employee_id = ec.manager_employee_id
         WHERE ec.id = $1
        """,
        expense_claim_id,
    )
    if row is None:
        return
    config = await _fetch_config(db, row['legal_entity_id'])
    if config is None or not config.enabled or not config.action_secret:
        return
    webhook_url = config.hr_webhook_url or config.incoming_webhook_url
    if not webhook_url:
        return
    callback_base = await _resolve_public_base_url(db, row['legal_entity_id'])
    if not callback_base:
        return
    callback_url = f'{callback_base}/integrations/mattermost/actions'
    channel = f"@{row['manager_username']}" if row['manager_username'] else config.hr_channel
    attachments = [
        {
            'fallback': f"Expense claim for {row['employee_name']} total {row['total_amount']} {row['currency_code']}",
            'pretext': ':receipt: Expense approval request',
            'text': (
                f"**{row['employee_name']}** submitted an expense claim\n"
                f"Claim date: {row['claim_date']}\n"
                f"Total: {row['total_amount']} {row['currency_code']}"
            ),
            'actions': [
                _build_action(config.action_secret, row['legal_entity_id'], 'expense_claim', row['id'], 'approved', callback_url),
                _build_action(config.action_secret, row['legal_entity_id'], 'expense_claim', row['id'], 'rejected', callback_url),
            ],
        }
    ]
    await MM_CLIENT.post_webhook(webhook_url, text='Expense approval request', channel=channel, attachments=attachments)


async def notify_it_prepare_workstation(db: Database, employee_id: UUID) -> None:
    row = await db.fetchrow(
        """
        SELECT e.id, e.employee_number, e.first_name, e.last_name, e.hire_date,
               le.id AS legal_entity_id,
               d.name_en AS department_name,
               jr.title_en AS role_title
          FROM employees e
          JOIN legal_entities le ON le.id = e.legal_entity_id
          LEFT JOIN departments d ON d.id = e.department_id
          LEFT JOIN job_roles jr ON jr.id = e.job_role_id
         WHERE e.id = $1
        """,
        employee_id,
    )
    if row is None:
        return
    config = await _fetch_config(db, row['legal_entity_id'])
    if config is None or not config.enabled:
        return
    webhook_url = config.it_webhook_url or config.incoming_webhook_url
    if not webhook_url:
        return
    text = (
        ':computer: **New hire onboarding**\n'
        f"Employee: {row['first_name']} {row['last_name']} ({row['employee_number']})\n"
        f"Role: {row['role_title'] or 'Unassigned'}\n"
        f"Department: {row['department_name'] or 'Unassigned'}\n"
        f"Hire date: {row['hire_date']}\n"
        'Please prepare laptop, phone, access card, and workstation.'
    )
    await MM_CLIENT.post_webhook(webhook_url, text=text, channel=config.it_channel)


async def _presence_for_employee(db: Database, employee_id: UUID, target_date: date) -> dict[str, Any]:
    leave_row = await db.fetchrow(
        """
        SELECT lt.name_en AS leave_type_name
          FROM leave_requests lr
          JOIN leave_types lt ON lt.id = lr.leave_type_id
         WHERE lr.employee_id = $1
           AND lr.status = 'approved'
           AND $2 BETWEEN lr.start_date AND lr.end_date
         ORDER BY lr.created_at DESC
         LIMIT 1
        """,
        employee_id,
        target_date,
    )
    if leave_row:
        return {'status': 'on_leave', 'detail': leave_row['leave_type_name']}

    mode_row = await db.fetchrow(
        """
        SELECT work_mode::text AS work_mode, note
          FROM employee_status_calendar
         WHERE employee_id = $1
           AND status_date = $2
        """,
        employee_id,
        target_date,
    )
    if mode_row and mode_row['work_mode'] == 'remote':
        return {'status': 'remote', 'detail': mode_row['note']}
    if mode_row and mode_row['work_mode'] == 'business_trip':
        return {'status': 'remote', 'detail': mode_row['note'] or 'Business trip'}

    latest_log = await db.fetchrow(
        """
        SELECT direction::text AS direction, event_ts
          FROM raw_attendance_logs
         WHERE employee_id = $1
           AND event_ts >= $2::date
           AND event_ts < ($2::date + INTERVAL '1 day')
         ORDER BY event_ts DESC
         LIMIT 1
        """,
        employee_id,
        target_date,
    )
    if latest_log and latest_log['direction'] == 'in':
        return {'status': 'office', 'detail': latest_log['event_ts']}
    return {'status': 'unknown', 'detail': 'No active presence record'}


async def _clocked_in_employees(db: Database, legal_entity_id: UUID) -> list[dict[str, Any]]:
    rows = await db.fetch(
        """
        WITH latest AS (
            SELECT DISTINCT ON (ral.employee_id)
                   ral.employee_id,
                   ral.event_ts,
                   ral.direction::text AS direction
              FROM raw_attendance_logs ral
              JOIN employees e ON e.id = ral.employee_id
             WHERE e.legal_entity_id = $1
               AND ral.event_ts >= current_date
             ORDER BY ral.employee_id, ral.event_ts DESC
        )
        SELECT e.id, e.first_name, e.last_name, e.employee_number, d.name_en AS department_name, latest.event_ts
          FROM latest
          JOIN employees e ON e.id = latest.employee_id
          LEFT JOIN departments d ON d.id = e.department_id
         WHERE latest.direction = 'in'
         ORDER BY e.first_name, e.last_name
        """,
        legal_entity_id,
    )
    return [dict(row) for row in rows]


async def _leave_balance_summary(db: Database, employee_id: UUID, balance_year: int) -> list[dict[str, Any]]:
    rows = await db.fetch(
        """
        SELECT lt.name_en, lt.name_ka,
               lb.opening_days, lb.earned_days, lb.used_days, lb.adjusted_days,
               (lb.opening_days + lb.earned_days + lb.adjusted_days - lb.used_days) AS remaining_days
          FROM leave_balances lb
          JOIN leave_types lt ON lt.id = lb.leave_type_id
         WHERE lb.employee_id = $1
           AND lb.balance_year = $2
         ORDER BY lt.name_en
        """,
        employee_id,
        balance_year,
    )
    return [dict(row) for row in rows]


async def _record_dispatch(db: Database, legal_entity_id: UUID, event_type: str, event_key: str, payload: dict[str, Any]) -> bool:
    try:
        await db.execute(
            """
            INSERT INTO automation_dispatch_log (legal_entity_id, event_type, event_key, payload)
            VALUES ($1, $2, $3, $4::jsonb)
            """,
            legal_entity_id,
            event_type,
            event_key,
            json.dumps(payload),
        )
        return True
    except Exception:
        return False


async def late_arrival_monitor_once(db: Database, target_date: date | None = None) -> None:
    target_date = target_date or datetime.now(tz=GEORGIA_TZ).date()
    entities = await db.fetch('SELECT id FROM legal_entities ORDER BY trade_name')
    for entity in entities:
        legal_entity_id = entity['id']
        config = await _fetch_config(db, legal_entity_id)
        if config is None or not config.enabled:
            continue
        webhook_url = config.hr_webhook_url or config.incoming_webhook_url
        if not webhook_url:
            continue
        threshold_minutes = await db.fetchval(
            'SELECT late_arrival_threshold_minutes FROM entity_operation_settings WHERE legal_entity_id = $1',
            legal_entity_id,
        ) or 15
        employees = await db.fetch(
            """
            SELECT id, first_name, last_name, employee_number, department_id
              FROM employees
             WHERE legal_entity_id = $1
               AND employment_status = 'active'
            """,
            legal_entity_id,
        )
        for employee in employees:
            shifts = await _fetch_resolved_shifts(db, employee['id'], target_date, target_date)
            shift = shifts.get(target_date)
            if shift is None:
                continue
            if datetime.now(tz=GEORGIA_TZ) < shift.start_local + timedelta(minutes=threshold_minutes):
                continue
            first_punch = await db.fetchval(
                """
                SELECT min(event_ts)
                  FROM raw_attendance_logs
                 WHERE employee_id = $1
                   AND event_ts BETWEEN $2 AND $3
                """,
                employee['id'],
                shift.start_local - timedelta(hours=2),
                shift.end_local,
            )
            is_late = first_punch is None or first_punch.astimezone(GEORGIA_TZ) > shift.start_local + timedelta(minutes=threshold_minutes)
            if not is_late:
                continue
            event_key = f"late:{employee['id']}:{target_date.isoformat()}"
            inserted = await _record_dispatch(
                db,
                legal_entity_id,
                'late_arrival',
                event_key,
                {'employee_id': str(employee['id']), 'work_date': target_date.isoformat()},
            )
            if not inserted:
                continue
            text = (
                ':warning: **Late arrival alert**\n'
                f"Employee: {employee['first_name']} {employee['last_name']} ({employee['employee_number']})\n"
                f"Scheduled start: {shift.start_local.strftime('%H:%M')}\n"
                f"First punch: {first_punch.astimezone(GEORGIA_TZ).strftime('%H:%M') if first_punch else 'No punch yet'}"
            )
            await MM_CLIENT.post_webhook(webhook_url, text=text, channel=config.hr_channel)
    await mark_background_job('late-arrival-monitor')


async def celebration_monitor_once(db: Database, target_date: date | None = None) -> None:
    target_date = target_date or datetime.now(tz=GEORGIA_TZ).date()
    entities = await db.fetch('SELECT id FROM legal_entities ORDER BY trade_name')
    for entity in entities:
        legal_entity_id = entity['id']
        config = await _fetch_config(db, legal_entity_id)
        if config is None or not config.enabled:
            continue
        webhook_url = config.general_webhook_url or config.incoming_webhook_url
        if not webhook_url:
            continue
        birthdays = await db.fetch(
            """
            SELECT id, first_name, last_name
              FROM employees
             WHERE legal_entity_id = $1
               AND birth_date IS NOT NULL
               AND extract(month from birth_date) = $2
               AND extract(day from birth_date) = $3
               AND employment_status = 'active'
            """,
            legal_entity_id,
            target_date.month,
            target_date.day,
        )
        for birthday in birthdays:
            event_key = f"birthday:{birthday['id']}:{target_date.isoformat()}"
            inserted = await _record_dispatch(db, legal_entity_id, 'birthday', event_key, {'employee_id': str(birthday['id'])})
            if inserted:
                await MM_CLIENT.post_webhook(
                    webhook_url,
                    text=f":birthday: Happy birthday, **{birthday['first_name']} {birthday['last_name']}**!",
                    channel=config.general_channel,
                )
        anniversaries = await db.fetch(
            """
            SELECT id, first_name, last_name, hire_date,
                   (extract(year from age($2::date, hire_date)))::int AS years_completed
              FROM employees
             WHERE legal_entity_id = $1
               AND extract(month from hire_date) = $3
               AND extract(day from hire_date) = $4
               AND hire_date < $2
               AND employment_status = 'active'
            """,
            legal_entity_id,
            target_date,
            target_date.month,
            target_date.day,
        )
        for anniversary in anniversaries:
            event_key = f"anniversary:{anniversary['id']}:{target_date.isoformat()}"
            inserted = await _record_dispatch(db, legal_entity_id, 'work_anniversary', event_key, {'employee_id': str(anniversary['id'])})
            if inserted:
                await MM_CLIENT.post_webhook(
                    webhook_url,
                    text=(
                        ':tada: Work anniversary! '
                        f"**{anniversary['first_name']} {anniversary['last_name']}** completed "
                        f"**{anniversary['years_completed']}** year(s) with the company."
                    ),
                    channel=config.general_channel,
                )
    await mark_background_job('celebration-monitor')


async def late_arrival_monitor_loop(db: Database, sleep_seconds: int) -> None:
    while True:
        await late_arrival_monitor_once(db)
        await asyncio.sleep(sleep_seconds)


async def celebration_monitor_loop(db: Database, sleep_seconds: int) -> None:
    while True:
        await celebration_monitor_once(db)
        await asyncio.sleep(sleep_seconds)


@MATTERMOST_ROUTER.post('/commands')
async def slash_commands(request: Request) -> JSONResponse:
    db = get_db_from_request(request)
    form = await request.form()
    token = str(form.get('token') or '')
    command = str(form.get('command') or '').strip()
    text = str(form.get('text') or '').strip()
    mattermost_user_id = str(form.get('user_id') or '') or None
    mattermost_username = str(form.get('user_name') or '') or None

    config = await _fetch_config_by_command_token(db, token)
    if config is None or not config.enabled:
        raise HTTPException(status_code=401, detail='Invalid Mattermost command token')

    actor = await _resolve_employee_from_mattermost(db, mattermost_user_id, mattermost_username)
    if actor is None:
        return JSONResponse({'response_type': 'ephemeral', 'text': 'Your Mattermost account is not linked to an employee profile.'})
    employee_id, legal_entity_id = actor

    if command == '/who_is_in':
        people = await _clocked_in_employees(db, legal_entity_id)
        if not people:
            return JSONResponse({'response_type': 'ephemeral', 'text': 'No employees are currently clocked in.'})
        lines = ['**Currently clocked in**']
        for person in people:
            lines.append(
                f"- {person['first_name']} {person['last_name']} ({person['employee_number']}) — {person['department_name'] or 'No department'}"
            )
        return JSONResponse({'response_type': 'ephemeral', 'text': '\n'.join(lines)})

    if command == '/my_balance':
        balances = await _leave_balance_summary(db, employee_id, datetime.now(tz=GEORGIA_TZ).year)
        if not balances:
            return JSONResponse({'response_type': 'ephemeral', 'text': 'No leave balances are configured for you yet.'})
        lines = ['**Your paid leave balances**']
        for balance in balances:
            lines.append(f"- {balance['name_en']}: {balance['remaining_days']} day(s) remaining")
        return JSONResponse({'response_type': 'ephemeral', 'text': '\n'.join(lines)})

    if command == '/status':
        handle = text.lstrip('@').strip()
        if not handle:
            return JSONResponse({'response_type': 'ephemeral', 'text': 'Usage: /status @username'})
        target = await db.fetchrow(
            """
            SELECT e.id, e.first_name, e.last_name
              FROM employee_chat_accounts eca
              JOIN employees e ON e.id = eca.employee_id
             WHERE e.legal_entity_id = $1
               AND eca.mattermost_username = $2
            """,
            legal_entity_id,
            handle,
        )
        if target is None:
            return JSONResponse({'response_type': 'ephemeral', 'text': f'No employee is linked to @{handle}.'})
        presence = await _presence_for_employee(db, target['id'], datetime.now(tz=GEORGIA_TZ).date())
        text_value = f"**{target['first_name']} {target['last_name']}** is **{presence['status'].replace('_', ' ')}**"
        if presence['detail']:
            text_value += f" ({presence['detail']})"
        return JSONResponse({'response_type': 'ephemeral', 'text': text_value})

    return JSONResponse({'response_type': 'ephemeral', 'text': f'Unsupported command: {command}'})


@MATTERMOST_ROUTER.post('/actions')
async def action_handler(request: Request) -> JSONResponse:
    db = get_db_from_request(request)
    payload = await request.json()
    context = payload.get('context') or {}
    legal_entity_id = UUID(context['legal_entity_id'])
    entity_type = str(context['entity_type'])
    entity_id = UUID(context['entity_id'])
    decision = str(context['decision'])
    signature = str(context['signature'])

    config = await _fetch_config(db, legal_entity_id)
    if config is None or not config.action_secret:
        return JSONResponse({'error': {'message': 'Mattermost integration is not configured for actions.'}})
    expected = _signature(config.action_secret, legal_entity_id, entity_type, entity_id, decision)
    if not hmac.compare_digest(expected, signature):
        return JSONResponse({'error': {'message': 'Invalid action signature.'}})

    actor = await _resolve_employee_from_mattermost(db, payload.get('user_id'), None)
    actor_employee_id = actor[0] if actor else None

    if entity_type == 'leave_request':
        note = 'Approved via Mattermost' if decision == 'approved' else 'Rejected via Mattermost'
        leave_row = await db.fetchrow(
            'SELECT approval_stage, status::text AS status FROM leave_requests WHERE id = $1',
            entity_id,
        )
        if leave_row is None:
            return JSONResponse({'error': {'message': 'Leave request not found.'}})
        if leave_row['status'] != 'submitted':
            return JSONResponse({'update': {'message': 'Leave request was already processed.'}})
        if decision == 'approved' and leave_row['approval_stage'] == 'manager_pending':
            await db.execute(
                """
                UPDATE leave_requests
                   SET approval_stage = 'hr_pending',
                       updated_at = now()
                 WHERE id = $1
                """,
                entity_id,
            )
            await db.execute(
                """
                INSERT INTO leave_request_approvals (leave_request_id, approver_employee_id, decision, decision_note, decided_via)
                VALUES ($1, $2, 'approved'::approval_status, $3, 'mattermost')
                """,
                entity_id,
                actor_employee_id,
                'Manager approved via Mattermost',
            )
            await send_leave_approval_request(db, entity_id)
            return JSONResponse(
                {
                    'update': {'message': 'Manager approval recorded and sent to HR.'},
                    'ephemeral_text': 'You approved the manager stage.',
                }
            )
        await db.execute(
            """
            UPDATE leave_requests
               SET status = $2::approval_status,
                   approved_at = CASE WHEN $2 = 'approved' THEN now() ELSE approved_at END,
                   rejected_at = CASE WHEN $2 = 'rejected' THEN now() ELSE rejected_at END,
                   approved_by_employee_id = CASE WHEN $2 = 'approved' THEN $3 ELSE approved_by_employee_id END,
                   rejection_reason = CASE WHEN $2 = 'rejected' THEN $4 ELSE rejection_reason END,
                   approval_stage = CASE WHEN $2 = 'approved' THEN 'completed' ELSE approval_stage END,
                   updated_at = now()
             WHERE id = $1
               AND status = 'submitted'
            """,
            entity_id,
            decision,
            actor_employee_id,
            note,
        )
        await db.execute(
            """
            INSERT INTO leave_request_approvals (leave_request_id, approver_employee_id, decision, decision_note, decided_via)
            VALUES ($1, $2, $3::approval_status, $4, 'mattermost')
            """,
            entity_id,
            actor_employee_id,
            decision,
            note,
        )
        return JSONResponse({'update': {'message': f'Leave request {decision}.'}, 'ephemeral_text': f'You {decision} the leave request.'})

    if entity_type == 'expense_claim':
        note = 'Approved via Mattermost' if decision == 'approved' else 'Rejected via Mattermost'
        await db.execute(
            """
            UPDATE expense_claims
               SET status = $2::approval_status,
                   approved_at = CASE WHEN $2 = 'approved' THEN now() ELSE approved_at END,
                   approved_by_employee_id = CASE WHEN $2 = 'approved' THEN $3 ELSE approved_by_employee_id END,
                   rejection_reason = CASE WHEN $2 = 'rejected' THEN $4 ELSE rejection_reason END,
                   updated_at = now()
             WHERE id = $1
               AND status = 'submitted'
            """,
            entity_id,
            decision,
            actor_employee_id,
            note,
        )
        await db.execute(
            """
            INSERT INTO expense_claim_approvals (expense_claim_id, approver_employee_id, decision, decision_note, decided_via)
            VALUES ($1, $2, $3::approval_status, $4, 'mattermost')
            """,
            entity_id,
            actor_employee_id,
            decision,
            note,
        )
        return JSONResponse({'update': {'message': f'Expense claim {decision}.'}, 'ephemeral_text': f'You {decision} the expense claim.'})

    return JSONResponse({'error': {'message': 'Unsupported action type.'}})


@MATTERMOST_ROUTER.post('/leave-requests')
async def create_leave_request(request: Request, payload: LeaveRequestCreate) -> dict[str, str]:
    actor = await require_actor(request)
    db = get_db_from_request(request)
    employee_id = payload.employee_id or actor.employee_id
    if employee_id != actor.employee_id and not actor.has('employee.manage'):
        raise HTTPException(status_code=403, detail='You can only create leave requests for yourself unless you manage employees')

    manager_employee_id = await db.fetchval(
        'SELECT coalesce(line_manager_id, manager_employee_id) FROM employees WHERE id = $1',
        employee_id,
    )
    requested_days = payload.requested_days or await _leave_business_days(db, payload.start_date, payload.end_date)
    leave_request_id = await db.fetchval(
        """
        INSERT INTO leave_requests (
            employee_id, leave_type_id, manager_employee_id, start_date, end_date, requested_days, reason, status, approval_stage
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, 'submitted', 'manager_pending')
        RETURNING id
        """,
        employee_id,
        payload.leave_type_id,
        manager_employee_id,
        payload.start_date,
        payload.end_date,
        requested_days,
        payload.reason,
    )
    await send_leave_approval_request(db, leave_request_id)
    return {'leave_request_id': str(leave_request_id)}


@MATTERMOST_ROUTER.post('/expense-claims')
async def create_expense_claim(request: Request, payload: ExpenseClaimCreate) -> dict[str, str]:
    actor = await require_actor(request)
    db = get_db_from_request(request)
    employee_id = payload.employee_id or actor.employee_id
    if employee_id != actor.employee_id and not actor.has('employee.manage'):
        raise HTTPException(status_code=403, detail='You can only create expense claims for yourself unless you manage employees')
    if not payload.items:
        raise HTTPException(status_code=400, detail='Expense claims require at least one item')
    manager_employee_id = await db.fetchval('SELECT manager_employee_id FROM employees WHERE id = $1', employee_id)
    total_amount = sum((item.amount for item in payload.items), start=Decimal('0.00'))
    tx = await db.transaction()
    try:
        claim_id = await tx.connection.fetchval(
            """
            INSERT INTO expense_claims (employee_id, manager_employee_id, claim_date, currency_code, total_amount, status)
            VALUES ($1, $2, $3, $4, $5, 'submitted')
            RETURNING id
            """,
            employee_id,
            manager_employee_id,
            payload.claim_date,
            payload.currency_code.upper(),
            total_amount,
        )
        await tx.connection.executemany(
            """
            INSERT INTO expense_claim_items (expense_claim_id, expense_date, category_code, description, amount, attachment_url)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            [
                (
                    claim_id,
                    item.expense_date,
                    item.category_code,
                    item.description,
                    item.amount,
                    item.attachment_url,
                )
                for item in payload.items
            ],
        )
        await tx.commit()
    except Exception:
        await tx.rollback()
        raise
    await send_expense_approval_request(db, claim_id)
    return {'expense_claim_id': str(claim_id)}
