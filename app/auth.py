from __future__ import annotations

import asyncio
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from html import escape
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import jwt
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from passlib.context import CryptContext
from pydantic import BaseModel, Field

from .config import settings
from .db import Database, set_database_rls_context
from .mail_engine import send_and_log_email
from .rbac import load_actor_context

AUTH_ROUTER = APIRouter(prefix='/auth', tags=['auth'])
PASSWORD_CONTEXT = CryptContext(schemes=['pbkdf2_sha256'], deprecated='auto')
BASE_DIR = Path(__file__).resolve().parent.parent
PROFILE_UPLOADS_DIR = BASE_DIR / 'static' / 'uploads' / 'profile'


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=255)
    platform: str | None = Field(default=None, max_length=64)
    device_label: str | None = Field(default=None, max_length=255)
    app_version: str | None = Field(default=None, max_length=64)
    push_token: str | None = Field(default=None, max_length=512)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)
    platform: str | None = Field(default=None, max_length=64)
    device_label: str | None = Field(default=None, max_length=255)
    app_version: str | None = Field(default=None, max_length=64)
    push_token: str | None = Field(default=None, max_length=512)


class PasswordResetRequest(BaseModel):
    username_or_email: str = Field(min_length=1, max_length=255)


class PasswordResetConfirmRequest(BaseModel):
    reset_token: str = Field(min_length=24)
    new_password: str = Field(min_length=10, max_length=255)


class InviteAcceptRequest(BaseModel):
    invite_token: str = Field(min_length=24)
    new_password: str = Field(min_length=10, max_length=255)


def hash_password(password: str) -> str:
    return PASSWORD_CONTEXT.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return PASSWORD_CONTEXT.verify(password, password_hash)


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _safe_file_name(value: str) -> str:
    return ''.join(char if char.isalnum() or char in {'-', '_', '.'} else '_' for char in value).strip('._') or 'upload.bin'


def _auth_app_link(param_name: str, token: str) -> str:
    return f"{settings.public_base_url}/ux/app?{param_name}={token}"


def _email_layout(*, eyebrow: str, title: str, body_html: str, action_label: str, action_url: str, footer: str) -> str:
    return f"""
    <div style="margin:0;padding:32px;background:#edf2ff;font-family:'Segoe UI',Arial,sans-serif;color:#172033;">
      <div style="max-width:640px;margin:0 auto;background:rgba(255,255,255,0.98);border-radius:28px;overflow:hidden;box-shadow:0 24px 80px rgba(15,23,42,0.16);">
        <div style="padding:24px 32px;background:linear-gradient(135deg,#1f2f50 0%,#243a63 58%,#f7fafc 58%,#ffffff 100%);color:#ffffff;">
          <div style="font-size:11px;letter-spacing:0.28em;text-transform:uppercase;opacity:0.75;">{escape(eyebrow)}</div>
          <h1 style="margin:18px 0 0;font-size:30px;line-height:1.15;font-weight:700;">{escape(title)}</h1>
        </div>
        <div style="padding:32px;">
          <div style="font-size:15px;line-height:1.7;color:#334155;">{body_html}</div>
          <div style="margin-top:28px;">
            <a href="{escape(action_url)}" style="display:inline-block;padding:14px 22px;border-radius:14px;background:linear-gradient(135deg,#2563eb,#1d4ed8);color:#ffffff;text-decoration:none;font-weight:700;">
              {escape(action_label)}
            </a>
          </div>
          <p style="margin:28px 0 0;font-size:13px;line-height:1.6;color:#64748b;">{escape(footer)}</p>
        </div>
      </div>
    </div>
    """.strip()


