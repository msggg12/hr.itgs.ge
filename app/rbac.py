from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from .db import Database


class AuthorizationError(PermissionError):
    pass


@dataclass(slots=True)
class ActorContext:
    employee_id: UUID
    legal_entity_id: UUID
    department_id: UUID | None
    permissions: set[str] = field(default_factory=set)
    role_codes: set[str] = field(default_factory=set)
    managed_department_ids: set[UUID] = field(default_factory=set)
    editable_department_ids: set[UUID] = field(default_factory=set)

    @property
    def is_hr(self) -> bool:
        return bool({'HR', 'ADMIN', 'TENANT_ADMIN'} & self.role_codes)

    def has(self, permission_code: str) -> bool:
        return permission_code in self.permissions or 'ADMIN' in self.role_codes


async def load_actor_context(db: Database, employee_id: UUID) -> ActorContext:
    row = await db.fetchrow(
        """
        SELECT
            e.id AS employee_id,
            e.legal_entity_id,
            e.department_id,
            array_remove(array_agg(DISTINCT ar.id::text), NULL) AS role_ids,
            array_remove(array_agg(DISTINCT ar.code::text), NULL) AS role_codes
          FROM employees e
         LEFT JOIN employee_access_roles ear ON ear.employee_id = e.id
         LEFT JOIN access_roles ar ON ar.id = ear.access_role_id
         WHERE e.id = $1
           AND e.employment_status = 'active'
           AND e.deleted_at IS NULL
         GROUP BY e.id, e.legal_entity_id, e.department_id
        """,
        employee_id,
    )
    if row is None:
        raise AuthorizationError('Actor does not exist or is not active')

    role_ids = [UUID(role_id) for role_id in (row['role_ids'] or []) if role_id]
    base_permission_rows = []
    override_rows = []
    if role_ids:
        base_permission_rows = await db.fetch(
            """
            SELECT access_role_id, permission_code
              FROM access_role_permissions
             WHERE access_role_id = ANY($1::uuid[])
            """,
            role_ids,
        )
        override_rows = await db.fetch(
            """
            SELECT access_role_id, permission_code, is_enabled
              FROM tenant_role_permission_overrides
             WHERE legal_entity_id = $1
               AND access_role_id = ANY($2::uuid[])
            """,
            row['legal_entity_id'],
            role_ids,
        )

    permissions_by_role: dict[UUID, set[str]] = {role_id: set() for role_id in role_ids}
    for record in base_permission_rows:
        permissions_by_role.setdefault(record['access_role_id'], set()).add(record['permission_code'])
    for record in override_rows:
        role_permissions = permissions_by_role.setdefault(record['access_role_id'], set())
        if record['is_enabled']:
            role_permissions.add(record['permission_code'])
        else:
            role_permissions.discard(record['permission_code'])
    effective_permissions = {
        permission
        for role_permissions in permissions_by_role.values()
        for permission in role_permissions
        if permission
    }

    managed_departments = await db.fetch(
        """
        SELECT DISTINCT id
          FROM departments
         WHERE manager_employee_id = $1
        UNION
        SELECT DISTINCT department_id AS id
          FROM employees
         WHERE manager_employee_id = $1
           AND department_id IS NOT NULL
        UNION
        SELECT DISTINCT department_id AS id
          FROM department_schedule_managers
         WHERE employee_id = $1
        """,
        employee_id,
    )
    editable_departments = await db.fetch(
        """
        SELECT DISTINCT department_id AS id
          FROM department_employee_editors
         WHERE employee_id = $1
        """,
        employee_id,
    )
    return ActorContext(
        employee_id=row['employee_id'],
        legal_entity_id=row['legal_entity_id'],
        department_id=row['department_id'],
        permissions=effective_permissions,
        role_codes={code.upper() for code in (row['role_codes'] or []) if code},
        managed_department_ids={record['id'] for record in managed_departments if record['id'] is not None},
        editable_department_ids={record['id'] for record in editable_departments if record['id'] is not None},
    )


async def apply_rls_context(conn: object, actor: ActorContext) -> None:
    await conn.execute("SELECT set_config('app.current_legal_entity_id', $1, true)", str(actor.legal_entity_id))
    await conn.execute("SELECT set_config('app.current_employee_id', $1, true)", str(actor.employee_id))
    await conn.execute("SELECT set_config('app.is_hr', $1, true)", 'true' if actor.is_hr else 'false')
    await conn.execute(
        "SELECT set_config('app.managed_department_ids', $1, true)",
        ','.join(str(dep_id) for dep_id in actor.managed_department_ids),
    )
    await conn.execute(
        "SELECT set_config('app.can_read_assets_all', $1, true)",
        'true' if actor.has('assets.read_all') or actor.has('assets.manage') else 'false',
    )


def ensure_permission(actor: ActorContext, permission_code: str) -> None:
    if not actor.has(permission_code):
        raise AuthorizationError(f'Missing permission: {permission_code}')


def can_view_employee_directory(actor: ActorContext) -> bool:
    return actor.has('employee.directory.read') or actor.has('employee.read_department') or actor.has('employee.manage')


def employee_directory_scope(actor: ActorContext) -> str:
    if actor.has('employee.manage') or actor.has('employee.directory.read'):
        return 'all'
    if actor.has('employee.read_department'):
        return 'department'
    return 'self'


def can_edit_employee_profiles(actor: ActorContext, target_department_id: UUID | None = None) -> bool:
    if actor.has('employee.manage'):
        return True
    if not actor.has('employee.edit'):
        return False
    if target_department_id is None:
        return bool(actor.editable_department_ids)
    return target_department_id in actor.editable_department_ids


def can_import_employees(actor: ActorContext) -> bool:
    return actor.has('employee.import') or actor.has('employee.manage')


def can_export_employees(actor: ActorContext) -> bool:
    return actor.has('employee.export') or actor.has('employee.manage')


def can_view_employee_record(actor: ActorContext, target_employee_id: UUID, target_department_id: UUID | None) -> bool:
    if actor.employee_id == target_employee_id and actor.has('employee.read_self'):
        return True
    if actor.has('employee.manage') or actor.has('employee.directory.read'):
        return True
    if (
        target_department_id is not None
        and actor.has('employee.read_department')
        and target_department_id in actor.managed_department_ids
    ):
        return True
    return False


def ensure_can_view_attendance(actor: ActorContext, target_employee_id: UUID, target_department_id: UUID | None) -> None:
    if actor.has('attendance.read_all'):
        return
    if actor.employee_id == target_employee_id and actor.has('attendance.read_self'):
        return
    if (
        target_department_id is not None
        and actor.has('attendance.read_department')
        and target_department_id in actor.managed_department_ids
    ):
        return
    raise AuthorizationError('You are not allowed to view this attendance data')


def ensure_can_export_payroll(actor: ActorContext) -> None:
    if not actor.has('payroll.export'):
        raise AuthorizationError('Only payroll-capable HR roles can export payroll')


def ensure_can_see_compensation(actor: ActorContext) -> None:
    if not actor.has('compensation.read_all'):
        raise AuthorizationError('Salary data is limited to HR roles')


def can_edit_shift_schedule(actor: ActorContext, employee_department_id: UUID | None) -> bool:
    """Admin / Tenant Admin, or manager of the employee's department (dept head)."""
    if bool({'ADMIN', 'TENANT_ADMIN'} & actor.role_codes):
        return True
    if employee_department_id is not None and employee_department_id in actor.managed_department_ids:
        return True
    return False
