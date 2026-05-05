from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, Request

from .auth import decode_token
from .db import Database, set_database_rls_context
from .rbac import ActorContext, AuthorizationError, load_actor_context


def get_db_from_request(request: Request) -> Database:
    db = getattr(request.app.state, 'db', None)
    if db is None:
        raise HTTPException(status_code=503, detail='Database is not initialized')
    return db


def _bearer_token(request: Request) -> str | None:
    authorization = request.headers.get('Authorization', '')
    if not authorization.lower().startswith('bearer '):
        return None
    return authorization[7:].strip() or None


def get_request_tenant_legal_entity_id(request: Request) -> UUID | None:
    raw_tenant_legal_entity_id = getattr(request.state, 'tenant_legal_entity_id', None)
    if not raw_tenant_legal_entity_id:
        return None
    return UUID(str(raw_tenant_legal_entity_id))


async def require_actor(request: Request) -> ActorContext:
    token = _bearer_token(request)
    if not token:
        raise HTTPException(status_code=401, detail='Bearer access token is required')

    payload = decode_token(token, expected_type='access')
    raw_employee_id = str(payload.get('sub') or '')
    if not raw_employee_id:
        raise HTTPException(status_code=401, detail='Bearer access token subject is required')
    try:
        employee_id = UUID(raw_employee_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail='Actor identifier must be a UUID') from exc

    token_legal_entity = payload.get('legal_entity_id')
    if not token_legal_entity:
        raise HTTPException(status_code=401, detail='Bearer access token legal_entity_id is required')
    try:
        token_legal_entity_id = UUID(str(token_legal_entity))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail='Token legal_entity_id must be a UUID') from exc

    # Load the actor under the token tenant so FORCE RLS applies even to identity lookup.
    set_database_rls_context(legal_entity_id=token_legal_entity_id, employee_id=employee_id)
    db = get_db_from_request(request)
    try:
        actor = await load_actor_context(db, employee_id)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    if actor.legal_entity_id != token_legal_entity_id:
        raise HTTPException(status_code=403, detail='Token legal_entity_id does not match the actor')

    request_tenant_legal_entity_id = get_request_tenant_legal_entity_id(request)
    if request_tenant_legal_entity_id and actor.legal_entity_id != request_tenant_legal_entity_id:
        raise HTTPException(status_code=403, detail='This host is not allowed to access the actor tenant')

    set_database_rls_context(
        legal_entity_id=actor.legal_entity_id,
        employee_id=actor.employee_id,
        is_hr=actor.is_hr,
        managed_department_ids=actor.managed_department_ids,
        can_read_assets_all=actor.has('assets.read_all') or actor.has('assets.manage'),
    )
    return actor