def _hash_token_value(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _client_ip(request: Request) -> str | None:
    for source in (
        request.headers.get('x-forwarded-for'),
        request.headers.get('x-real-ip'),
        request.client.host if request.client else None,
    ):
        if not source:
            continue
        candidate = source.split(',')[0].strip()
        if candidate:
            return candidate
    return None


async def _store_profile_photo(upload: UploadFile, employee_id: UUID) -> tuple[str, int]:
    file_name = (upload.filename or '').lower()
    content_type = (upload.content_type or '').lower()
    if not (content_type.startswith('image/') or file_name.endswith(('.jpg', '.jpeg', '.png', '.webp'))):
        raise HTTPException(status_code=422, detail='Profile photo must be an image file')
    payload = await upload.read()
    if not payload:
        raise HTTPException(status_code=422, detail='Uploaded profile photo is empty')
    PROFILE_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(file_name).suffix or '.jpg'
    stored_name = f"invite_{employee_id}_{secrets.token_hex(8)}{suffix}"
    absolute_path = PROFILE_UPLOADS_DIR / stored_name
    await asyncio.to_thread(absolute_path.write_bytes, payload)
    return f"/static/uploads/profile/{stored_name}", len(payload)


def _token_payload(
    *,
    employee_id: UUID,
    legal_entity_id: UUID,
    username: str,
    token_type: str,
    ttl_minutes: int,
) -> dict[str, Any]:
    issued_at = datetime.now(UTC)
    return {
        'sub': str(employee_id),
        'legal_entity_id': str(legal_entity_id),
        'username': username,
        'type': token_type,
        'iat': int(issued_at.timestamp()),
        'exp': int((issued_at + timedelta(minutes=ttl_minutes)).timestamp()),
    }


def create_access_token(*, employee_id: UUID, legal_entity_id: UUID, username: str) -> str:
    payload = _token_payload(
        employee_id=employee_id,
        legal_entity_id=legal_entity_id,
        username=username,
        token_type='access',
        ttl_minutes=settings.access_token_ttl_minutes,
    )
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(*, employee_id: UUID, legal_entity_id: UUID, username: str, session_id: UUID, token_jti: str) -> str:
    payload = _token_payload(
        employee_id=employee_id,
        legal_entity_id=legal_entity_id,
        username=username,
        token_type='refresh',
        ttl_minutes=settings.refresh_token_ttl_minutes,
    )
    payload['sid'] = str(session_id)
    payload['jti'] = token_jti
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str, expected_type: str = 'access') -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid or expired token') from exc
    if payload.get('type') != expected_type:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Unexpected token type')
    return payload


async def _authenticate_identity(db: Database, username: str, password: str) -> dict[str, Any]:
    row = await db.fetchrow(
        """
        SELECT ai.id,
               ai.employee_id,
               ai.username,
               ai.password_hash,
               ai.is_active,
               e.legal_entity_id,
               e.email,
               e.employment_status
          FROM auth_identities ai
          JOIN employees e ON e.id = ai.employee_id
         WHERE ai.username = $1
            OR e.email = $1
            OR e.employee_number = $1
         LIMIT 1
        """,
        username,
    )
    if row is None or not row['is_active'] or row['employment_status'] != 'active':
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid credentials')
    if not verify_password(password, row['password_hash']):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid credentials')
    return dict(row)


def _request_tenant_legal_entity_id(request: Request) -> UUID | None:
    raw_tenant_legal_entity_id = getattr(request.state, 'tenant_legal_entity_id', None)
    if not raw_tenant_legal_entity_id:
        return None
    return UUID(str(raw_tenant_legal_entity_id))


def _require_request_tenant_legal_entity_id(request: Request) -> UUID:
    tenant_legal_entity_id = _request_tenant_legal_entity_id(request)
    if tenant_legal_entity_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Tenant could not be resolved for this request')
    set_database_rls_context(legal_entity_id=tenant_legal_entity_id)
    return tenant_legal_entity_id


