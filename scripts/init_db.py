from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.auth import hash_password  # noqa: E402
from app.db import Database, apply_current_database_rls_context, set_database_rls_context  # noqa: E402
from app.labor_engine import seed_public_holidays  # noqa: E402
from app.runtime_setup import ensure_runtime_schema  # noqa: E402


def env(name: str, default: str) -> str:
    return os.environ.get(name, default).strip()


async def apply_sql_files(db: Database) -> None:
    base_schema_exists = await db.fetchval("SELECT to_regclass('hrms.legal_entities') IS NOT NULL")
    if not base_schema_exists:
        await db.execute((PROJECT_ROOT / 'sql/001_hrms_schema.sql').read_text(encoding='utf-8'))
    extensions_exist = await db.fetchval("SELECT to_regclass('hrms.auth_identities') IS NOT NULL")
    if not extensions_exist:
        await db.execute((PROJECT_ROOT / 'sql/002_enterprise_extensions.sql').read_text(encoding='utf-8'))


async def apply_phase_migrations(db: Database) -> None:
    for path in sorted((PROJECT_ROOT / 'sql').glob('*.sql')):
        if path.name.startswith(('001_', '002_')):
            continue
        await db.execute(path.read_text(encoding='utf-8'))


async def ensure_card_identity_constraints(db: Database) -> None:
    duplicate_cards = await db.fetchval(
        """
        SELECT count(*)
          FROM (
                SELECT device_id, card_number
                  FROM hrms.employee_device_identities
                 WHERE card_number IS NOT NULL
                   AND card_number <> ''
                   AND is_active = true
                 GROUP BY device_id, card_number
                HAVING count(DISTINCT employee_id) > 1
          ) duplicates
        """
    )
    if duplicate_cards:
        print(f'[init_db] skipped unique card index; duplicate active device cards found: {duplicate_cards}')
        return
    await db.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_employee_device_identities_device_card
            ON hrms.employee_device_identities (device_id, card_number)
         WHERE card_number IS NOT NULL
           AND card_number <> ''
           AND is_active = true
        """
    )


async def ensure_super_admin(db: Database) -> dict[str, str]:
    company_name = env('SUPERADMIN_COMPANY_NAME', 'ITGS HR')
    company_trade_name = env('SUPERADMIN_COMPANY_TRADE_NAME', company_name)
    company_tax_id = env('SUPERADMIN_COMPANY_TAX_ID', 'GE-000000001')
    admin_username = env('SUPERADMIN_USERNAME', 'superadmin')
    admin_password = env('SUPERADMIN_PASSWORD', '')
    if not admin_password:
        raise RuntimeError('SUPERADMIN_PASSWORD is required')
    admin_email = env('SUPERADMIN_EMAIL', '')
    admin_first_name = env('SUPERADMIN_FIRST_NAME', 'System')
    admin_last_name = env('SUPERADMIN_LAST_NAME', 'Administrator')
    admin_personal_number = env('SUPERADMIN_PERSONAL_NUMBER', '00000000000')

    tx = await db.transaction()
    try:
        legal_entity_id = await tx.connection.fetchval(
            """
            INSERT INTO legal_entities (legal_name, trade_name, tax_id, timezone, currency_code, city, country_code)
            VALUES ($1, $2, $3, 'Asia/Tbilisi', 'GEL', 'Tbilisi', 'GE')
            ON CONFLICT (tax_id) DO UPDATE
               SET trade_name = EXCLUDED.trade_name,
                   updated_at = now()
            RETURNING id
            """,
            company_name,
            company_trade_name,
            company_tax_id,
        )
        set_database_rls_context(legal_entity_id=legal_entity_id)
        await apply_current_database_rls_context(tx.connection)
        department_id = await tx.connection.fetchval(
            """
            INSERT INTO departments (legal_entity_id, code, name_en, name_ka)
            VALUES ($1, 'ADMIN', 'Administration', 'ადმინისტრაცია')
            ON CONFLICT (legal_entity_id, code) DO UPDATE
               SET name_en = EXCLUDED.name_en,
                   name_ka = EXCLUDED.name_ka,
                   updated_at = now()
            RETURNING id
            """,
            legal_entity_id,
        )
        job_role_id = await tx.connection.fetchval(
            """
            INSERT INTO job_roles (legal_entity_id, code, title_en, title_ka, is_managerial)
            VALUES ($1, 'SUPER_ADMIN', 'Super Admin', 'სუპერ ადმინი', true)
            ON CONFLICT (legal_entity_id, code) DO UPDATE
               SET title_en = EXCLUDED.title_en,
                   title_ka = EXCLUDED.title_ka,
                   is_managerial = EXCLUDED.is_managerial,
                   updated_at = now()
            RETURNING id
            """,
            legal_entity_id,
        )
        pay_policy_id = await tx.connection.fetchval(
            """
            INSERT INTO pay_policies (
                legal_entity_id, code, name, payroll_cycle, standard_weekly_hours,
                overtime_multiplier, night_bonus_multiplier, holiday_multiplier,
                employee_pension_rate, income_tax_rate
            )
            VALUES ($1, 'STD', 'Standard Georgia Policy', 'monthly', 40.00, 1.25, 0.20, 2.00, 0.02, 0.20)
            ON CONFLICT (legal_entity_id, code) DO UPDATE
               SET name = EXCLUDED.name,
                   updated_at = now()
            RETURNING id
            """,
            legal_entity_id,
        )
        employee_id = await tx.connection.fetchval(
            """
            INSERT INTO employees (
                legal_entity_id, employee_number, personal_number, first_name, last_name, email,
                department_id, job_role_id, hire_date, employment_status
            )
            VALUES ($1, 'ADM-0001', $2, $3, $4, $5, $6, $7, current_date, 'active')
            ON CONFLICT (legal_entity_id, employee_number) DO UPDATE
               SET first_name = EXCLUDED.first_name,
                   last_name = EXCLUDED.last_name,
                   email = EXCLUDED.email,
                   department_id = EXCLUDED.department_id,
                   job_role_id = EXCLUDED.job_role_id,
                   updated_at = now()
            RETURNING id
            """,
            legal_entity_id,
            admin_personal_number,
            admin_first_name,
            admin_last_name,
            admin_email,
            department_id,
            job_role_id,
        )
        await tx.connection.execute(
            """
            INSERT INTO employee_compensation (employee_id, policy_id, effective_from, base_salary, is_pension_participant)
            SELECT $1, $2, current_date, 0, false
             WHERE NOT EXISTS (
                SELECT 1
                  FROM employee_compensation
                 WHERE employee_id = $1
             )
            """,
            employee_id,
            pay_policy_id,
        )
        tenant_admin_role_id = await tx.connection.fetchval(
            """
            INSERT INTO access_roles (code, name_en, name_ka, description)
            VALUES ('TENANT_ADMIN', 'Tenant Administrator', 'კომპანიის ადმინისტრატორი', 'Tenant-scoped administration')
            ON CONFLICT (code) DO UPDATE
               SET name_en = EXCLUDED.name_en,
                   name_ka = EXCLUDED.name_ka,
                   description = EXCLUDED.description,
                   updated_at = now()
            RETURNING id
            """
        )
        await tx.connection.execute(
            """
            INSERT INTO access_role_permissions (access_role_id, permission_code)
            SELECT $1, permission_code
              FROM unnest($2::text[]) AS permission_code
            ON CONFLICT DO NOTHING
            """,
            tenant_admin_role_id,
            [
                'employee.read_self',
                'employee.read_department',
                'employee.manage',
                'attendance.read_self',
                'attendance.read_department',
                'attendance.read_all',
                'attendance.review',
                'compensation.read_all',
                'payroll.export',
                'device.manage',
                'assets.read_self',
                'assets.read_all',
                'assets.manage',
                'recruitment.read',
                'recruitment.manage',
            ],
        )
        admin_role_id = await tx.connection.fetchval("SELECT id FROM access_roles WHERE code = 'ADMIN'")
        await tx.connection.execute(
            """
            INSERT INTO employee_access_roles (employee_id, access_role_id, assigned_by_employee_id)
            VALUES ($1, $2, $1)
            ON CONFLICT DO NOTHING
            """,
            employee_id,
            admin_role_id,
        )
        await tx.connection.execute(
            """
            INSERT INTO auth_identities (employee_id, username, password_hash, is_active)
            VALUES ($1, $2, $3, true)
            ON CONFLICT (username) DO UPDATE
               SET employee_id = EXCLUDED.employee_id,
                   password_hash = EXCLUDED.password_hash,
                   is_active = true,
                   updated_at = now()
            """,
            employee_id,
            admin_username,
            hash_password(admin_password),
        )
        await tx.connection.execute(
            """
            INSERT INTO entity_operation_settings (legal_entity_id, late_arrival_threshold_minutes, require_asset_clearance_for_final_payroll)
            VALUES ($1, 15, true)
            ON CONFLICT (legal_entity_id) DO NOTHING
            """,
            legal_entity_id,
        )
        await tx.commit()
    except Exception:
        await tx.rollback()
        raise

    await db.execute('SELECT hrms.seed_standard_shift_patterns($1)', legal_entity_id)
    await db.execute('SELECT hrms.seed_default_candidate_pipeline_stages($1)', legal_entity_id)
    await db.execute(
        """
        INSERT INTO leave_types (legal_entity_id, code, name_en, name_ka, is_paid, annual_allowance_days, carryover_limit_days)
        VALUES
            ($1, 'ANNUAL', 'Annual Leave', 'წლიური შვებულება', true, 24, 10),
            ($1, 'SICK', 'Sick Leave', 'ბიულეტინი', true, 0, 0)
        ON CONFLICT (legal_entity_id, code) DO UPDATE
           SET name_en = EXCLUDED.name_en,
               name_ka = EXCLUDED.name_ka,
               is_paid = EXCLUDED.is_paid,
               annual_allowance_days = EXCLUDED.annual_allowance_days,
               carryover_limit_days = EXCLUDED.carryover_limit_days,
               updated_at = now()
        """,
        legal_entity_id,
    )
    await db.execute(
        """
        INSERT INTO tenant_subscriptions (legal_entity_id)
        VALUES ($1)
        ON CONFLICT (legal_entity_id) DO NOTHING
        """,
        legal_entity_id,
    )
    public_host = urlparse(env('PUBLIC_BASE_URL', 'http://localhost:8000')).hostname
    if public_host and public_host not in {'localhost', '127.0.0.1'}:
        subdomain = public_host.split('.')[0] if public_host.count('.') >= 2 else None
        await db.execute(
            """
            INSERT INTO tenant_domains (legal_entity_id, host, subdomain, is_primary, is_active)
            VALUES ($1, $2, $3, true, true)
            ON CONFLICT (host) DO UPDATE
               SET legal_entity_id = EXCLUDED.legal_entity_id,
                   subdomain = EXCLUDED.subdomain,
                   is_primary = true,
                   is_active = true,
                   updated_at = now()
            """,
            legal_entity_id,
            public_host,
            subdomain,
        )
    return {
        'legal_entity_id': str(legal_entity_id),
        'department_id': str(department_id),
        'job_role_id': str(job_role_id),
        'pay_policy_id': str(pay_policy_id),
        'employee_id': str(employee_id),
        'username': admin_username,
    }


async def main() -> None:
    database_url = env('DATABASE_URL', '')
    if not database_url:
        raise RuntimeError('DATABASE_URL is required')
    db = Database(database_url)
    retries = int(env('DB_INIT_RETRIES', '20'))
    for attempt in range(1, retries + 1):
        try:
            await db.connect()
            break
        except Exception:
            if attempt == retries:
                raise
            await asyncio.sleep(3)
    try:
        await apply_sql_files(db)
        await ensure_runtime_schema(db)
        await ensure_card_identity_constraints(db)
        await seed_public_holidays(db, 2025)
        await seed_public_holidays(db, 2026)
        result = await ensure_super_admin(db)
        set_database_rls_context(legal_entity_id=None)
        await apply_phase_migrations(db)
        print(f"[init_db] super-admin employee_id={result['employee_id']} username={result['username']}")
        print(f"[init_db] legal_entity_id={result['legal_entity_id']}")
    finally:
        await db.close()


if __name__ == '__main__':
    asyncio.run(main())
