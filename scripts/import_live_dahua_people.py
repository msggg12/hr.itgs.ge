from __future__ import annotations

import asyncio
import re
import unicodedata
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterable
from zipfile import ZipFile

import asyncpg


DB_DSN = "postgresql://hrms:hrms@127.0.0.1:5432/hrms"
CSV_PATH = Path(r"C:\Users\User\Downloads\Person List2026-04-09_12_18_40.csv")
KEEP_EMPLOYEE_NUMBER = "ADM-0001"
KEEP_PERSONAL_NUMBER = "00000000000"
DEFAULT_TIMEZONE = "Asia/Tbilisi"
DEFAULT_CURRENCY = "GEL"
SYSTEM_ACTOR_NOTE = "Live Dahua import bootstrap"


@dataclass
class CsvEmployee:
    person_id: str
    full_name: str
    department_path: str
    phone: str | None
    email: str | None
    employment_date: date
    termination_date: date | None
    birthday: date | None

    @property
    def first_name(self) -> str:
        parts = split_name(self.full_name)
        return parts[0]

    @property
    def last_name(self) -> str:
        parts = split_name(self.full_name)
        return parts[1]


def split_name(full_name: str) -> tuple[str, str]:
    tokens = [token for token in re.split(r"\s+", full_name.strip()) if token]
    if not tokens:
        return "Unknown", "Employee"
    if len(tokens) == 1:
        return tokens[0], "-"
    return tokens[0], " ".join(tokens[1:])


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", ascii_only.upper()).strip("_")
    return cleaned or "GENERAL"


def parse_datetime_like(raw: str) -> date | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def parse_xlsx_rows(path: Path) -> list[list[str]]:
    ns = {
        "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
    }
    with ZipFile(path) as zf:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            shared_root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in shared_root.findall("a:si", ns):
                shared_strings.append("".join(node.text or "" for node in si.findall(".//a:t", ns)))

        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        relationships = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        first_sheet = workbook.find("a:sheets/a:sheet", ns)
        if first_sheet is None:
            raise RuntimeError("Workbook has no sheets")
        relation_id = first_sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
        sheet_target = None
        for rel in relationships.findall("pr:Relationship", ns):
            if rel.attrib.get("Id") == relation_id:
                sheet_target = rel.attrib["Target"]
                break
        if not sheet_target:
            raise RuntimeError("Could not resolve first worksheet")

        sheet = ET.fromstring(zf.read(f"xl/{sheet_target}"))
        rows: list[list[str]] = []
        for row in sheet.findall(".//a:sheetData/a:row", ns):
            values: list[str] = []
            for cell in row.findall("a:c", ns):
                cell_type = cell.attrib.get("t")
                value_node = cell.find("a:v", ns)
                if value_node is None:
                    inline_node = cell.find("a:is", ns)
                    text = "".join(t.text or "" for t in inline_node.findall(".//a:t", ns)) if inline_node is not None else ""
                else:
                    raw = value_node.text or ""
                    text = shared_strings[int(raw)] if cell_type == "s" else raw
                values.append(text)
            rows.append(values)
        return rows


def load_csv_employees(path: Path) -> list[CsvEmployee]:
    rows = parse_xlsx_rows(path)
    if not rows:
        raise RuntimeError("No rows found in workbook")
    headers = rows[0]
    index = {header: idx for idx, header in enumerate(headers)}
    required = ["* Person ID", "* Name", "Department", "Employment Date", "Termination Date", "Birthday", "Phone No.", "Email"]
    missing = [header for header in required if header not in index]
    if missing:
        raise RuntimeError(f"Missing required headers: {', '.join(missing)}")

    employees: list[CsvEmployee] = []
    for raw_row in rows[1:]:
        person_id = (raw_row[index["* Person ID"]] if index["* Person ID"] < len(raw_row) else "").strip()
        full_name = (raw_row[index["* Name"]] if index["* Name"] < len(raw_row) else "").strip()
        if not person_id or not full_name:
            continue
        department_path = (raw_row[index["Department"]] if index["Department"] < len(raw_row) else "").strip() or "Default Company"
        phone = (raw_row[index["Phone No."]] if index["Phone No."] < len(raw_row) else "").strip() or None
        email = (raw_row[index["Email"]] if index["Email"] < len(raw_row) else "").strip().lower() or None
        employment_date = parse_datetime_like(raw_row[index["Employment Date"]] if index["Employment Date"] < len(raw_row) else "")
        termination_date = parse_datetime_like(raw_row[index["Termination Date"]] if index["Termination Date"] < len(raw_row) else "")
        birthday = parse_datetime_like(raw_row[index["Birthday"]] if index["Birthday"] < len(raw_row) else "")
        employees.append(
            CsvEmployee(
                person_id=person_id,
                full_name=full_name,
                department_path=department_path,
                phone=phone,
                email=email,
                employment_date=employment_date or date.today(),
                termination_date=termination_date,
                birthday=birthday,
            )
        )
    return employees