async def _create_refresh_session(
    db: Database,
    *,
    employee_id: UUID,
    legal_entity_id: UUID,
    username: str,
    request: Request,
    platform: str | None = None,
    device_label: str | None = None,
    app_version: str | None = None,
    push_token: str | None = None,
) -> tuple[UUID, str, str]:
    session_id = uuid4()
    token_jti = secrets.token_urlsafe(18)
    refresh_token = create_refresh_token(
        employee_id=employee_id,
        legal_entity_id=legal_entity_id,
        username=username,
        session_id=session_id,
        token_jti=token_jti,
    )
    await db.execute(
        """
        INSERT INTO auth_refresh_sessions (
            id, employee_id, legal_entity_id, username, token_jti, token_hash,
            platform, device_label, app_version, user_agent, push_token,
            created_ip, last_seen_at, expires_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, now(), now() + make_interval(mins => $13))
        """,
        session_id,
        employee_id,
        legal_entity_id,
        username,
        token_jti,
        _hash_token_value(refresh_token),
        _clean_text(platform),
        _clean_text(device_label),
        _clean_text(app_version),
        request.headers.get('user-agent'),
        _clean_text(push_token),
        _client_ip(request),
        settings.refresh_token_ttl_minutes,
    )
    return session_id, token_jti, refresh_token


async def _token_bundle(
    db: Database,
    *,
    employee_id: UUID,
    legal_entity_id: UUID,
    username: str,
    request: Request,
    platform: str | None = None,
    device_label: str | None = None,
    app_version: str | None = None,
    push_token: str | None = None,
) -> dict[str, Any]:
    set_database_rls_context(legal_entity_id=legal_entity_id, employee_id=employee_id)
    actor = await load_actor_context(db, employee_id)
    set_database_rls_context(
        legal_entity_id=actor.legal_entity_id,
        employee_id=actor.employee_id,
        is_hr=actor.is_hr,
        managed_department_ids=actor.managed_department_ids,
        can_read_assets_all=actor.has('assets.read_all') or actor.has('assets.manage'),
    )
    access_token = create_access_token(
        employee_id=employee_id,
        legal_entity_id=legal_entity_id,
        username=username,
    )
    session_id, _, refresh_token = await _create_refresh_session(
        db,
        employee_id=employee_id,
        legal_entity_id=legal_entity_id,
        username=username,
        request=request,
        platform=platform,
        device_label=device_label,
        app_version=app_version,
        push_token=push_token,
    )
    return {
        'access_token': access_token,
        'refresh_token': refresh_token,
        'refresh_session_id': str(session_id),
        'token_type': 'bearer',
        'expires_in': settings.access_token_ttl_minutes * 60,
        'employee': {
            'employee_id': str(actor.employee_id),
            'legal_entity_id': str(actor.legal_entity_id),
            'department_id': str(actor.department_id) if actor.department_id else None,
            'role_codes': sorted(actor.role_codes),
            'permissions': sorted(actor.permissions),
        },
    }


@AUTH_ROUTER.post('/login')
async def login(request: Request, payload: LoginRequest) -> dict[str, Any]:
    db: Database = request.app.state.db
    request_tenant_legal_entity_id = _require_request_tenant_legal_entity_id(request)
    identity = await _authenticate_identity(db, payload.username.strip(), payload.password)
    if request_tenant_legal_entity_id != identity['legal_entity_id']:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='This user belongs to a different tenant')
    set_database_rls_context(legal_entity_id=identity['legal_entity_id'], employee_id=identity['employee_id'])
    await db.execute('UPDATE auth_identities SET last_login_at = now(), updated_at = now() WHERE id = $1', identity['id'])
    return await _token_bundle(
        db,
        employee_id=identity['employee_id'],
        legal_entity_id=identity['legal_entity_id'],
        username=identity['username'],
        request=request,
        platform=payload.platform,
        device_label=payload.device_label,
        app_version=payload.app_version,
        push_token=payload.push_token,
    )


@AUTH_ROUTER.post('/refresh')
async def refresh(request: Request, payload: RefreshRequest) -> dict[str, Any]:
    db: Database = request.app.state.db
    token_payload = decode_token(payload.refresh_token, expected_type='refresh')
    employee_id = UUID(str(token_payload['sub']))
    legal_entity_id = UUID(str(token_payload['legal_entity_id']))
    set_database_rls_context(legal_entity_id=legal_entity_id, employee_id=employee_id)
    session_id = UUID(str(token_payload.get('sid')))
    token_jti = str(token_payload.get('jti') or '')
    request_tenant_legal_entity_id = _request_tenant_legal_entity_id(request)
    if request_tenant_legal_entity_id and request_tenant_legal_entity_id != legal_entity_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Refresh token belongs to another tenant')
    session = await db.fetchrow(
        """
        SELECT id, username
          FROM auth_refresh_sessions
         WHERE id = $1
           AND employee_id = $2
           AND legal_entity_id = $3
           AND token_jti = $4
           AND token_hash = $5
           AND revoked_at IS NULL
           AND rotated_at IS NULL
           AND expires_at >= now()
         LIMIT 1
        """,
        session_id,
        employee_id,
        legal_entity_id,
        token_jti,
        _hash_token_value(payload.refresh_token),
    )
    if session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Refresh session is invalid or expired')
    username = str(token_payload.get('username') or employee_id)
    bundle = await _token_bundle(
        db,
        employee_id=employee_id,
        legal_entity_id=legal_entity_id,
        username=username,
        request=request,
        platform=payload.platform,
        device_label=payload.device_label,
        app_version=payload.app_version,
        push_token=payload.push_token,
    )
    await db.execute(
        """
        UPDATE auth_refresh_sessions
           SET rotated_at = now(),
               replaced_by_session_id = $2,
               last_seen_at = now()
         WHERE id = $1
        """,
        session_id,
        UUID(bundle['refresh_session_id']),
    )
    return bundle


@AUTH_ROUTER.get('/me')
async def me(request: Request) -> dict[str, Any]:
    from .api_support import require_actor

    actor = await require_actor(request)
    return {
        'employee_id': str(actor.employee_id),
        'legal_entity_id': str(actor.legal_entity_id),
        'department_id': str(actor.department_id) if actor.department_id else None,
        'role_codes': sorted(actor.role_codes),
        'permissions': sorted(actor.permissions),
        'managed_department_ids': [str(dep_id) for dep_id in sorted(actor.managed_department_ids, key=str)],
    }


@AUTH_ROUTER.post('/logout')
async def logout(request: Request, payload: RefreshRequest | None = None) -> dict[str, str]:
    db: Database = request.app.state.db
    if payload and payload.refresh_token:
        try:
            token_payload = decode_token(payload.refresh_token, expected_type='refresh')
            await db.execute(
                """
                UPDATE auth_refresh_sessions
                   SET revoked_at = now(),
                       last_seen_at = now()
                 WHERE id = $1
                   AND token_hash = $2
                """,
                UUID(str(token_payload.get('sid'))),
                _hash_token_value(payload.refresh_token),
            )
        except Exception:
            pass
    return {'status': 'logged_out'}


@AUTH_ROUTER.get('/sessions')
async def active_sessions(request: Request) -> dict[str, list[dict[str, Any]]]:
    from .api_support import require_actor

    actor = await require_actor(request)
    db: Database = request.app.state.db
    rows = await db.fetch(
        """
        SELECT id, platform, device_label, app_version, user_agent, created_ip, last_seen_at, expires_at, created_at
          FROM auth_refresh_sessions
         WHERE employee_id = $1
           AND revoked_at IS NULL
           AND expires_at >= now()
         ORDER BY created_at DESC
        """,
        actor.employee_id,
    )
    return {
        'items': [
            {
                'id': str(row['id']),
                'platform': row['platform'],
                'device_label': row['device_label'],
                'app_version': row['app_version'],
                'user_agent': row['user_agent'],
                'created_ip': row['created_ip'],
                'last_seen_at': row['last_seen_at'].isoformat() if row['last_seen_at'] else None,
                'expires_at': row['expires_at'].isoformat() if row['expires_at'] else None,
                'created_at': row['created_at'].isoformat() if row['created_at'] else None,
            }
            for row in rows
        ]
    }


@AUTH_ROUTER.delete('/sessions/{session_id}')
async def revoke_session(request: Request, session_id: UUID) -> dict[str, str]:
    from .api_support import require_actor

    actor = await require_actor(request)
    db: Database = request.app.state.db
    updated = await db.execute(
        """
        UPDATE auth_refresh_sessions
           SET revoked_at = now(),
               last_seen_at = now()
         WHERE id = $1
           AND employee_id = $2
        """,
        session_id,
        actor.employee_id,
    )
    if updated.endswith('0'):
        raise HTTPException(status_code=404, detail='Session not found')
    return {'status': 'revoked'}