async def ensure_department(
    conn: asyncpg.Connection,
    legal_entity_id: uuid.UUID,
    cache: dict[str, uuid.UUID],
    department_path: str,
) -> uuid.UUID:
    if department_path in cache:
        return cache[department_path]

    leaf = department_path.split("\\")[-1].strip() or "Default Company"
    candidates = [department_path, leaf]
    row = await conn.fetchrow(
        """
        select id
        from hrms.departments
        where legal_entity_id = $1
          and (
            upper(code::text) = any($2::text[])
            or upper(name_en) = any($2::text[])
            or upper(name_ka) = any($2::text[])
          )
        order by case when upper(code::text) = $3 then 0 else 1 end, created_at
        limit 1
        """,
        legal_entity_id,
        [candidate.upper() for candidate in candidates],
        leaf.upper(),
    )
    if row:
        cache[department_path] = row["id"]
        return row["id"]

    department_id = uuid.uuid4()
    code = slugify(leaf)
    suffix = 1
    while await conn.fetchval(
        "select 1 from hrms.departments where legal_entity_id = $1 and upper(code::text) = $2",
        legal_entity_id,
        code.upper(),
    ):
        suffix += 1
        code = f"{slugify(leaf)}_{suffix}"
    now = datetime.now(timezone.utc)
    await conn.execute(
        """
        insert into hrms.departments (
            id, legal_entity_id, parent_department_id, code, name_en, name_ka,
            cost_center_code, is_active, created_at, updated_at, manager_employee_id
        )
        values ($1, $2, null, $3, $4, $5, null, true, $6, $6, null)
        """,
        department_id,
        legal_entity_id,
        code,
        leaf,
        leaf,
        now,
    )
    cache[department_path] = department_id
    return department_id


async def wipe_existing_employee_data(conn: asyncpg.Connection, keep_employee_id: uuid.UUID) -> dict[str, int]:
    stats: dict[str, int] = {}
    stats["asset_assignments_deleted"] = int(
        (await conn.execute("delete from hrms.asset_assignments where employee_id <> $1", keep_employee_id)).split()[-1]
    )
    for table in (
        "attendance_manual_adjustments",
        "attendance_review_flags",
        "attendance_work_sessions",
        "raw_attendance_logs",
        "web_punch_events",
        "monthly_timesheets",
        "payroll_payment_records",
        "device_command_queue",
        "device_push_batches",
        "employee_device_identities",
        "biometric_templates",
        "employee_status_calendar",
        "leave_request_approvals",
        "leave_request_files",
        "leave_requests",
        "leave_balances",
        "offboarding_clearances",
        "employee_separations",
        "final_payroll_holds",
        "employee_message_dispatches",
        "employee_chat_accounts",
        "employee_google_calendar_connections",
        "employee_dashboard_preferences",
        "employee_file_uploads",
        "auth_invites",
        "password_reset_tokens",
        "employee_access_roles",
        "auth_identities",
        "employee_compensation",
        "assigned_shifts",
        "department_schedule_managers",
        "onboarding_course_assignments",
        "burnout_risk_alerts",
        "expense_claims",
        "okr_objectives",
    ):
        if table == "device_push_batches":
            command = "delete from hrms.device_push_batches"
        elif table == "device_command_queue":
            command = "delete from hrms.device_command_queue"
        elif table in {"leave_request_approvals", "leave_request_files"}:
            command = f"delete from hrms.{table} where leave_request_id in (select id from hrms.leave_requests where employee_id <> $1)"
        elif table == "employee_message_dispatches":
            command = """
                delete from hrms.employee_message_dispatches
                where sender_employee_id <> $1 or target_employee_id <> $1
            """
        elif table == "auth_invites":
            command = "delete from hrms.auth_invites where employee_id <> $1"
        elif table == "password_reset_tokens":
            command = "delete from hrms.password_reset_tokens where employee_id <> $1"
        elif table == "department_schedule_managers":
            command = "delete from hrms.department_schedule_managers where employee_id <> $1"
        elif table == "expense_claims":
            command = "delete from hrms.expense_claims where employee_id <> $1"
        elif table == "okr_objectives":
            command = "delete from hrms.okr_objectives where owner_employee_id <> $1"
        else:
            command = f"delete from hrms.{table} where employee_id <> $1"
        if "$1" in command:
            result = await conn.execute(command, keep_employee_id)
        else:
            result = await conn.execute(command)
        stats[f"{table}_deleted"] = int(result.split()[-1])

    stats["employees_deleted"] = int(
        (
            await conn.execute(
                """
                delete from hrms.employees
                where id <> $1
                """
                ,
                keep_employee_id,
            )
        ).split()[-1]
    )
    return stats