@AUTH_ROUTER.post('/password-reset/request')
async def request_password_reset(request: Request, payload: PasswordResetRequest) -> dict[str, str]:
    db: Database = request.app.state.db
    request_tenant_legal_entity_id = _require_request_tenant_legal_entity_id(request)
    identity = await db.fetchrow(
        """
        SELECT ai.id AS identity_id,
               ai.employee_id,
               ai.username,
               e.legal_entity_id,
               e.first_name,
               e.last_name,
               e.email
          FROM auth_identities ai
          JOIN employees e ON e.id = ai.employee_id
         WHERE ai.username = $1
            OR e.email = $1
         LIMIT 1
        """,
        payload.username_or_email.strip(),
    )
    if identity is None:
        return {'status': 'accepted'}
    if request_tenant_legal_entity_id != identity['legal_entity_id']:
        return {'status': 'accepted'}
    if not identity['email'] or not settings.smtp_host:
        return {'status': 'accepted'}

    reset_token = secrets.token_urlsafe(32)
    await db.execute(
        """
        INSERT INTO password_reset_tokens (employee_id, identity_id, reset_token, expires_at)
        VALUES ($1, $2, $3, now() + make_interval(mins => $4))
        """,
        identity['employee_id'],
        identity['identity_id'],
        reset_token,
        settings.password_reset_ttl_minutes,
    )
    reset_link = _auth_app_link('reset_token', reset_token)
    full_name = ' '.join(part for part in [identity['first_name'], identity['last_name']] if part).strip()
    body_text = (
        f"{full_name},\n\n"
        f"Use this link to reset your HRMS password:\n{reset_link}\n\n"
        f"The link remains valid for {settings.password_reset_ttl_minutes} minutes."
    )
    body_html = _email_layout(
        eyebrow='ITGS HR',
        title='Reset your password',
        body_html=(
            f"<p>Hello {escape(full_name or identity['username'])},</p>"
            f"<p>We received a request to reset your password. Use the secure link below to choose a new password.</p>"
        ),
        action_label='Reset Password',
        action_url=reset_link,
        footer=f'This link expires in {settings.password_reset_ttl_minutes} minutes.',
    )
    await send_and_log_email(
        db,
        legal_entity_id=identity['legal_entity_id'],
        event_type='password_reset',
        event_key=str(identity['employee_id']),
        to_email=identity['email'],
        subject='Reset your HRMS password',
        body_text=body_text,
        body_html=body_html,
        extra_payload={'employee_id': str(identity['employee_id'])},
    )
    return {'status': 'accepted'}


@AUTH_ROUTER.get('/password-reset/resolve')
async def resolve_password_reset_token(request: Request, reset_token: str) -> dict[str, Any]:
    db: Database = request.app.state.db
    _require_request_tenant_legal_entity_id(request)
    row = await db.fetchrow(
        """
        SELECT prt.id,
               e.email,
               e.first_name,
               e.last_name,
               prt.expires_at
          FROM password_reset_tokens prt
          JOIN employees e ON e.id = prt.employee_id
         WHERE prt.reset_token = $1
           AND prt.used_at IS NULL
           AND prt.expires_at >= now()
         ORDER BY prt.created_at DESC
         LIMIT 1
        """,
        reset_token,
    )
    if row is None:
        raise HTTPException(status_code=400, detail='Password reset link is invalid or expired')
    return {
        'status': 'valid',
        'email': row['email'],
        'full_name': ' '.join(part for part in [row['first_name'], row['last_name']] if part).strip(),
        'expires_at': row['expires_at'].isoformat() if row['expires_at'] else None,
    }


@AUTH_ROUTER.post('/password-reset/confirm')
async def confirm_password_reset(request: Request, payload: PasswordResetConfirmRequest) -> dict[str, str]:
    db: Database = request.app.state.db
    _require_request_tenant_legal_entity_id(request)
    reset_row = await db.fetchrow(
        """
        SELECT id, employee_id, identity_id
          FROM password_reset_tokens
         WHERE reset_token = $1
           AND used_at IS NULL
           AND expires_at >= now()
         ORDER BY created_at DESC
         LIMIT 1
        """,
        payload.reset_token,
    )
    if reset_row is None:
        raise HTTPException(status_code=400, detail='Password reset link is invalid or expired')
    await db.execute(
        'UPDATE auth_identities SET password_hash = $2, updated_at = now() WHERE id = $1',
        reset_row['identity_id'],
        hash_password(payload.new_password),
    )
    await db.execute('UPDATE password_reset_tokens SET used_at = now() WHERE id = $1', reset_row['id'])
    try:
        from .mattermost_integration import ensure_mattermost_account_for_employee
        await ensure_mattermost_account_for_employee(db, reset_row['employee_id'])
    except Exception:
        pass
    return {'status': 'reset'}


@AUTH_ROUTER.get('/invite/resolve')
async def resolve_invite(request: Request, invite_token: str) -> dict[str, Any]:
    db: Database = request.app.state.db
    _require_request_tenant_legal_entity_id(request)
    invite = await db.fetchrow(
        """
        SELECT ai.id AS invite_id,
               ai.employee_id,
               ai.username,
               ai.recipient_email,
               ai.expires_at,
               e.email,
               e.first_name,
               e.last_name,
               d.name_ka AS department_name_ka,
               d.name_en AS department_name_en,
               jr.title_ka AS job_role_title_ka,
               jr.title_en AS job_role_title_en,
               m.first_name || ' ' || m.last_name AS manager_name
          FROM auth_invites ai
          JOIN employees e ON e.id = ai.employee_id
     LEFT JOIN departments d ON d.id = e.department_id
     LEFT JOIN job_roles jr ON jr.id = e.job_role_id
     LEFT JOIN employees m ON m.id = e.manager_employee_id
         WHERE ai.invite_token = $1
           AND ai.accepted_at IS NULL
           AND ai.expires_at >= now()
         ORDER BY ai.created_at DESC
         LIMIT 1
        """,
        invite_token,
    )
    if invite is None:
        raise HTTPException(status_code=400, detail='Invite link is invalid or expired')
    return {
        'status': 'valid',
        'username': invite['username'],
        'email': invite['email'] or invite['recipient_email'],
        'full_name': ' '.join(part for part in [invite['first_name'], invite['last_name']] if part).strip(),
        'department_name': invite['department_name_ka'] or invite['department_name_en'],
        'job_role_title': invite['job_role_title_ka'] or invite['job_role_title_en'],
        'manager_name': invite['manager_name'],
        'expires_at': invite['expires_at'].isoformat() if invite['expires_at'] else None,
    }