async def import_employees(conn: asyncpg.Connection, employees: Iterable[CsvEmployee]) -> dict[str, int]:
    superadmin = await conn.fetchrow(
        """
        select id, legal_entity_id
        from hrms.employees
        where employee_number = $1 and personal_number = $2 and deleted_at is null
        limit 1
        """,
        KEEP_EMPLOYEE_NUMBER,
        KEEP_PERSONAL_NUMBER,
    )
    if not superadmin:
        raise RuntimeError("Could not find the preserved superadmin employee")

    ess_role_id = await conn.fetchval(
        """
        select id
        from hrms.access_roles
        where upper(code::text) = 'ESS_EMPLOYEE'
        limit 1
        """
    )
    if not ess_role_id:
        raise RuntimeError("ESS_EMPLOYEE role was not found")

    pay_policy_id = await conn.fetchval(
        """
        select id
        from hrms.pay_policies
        where legal_entity_id = $1
        order by created_at
        limit 1
        """,
        superadmin["legal_entity_id"],
    )
    if not pay_policy_id:
        raise RuntimeError("No pay policy found for the target legal entity")

    department_cache: dict[str, uuid.UUID] = {}
    inserted = 0
    role_links = 0
    compensation_rows = 0
    now = datetime.now(timezone.utc)
    for employee in employees:
        department_id = await ensure_department(conn, superadmin["legal_entity_id"], department_cache, employee.department_path)
        employee_id = uuid.uuid4()
        await conn.execute(
            """
            insert into hrms.employees (
                id, legal_entity_id, employee_number, personal_number,
                first_name, last_name, first_name_ka, last_name_ka, birth_date,
                email, mobile_phone, department_id, job_role_id, manager_employee_id,
                hire_date, termination_date, employment_status, timezone,
                default_device_user_id, home_address, emergency_contact_name,
                emergency_contact_phone, created_at, updated_at, line_manager_id, deleted_at
            )
            values (
                $1, $2, $3, $3,
                $4, $5, $4, $5, $6,
                $7, $8, $9, null, null,
                $10, $11, 'active', $12,
                $3, null, null,
                null, $13, $13, null, null
            )
            """,
            employee_id,
            superadmin["legal_entity_id"],
            employee.person_id,
            employee.first_name,
            employee.last_name,
            employee.birthday,
            employee.email,
            employee.phone,
            department_id,
            employee.employment_date,
            employee.termination_date,
            DEFAULT_TIMEZONE,
            now,
        )
        inserted += 1
        await conn.execute(
            """
            insert into hrms.employee_compensation (
                id, employee_id, policy_id, effective_from, effective_to, base_salary,
                currency_code, hourly_rate_override, is_pension_participant, notes, created_at, updated_at
            )
            values ($1, $2, $3, $4, null, $5, $6, null, true, $7, $8, $8)
            """,
            uuid.uuid4(),
            employee_id,
            pay_policy_id,
            employee.employment_date,
            Decimal("0.00"),
            DEFAULT_CURRENCY,
            SYSTEM_ACTOR_NOTE,
            now,
        )
        compensation_rows += 1
        await conn.execute(
            """
            insert into hrms.employee_access_roles (
                employee_id, access_role_id, assigned_at, assigned_by_employee_id
            )
            values ($1, $2, $3, $4)
            """,
            employee_id,
            ess_role_id,
            now,
            superadmin["id"],
        )
        role_links += 1

    return {
        "employees_inserted": inserted,
        "compensation_rows": compensation_rows,
        "role_links": role_links,
        "departments_touched": len(department_cache),
    }


async def main() -> None:
    if not CSV_PATH.exists():
        raise FileNotFoundError(CSV_PATH)

    employees = load_csv_employees(CSV_PATH)
    if not employees:
        raise RuntimeError("No employees loaded from source file")

    conn = await asyncpg.connect(DB_DSN)
    try:
        keep_employee = await conn.fetchrow(
            """
            select id
            from hrms.employees
            where employee_number = $1 and personal_number = $2 and deleted_at is null
            limit 1
            """,
            KEEP_EMPLOYEE_NUMBER,
            KEEP_PERSONAL_NUMBER,
        )
        if not keep_employee:
            raise RuntimeError("Preserved superadmin record not found")

        async with conn.transaction():
            cleanup_stats = await wipe_existing_employee_data(conn, keep_employee["id"])
            import_stats = await import_employees(conn, employees)

        print("CLEANUP")
        for key, value in cleanup_stats.items():
            print(f"{key}={value}")
        print("IMPORT")
        for key, value in import_stats.items():
            print(f"{key}={value}")
        print(f"source_rows={len(employees)}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