@AUTH_ROUTER.post('/invite/complete')
async def complete_invite_registration(
    request: Request,
    invite_token: str = Form(...),
    personal_number: str = Form(...),
    mobile_phone: str = Form(...),
    password: str = Form(...),
    profile_photo: UploadFile | None = File(default=None),
) -> dict[str, Any]:
    if len(password.strip()) < 10:
        raise HTTPException(status_code=422, detail='Password must be at least 10 characters long')
    normalized_personal_number = ''.join(char for char in personal_number if char.isdigit())
    if len(normalized_personal_number) != 11:
        raise HTTPException(status_code=422, detail='Personal ID must contain exactly 11 digits')
    normalized_phone = ''.join(char for char in mobile_phone if char.isdigit())
    if len(normalized_phone) < 9 or len(normalized_phone) > 15:
        raise HTTPException(status_code=422, detail='Phone number must contain between 9 and 15 digits')

    db: Database = request.app.state.db
    _require_request_tenant_legal_entity_id(request)
    invite = await db.fetchrow(
        """
        SELECT ai.id AS invite_id,
               ai.employee_id,
               ai.username,
               e.legal_entity_id
          FROM auth_invites ai
          JOIN employees e ON e.id = ai.employee_id
         WHERE ai.invite_token = $1
           AND ai.accepted_at IS NULL
           AND ai.expires_at >= now()
         ORDER BY ai.created_at DESC
         LIMIT 1
        """,
        invite_token,
    )
    if invite is None:
        raise HTTPException(status_code=400, detail='Invite link is invalid or expired')

    tx = await db.transaction()
    try:
        await tx.connection.execute(
            """
            UPDATE auth_identities
               SET password_hash = $2,
                   is_active = true,
                   updated_at = now()
             WHERE employee_id = $1
            """,
            invite['employee_id'],
            hash_password(password.strip()),
        )
        await tx.connection.execute(
            """
            UPDATE employees
               SET personal_number = $2,
                   mobile_phone = $3,
                   employment_status = 'active',
                   updated_at = now()
             WHERE id = $1
            """,
            invite['employee_id'],
            normalized_personal_number,
            _clean_text(mobile_phone),
        )
        if profile_photo is not None and (profile_photo.filename or '').strip():
            file_url, file_size = await _store_profile_photo(profile_photo, invite['employee_id'])
            await tx.connection.execute(
                """
                INSERT INTO employee_file_uploads (
                    employee_id, legal_entity_id, file_category, file_name, file_url,
                    content_type, file_size, created_by_employee_id
                )
                VALUES ($1, $2, 'profile_photo', $3, $4, $5, $6, $1)
                """,
                invite['employee_id'],
                invite['legal_entity_id'],
                _safe_file_name(profile_photo.filename or 'profile.jpg'),
                file_url,
                profile_photo.content_type,
                file_size,
            )
        await tx.connection.execute(
            'UPDATE auth_invites SET accepted_at = now(), updated_at = now() WHERE id = $1',
            invite['invite_id'],
        )
        await tx.commit()
    except Exception:
        await tx.rollback()
        raise

    try:
        from .mattermost_integration import ensure_mattermost_account_for_employee
        await ensure_mattermost_account_for_employee(db, invite['employee_id'])
    except Exception:
        pass

    return await _token_bundle(
        db,
        employee_id=invite['employee_id'],
        legal_entity_id=invite['legal_entity_id'],
        username=invite['username'],
        request=request,
        platform='web',
        device_label='Invite completion',
    )


@AUTH_ROUTER.post('/invite/accept')
async def accept_invite(request: Request, payload: InviteAcceptRequest) -> dict[str, Any]:
    db: Database = request.app.state.db
    _require_request_tenant_legal_entity_id(request)
    invite = await db.fetchrow(
        """
        SELECT ai.id AS invite_id,
               ai.employee_id,
               ai.username,
               e.legal_entity_id
          FROM auth_invites ai
          JOIN employees e ON e.id = ai.employee_id
         WHERE ai.invite_token = $1
           AND ai.accepted_at IS NULL
           AND ai.expires_at >= now()
         ORDER BY ai.created_at DESC
         LIMIT 1
        """,
        payload.invite_token,
    )
    if invite is None:
        raise HTTPException(status_code=400, detail='Invite link is invalid or expired')
    await db.execute(
        """
        UPDATE auth_identities
           SET password_hash = $2,
               is_active = true,
               updated_at = now()
         WHERE employee_id = $1
        """,
        invite['employee_id'],
        hash_password(payload.new_password),
    )
    await db.execute(
        """
        UPDATE employees
           SET employment_status = 'active',
               updated_at = now()
         WHERE id = $1
        """,
        invite['employee_id'],
    )
    await db.execute('UPDATE auth_invites SET accepted_at = now(), updated_at = now() WHERE id = $1', invite['invite_id'])
    try:
        from .mattermost_integration import ensure_mattermost_account_for_employee
        await ensure_mattermost_account_for_employee(db, invite['employee_id'])
    except Exception:
        pass
    return await _token_bundle(
        db,
        employee_id=invite['employee_id'],
        legal_entity_id=invite['legal_entity_id'],
        username=invite['username'],
        request=request,
        platform='web',
        device_label='Invite acceptance',
    )
