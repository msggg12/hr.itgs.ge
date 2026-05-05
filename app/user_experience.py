from __future__ import annotations

import asyncio
import csv
from collections import defaultdict
import io
import json
import zipfile
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from .api_support import get_db_from_request, get_request_tenant_legal_entity_id, require_actor
from .config import settings
from .google_calendar import get_upcoming_google_schedule
from .labor_engine import _fetch_resolved_shifts
from .mattermost_integration import _fetch_config as _fetch_mattermost_config
from .rbac import (
    can_edit_employee_profiles,
    can_edit_shift_schedule,
    can_export_employees,
    can_import_employees,
    can_view_employee_directory,
    ensure_can_export_payroll,
    ensure_can_view_attendance,
    employee_directory_scope,
    ensure_permission,
)
from .tenant import DEFAULT_FEATURE_FLAGS

UX_ROUTER = APIRouter(prefix='/ux', tags=['ux'])
GEORGIA_TZ = ZoneInfo('Asia/Tbilisi')
GEORGIAN_WEEKDAY_LABELS = {
    1: 'ორშ',
    2: 'სამ',
    3: 'ოთხ',
    4: 'ხუთ',
    5: 'პარ',
    6: 'შაბ',
    7: 'კვი',
}
GEORGIAN_MONTH_NAMES = {
    1: 'იანვარი',
    2: 'თებერვალი',
    3: 'მარტი',
    4: 'აპრილი',
    5: 'მაისი',
    6: 'ივნისი',
    7: 'ივლისი',
    8: 'აგვისტო',
    9: 'სექტემბერი',
    10: 'ოქტომბერი',
    11: 'ნოემბერი',
    12: 'დეკემბერი',
}
ATTENDANCE_WEEKDAY_LABELS = {
    1: 'ორშ',
    2: 'სამ',
    3: 'ოთხ',
    4: 'ხუთ',
    5: 'პარ',
    6: 'შაბ',
    7: 'კვი',
}
ATTENDANCE_MONTH_NAMES = {
    1: 'იანვარი',
    2: 'თებერვალი',
    3: 'მარტი',
    4: 'აპრილი',
    5: 'მაისი',
    6: 'ივნისი',
    7: 'ივლისი',
    8: 'აგვისტო',
    9: 'სექტემბერი',
    10: 'ოქტომბერი',
    11: 'ნოემბერი',
    12: 'დეკემბერი',
}
ATTENDANCE_GRACE_MINUTES = 10
ATTENDANCE_SICK_CODES = {'SICK', 'SICK_LEAVE', 'BULLETIN', 'MEDICAL', 'MEDICAL_BULLETIN'}


class WidgetPlacement(BaseModel):
    widget_code: str
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(ge=1)
    h: int = Field(ge=1)


class DashboardPreferenceUpdate(BaseModel):
    theme_preference: Literal['system', 'light', 'dark'] = 'system'
    pinned_widgets: list[str] = Field(default_factory=list)
    layout: list[WidgetPlacement] = Field(default_factory=list)
    mobile_layout: list[WidgetPlacement] = Field(default_factory=list)


class ShiftAssignmentUpsert(BaseModel):
    employee_id: UUID
    shift_date: date
    shift_pattern_id: UUID | None = None
    start_time: str | None = None
    end_time: str | None = None


def _georgia_today() -> date:
    return datetime.now(tz=GEORGIA_TZ).date()


def _georgia_range_start(target_day: date) -> date:
    return target_day - timedelta(days=target_day.weekday())


def _build_series(days: list[date], values: dict[date, int]) -> list[int]:
    return [int(values.get(day, 0)) for day in days]


def _summarize_web_punch_rows(rows: list[dict[str, object]]) -> dict[str, object]:
    open_segment_started_at: datetime | None = None
    completed_seconds = 0
    for row in rows:
        if row['direction'] == 'in':
            open_segment_started_at = row['punch_ts']
        elif row['direction'] == 'out' and open_segment_started_at is not None:
            completed_seconds += max(0, int((row['punch_ts'] - open_segment_started_at).total_seconds()))
            open_segment_started_at = None

    current_segment_seconds = 0
    if open_segment_started_at is not None:
        current_segment_seconds = max(0, int((datetime.now(tz=GEORGIA_TZ) - open_segment_started_at.astimezone(GEORGIA_TZ)).total_seconds()))

    return {
        'is_checked_in': open_segment_started_at is not None,
        'current_direction': 'out' if open_segment_started_at is not None else 'in',
        'current_segment_started_at': open_segment_started_at.isoformat() if open_segment_started_at is not None else None,
        'completed_work_seconds_today': completed_seconds,
        'current_segment_seconds': current_segment_seconds,
        'worked_seconds_today': completed_seconds + current_segment_seconds,
        'today_punch_count': len(rows),
    }


def _completed_months(start_date: date, target_date: date) -> int:
    if target_date < start_date:
        return 0
    months = (target_date.year - start_date.year) * 12 + (target_date.month - start_date.month)
    if target_date.day < start_date.day:
        months -= 1
    return max(months, 0)


async def _leave_policy_settings(db, legal_entity_id: UUID) -> dict[str, object]:
    row = await db.fetchrow(
        """
        SELECT paid_leave_allowance_days,
               unpaid_leave_allowance_days,
               eligibility_months,
               enable_birthday_off,
               enable_day_off,
               global_leave_approver_employee_id
          FROM entity_leave_policy_settings
         WHERE legal_entity_id = $1
        """,
        legal_entity_id,
    )
    if row is None:
        return {
            'paid_leave_allowance_days': 24,
            'unpaid_leave_allowance_days': 15,
            'eligibility_months': 11,
            'enable_birthday_off': False,
            'enable_day_off': False,
            'global_leave_approver_employee_id': None,
        }
    return dict(row)


def _leave_type_visible_for_policy(code: str | None, policy: dict[str, object]) -> bool:
    normalized = (code or '').upper()
    if normalized in {'BIRTHDAY_OFF', 'BIRTHDAY', 'BIRTHDAY_LEAVE'}:
        return bool(policy.get('enable_birthday_off'))
    if normalized in {'DAY_OFF', 'DAYOFF', 'PERSONAL_DAY'}:
        return bool(policy.get('enable_day_off'))
    return True


def _to_float(value: Decimal | int | float | None) -> float:
    if value is None:
        return 0.0
    return float(value)


def _segment_end_time(start_time_text: str, planned_minutes: int) -> str:
    start_dt = datetime.strptime(start_time_text, '%H:%M')
    end_dt = start_dt + timedelta(minutes=planned_minutes)
    return end_dt.strftime('%H:%M')


def _month_bounds(value: date) -> tuple[date, date]:
    month_start = value.replace(day=1)
    if month_start.month == 12:
        next_month = date(month_start.year + 1, 1, 1)
    else:
        next_month = date(month_start.year, month_start.month + 1, 1)
    return month_start, next_month - timedelta(days=1)


def _calendar_title(value: date) -> str:
    return f"{ATTENDANCE_MONTH_NAMES[value.month]} {value.year}"


def _week_bucket_key(value: date) -> str:
    week_start = value - timedelta(days=value.weekday())
    return week_start.isoformat()


def _attendance_calendar_title(value: date) -> str:
    return f"{ATTENDANCE_MONTH_NAMES[value.month]} {value.year}"


def _actor_can_open_attendance_hub(actor) -> bool:
    return (
        actor.has('attendance.read_self')
        or actor.has('attendance.read_department')
        or actor.has('attendance.read_all')
        or actor.has('attendance.review')
        or actor.has('employee.manage')
    )


def _actor_can_access_company_home_dashboard(actor) -> bool:
    return (
        actor.has('attendance.read_department')
        or actor.has('attendance.read_all')
        or actor.has('attendance.review')
        or actor.has('employee.manage')
        or bool({'ADMIN', 'TENANT_ADMIN'} & actor.role_codes)
    )


def _normalize_dashboard_widget_visibility(value: object | None) -> dict[str, bool]:
    raw_value = value
    if isinstance(raw_value, str):
        try:
            raw_value = json.loads(raw_value)
        except json.JSONDecodeError:
            raw_value = {}
    if not isinstance(raw_value, dict):
        raw_value = {}
    return {
        'summary_cards': bool(raw_value.get('summary_cards', True)),
        'analytics': bool(raw_value.get('analytics', True)),
        'live_feed': bool(raw_value.get('live_feed', True)),
        'action_center': bool(raw_value.get('action_center', True)),
        'upcoming_schedule': bool(raw_value.get('upcoming_schedule', True)),
        'celebrations': bool(raw_value.get('celebrations', True)),
    }


async def _entity_ui_policy_flags(db, legal_entity_id: UUID) -> dict[str, object]:
    row = await db.fetchrow(
        """
        SELECT company_dashboard_enabled,
               payroll_dashboard_enabled,
               dashboard_widget_visibility
          FROM entity_system_config
         WHERE legal_entity_id = $1
        """,
        legal_entity_id,
    )
    raw_widget_visibility = row['dashboard_widget_visibility'] if row else None
    if isinstance(raw_widget_visibility, str):
        try:
            raw_widget_visibility = json.loads(raw_widget_visibility)
        except json.JSONDecodeError:
            raw_widget_visibility = {}
    return {
        'company_dashboard_enabled': bool(row['company_dashboard_enabled']) if row and row['company_dashboard_enabled'] is not None else True,
        'payroll_dashboard_enabled': bool(row['payroll_dashboard_enabled']) if row and row['payroll_dashboard_enabled'] is not None else True,
        'dashboard_widget_visibility': _normalize_dashboard_widget_visibility(raw_widget_visibility),
    }


async def _attendance_accessible_departments(db, actor) -> list[dict[str, object]]:
    if actor.has('attendance.read_all') or actor.has('employee.manage') or bool({'ADMIN', 'TENANT_ADMIN'} & actor.role_codes):
        rows = await db.fetch(
            """
            SELECT id, coalesce(name_ka, name_en) AS name
              FROM departments
             WHERE legal_entity_id = $1
               AND is_active = true
             ORDER BY coalesce(name_ka, name_en)
            """,
            actor.legal_entity_id,
        )
    else:
        accessible_ids = set(actor.managed_department_ids)
        if actor.department_id is not None:
            accessible_ids.add(actor.department_id)
        if not accessible_ids:
            return []
        rows = await db.fetch(
            """
            SELECT id, coalesce(name_ka, name_en) AS name
              FROM departments
             WHERE id = ANY($1::uuid[])
               AND is_active = true
             ORDER BY coalesce(name_ka, name_en)
            """,
            list(accessible_ids),
        )
    return [{'id': row['id'], 'name': row['name']} for row in rows]


def _resolve_attendance_department(
    actor,
    accessible_departments: list[dict[str, object]],
    requested_department_id: UUID | None,
) -> UUID | None:
    if requested_department_id is not None:
        for department in accessible_departments:
            if department['id'] == requested_department_id:
                return requested_department_id
    if actor.department_id is not None:
        for department in accessible_departments:
            if department['id'] == actor.department_id:
                return actor.department_id
    if accessible_departments:
        return accessible_departments[0]['id']
    return actor.department_id


async def _attendance_scope_employee_rows(db, actor, department_id: UUID | None) -> list[dict[str, object]]:
    if department_id is not None:
        rows = await db.fetch(
            """
            SELECT e.id,
                   e.employee_number,
                   e.first_name,
                   e.last_name,
                   e.department_id,
                   coalesce(d.name_ka, d.name_en) AS department_name,
                   coalesce(jr.title_ka, jr.title_en) AS job_title
              FROM employees e
              LEFT JOIN departments d ON d.id = e.department_id
              LEFT JOIN job_roles jr ON jr.id = e.job_role_id
             WHERE e.legal_entity_id = $1
               AND e.deleted_at IS NULL
               AND e.employment_status = 'active'
               AND e.department_id = $2
             ORDER BY e.first_name, e.last_name
            """,
            actor.legal_entity_id,
            department_id,
        )
    else:
        rows = await db.fetch(
            """
            SELECT e.id,
                   e.employee_number,
                   e.first_name,
                   e.last_name,
                   e.department_id,
                   coalesce(d.name_ka, d.name_en) AS department_name,
                   coalesce(jr.title_ka, jr.title_en) AS job_title
              FROM employees e
              LEFT JOIN departments d ON d.id = e.department_id
              LEFT JOIN job_roles jr ON jr.id = e.job_role_id
             WHERE e.id = $1
               AND e.deleted_at IS NULL
               AND e.employment_status = 'active'
            """,
            actor.employee_id,
        )
    return [dict(row) for row in rows]


async def _attendance_event_map(
    db,
    employee_ids: list[UUID],
    start_date: date,
    end_date: date,
) -> dict[tuple[UUID, date], list[dict[str, object]]]:
    if not employee_ids:
        return {}
    rows = await db.fetch(
        """
        SELECT employee_id, work_date, event_ts, direction, source_type
          FROM (
                SELECT ral.employee_id,
                       (ral.event_ts AT TIME ZONE 'Asia/Tbilisi')::date AS work_date,
                       ral.event_ts,
                       ral.direction::text AS direction,
                       'device'::text AS source_type
                  FROM raw_attendance_logs ral
                 WHERE ral.employee_id = ANY($1::uuid[])
                   AND (ral.event_ts AT TIME ZONE 'Asia/Tbilisi')::date BETWEEN $2 AND $3
                UNION ALL
                SELECT wpe.employee_id,
                       (wpe.punch_ts AT TIME ZONE 'Asia/Tbilisi')::date AS work_date,
                       wpe.punch_ts AS event_ts,
                       wpe.direction::text AS direction,
                       'web'::text AS source_type
                  FROM web_punch_events wpe
                 WHERE wpe.employee_id = ANY($1::uuid[])
                   AND wpe.is_valid = true
                   AND (wpe.punch_ts AT TIME ZONE 'Asia/Tbilisi')::date BETWEEN $2 AND $3
          ) attendance_events
         ORDER BY employee_id, work_date, event_ts
        """,
        employee_ids,
        start_date,
        end_date,
    )
    event_map: dict[tuple[UUID, date], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        event_map[(row['employee_id'], row['work_date'])].append(
            {
                'event_ts': row['event_ts'],
                'direction': row['direction'],
                'source_type': row['source_type'],
            }
        )
    return dict(event_map)


async def _attendance_session_map(
    db,
    employee_ids: list[UUID],
    start_date: date,
    end_date: date,
) -> dict[tuple[UUID, date], dict[str, object]]:
    if not employee_ids:
        return {}
    rows = await db.fetch(
        """
        SELECT employee_id,
               work_date,
               min(check_in_ts) AS check_in_ts,
               max(check_out_ts) AS check_out_ts,
               coalesce(sum(total_minutes), 0) AS total_minutes,
               bool_or(check_out_ts IS NULL) AS has_open_session,
               bool_or(review_status::text IN ('corrected', 'approved')) AS has_reviewed_session,
               max(incomplete_reason) FILTER (WHERE incomplete_reason IS NOT NULL) AS incomplete_reason
          FROM attendance_work_sessions
         WHERE employee_id = ANY($1::uuid[])
           AND work_date BETWEEN $2 AND $3
         GROUP BY employee_id, work_date
        """,
        employee_ids,
        start_date,
        end_date,
    )
    return {
        (row['employee_id'], row['work_date']): {
            'check_in_ts': row['check_in_ts'],
            'check_out_ts': row['check_out_ts'],
            'total_minutes': int(row['total_minutes'] or 0),
            'has_open_session': bool(row['has_open_session']),
            'has_reviewed_session': bool(row['has_reviewed_session']),
            'incomplete_reason': row['incomplete_reason'],
        }
        for row in rows
    }


async def _attendance_leave_map(
    db,
    employee_ids: list[UUID],
    start_date: date,
    end_date: date,
) -> dict[tuple[UUID, date], dict[str, object]]:
    if not employee_ids:
        return {}
    rows = await db.fetch(
        """
        SELECT lr.employee_id,
               lr.start_date,
               lr.end_date,
               lr.status::text AS status,
               upper(lt.code::text) AS leave_code,
               coalesce(lt.name_ka, lt.name_en) AS leave_name
          FROM leave_requests lr
          JOIN leave_types lt ON lt.id = lr.leave_type_id
         WHERE lr.employee_id = ANY($1::uuid[])
           AND lr.end_date >= $2
           AND lr.start_date <= $3
           AND lr.status::text IN ('submitted', 'manager_pending', 'hr_pending', 'approved')
         ORDER BY CASE WHEN lr.status = 'approved' THEN 0 ELSE 1 END, lr.created_at DESC
        """,
        employee_ids,
        start_date,
        end_date,
    )
    leave_map: dict[tuple[UUID, date], dict[str, object]] = {}
    for row in rows:
        current = max(row['start_date'], start_date)
        final = min(row['end_date'], end_date)
        while current <= final:
            key = (row['employee_id'], current)
            if key not in leave_map:
                leave_map[key] = {
                    'status': 'sick' if row['leave_code'] in ATTENDANCE_SICK_CODES else 'leave',
                    'leave_name': row['leave_name'],
                    'leave_code': row['leave_code'],
                    'approval_status': row['status'],
                }
            current += timedelta(days=1)
    return leave_map


def _attendance_event_bounds(events: list[dict[str, object]]) -> dict[str, object]:
    if not events:
        return {
            'first_event_ts': None,
            'last_event_ts': None,
            'check_in_ts': None,
            'check_out_ts': None,
            'has_activity': False,
        }
    first_event = events[0]['event_ts']
    last_event = events[-1]['event_ts']
    check_in_ts = next((item['event_ts'] for item in events if item['direction'] == 'in'), first_event)
    check_out_ts = next((item['event_ts'] for item in reversed(events) if item['direction'] == 'out'), None)
    return {
        'first_event_ts': first_event,
        'last_event_ts': last_event,
        'check_in_ts': check_in_ts,
        'check_out_ts': check_out_ts,
        'has_activity': True,
    }


def _attendance_clock_label(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(GEORGIA_TZ).strftime('%H:%M')


def _attendance_shift_label(shift) -> str | None:
    if shift is None:
        return None
    return f"{shift.start_local.strftime('%H:%M')}-{shift.end_local.strftime('%H:%M')}"


def _attendance_day_metrics(
    shift,
    session: dict[str, object] | None,
    events: list[dict[str, object]],
) -> dict[str, object]:
    ordered_events = sorted(events, key=lambda item: item['event_ts'])
    first_event_ts = ordered_events[0]['event_ts'] if ordered_events else None
    last_event_ts = ordered_events[-1]['event_ts'] if ordered_events else None

    reviewed_window_available = bool(
        session
        and session.get('has_reviewed_session')
        and session.get('check_in_ts') is not None
        and session.get('check_out_ts') is not None
    )

    if reviewed_window_available:
        check_in_ts = session['check_in_ts']
        check_out_ts = session['check_out_ts']
    elif first_event_ts is not None:
        check_in_ts = first_event_ts
        check_out_ts = last_event_ts if last_event_ts is not None and last_event_ts > first_event_ts else None
    else:
        check_in_ts = session['check_in_ts'] if session and session.get('check_in_ts') else None
        check_out_ts = session['check_out_ts'] if session and session.get('check_out_ts') else None

    has_activity = check_in_ts is not None or bool(ordered_events) or bool(session)
    missing_checkout = bool(
        has_activity
        and check_in_ts is not None
        and (
            check_out_ts is None
            or (session and session.get('has_open_session'))
            or (session and session.get('incomplete_reason') == 'missing_check_out')
            or (ordered_events and len(ordered_events) == 1)
        )
    )

    total_minutes = 0
    if check_in_ts is not None and check_out_ts is not None and check_out_ts > check_in_ts and not missing_checkout:
        total_minutes = int((check_out_ts - check_in_ts).total_seconds() // 60)

    late_minutes = 0
    overtime_minutes = 0
    if shift is not None and check_in_ts is not None:
        check_in_local = check_in_ts.astimezone(GEORGIA_TZ)
        late_threshold = shift.start_local + timedelta(minutes=ATTENDANCE_GRACE_MINUTES)
        if check_in_local > late_threshold:
            late_minutes = int((check_in_local - late_threshold).total_seconds() // 60)
    if shift is not None and check_out_ts is not None and not missing_checkout:
        check_out_local = check_out_ts.astimezone(GEORGIA_TZ)
        overtime_threshold = shift.end_local + timedelta(minutes=ATTENDANCE_GRACE_MINUTES)
        if check_out_local > overtime_threshold:
            overtime_minutes = int((check_out_local - overtime_threshold).total_seconds() // 60)

    exception_code = None
    exception_label = None
    if missing_checkout:
        exception_code = 'missing_checkout'
        exception_label = 'Checkout time calculation failed / Missing Checkout'
    elif session and session.get('incomplete_reason') == 'orphan_check_out':
        exception_code = 'orphan_checkout'
        exception_label = 'Checkout punch exists without a matching check-in'

    return {
        'has_activity': bool(has_activity),
        'check_in_ts': check_in_ts.isoformat() if check_in_ts else None,
        'check_out_ts': check_out_ts.isoformat() if check_out_ts else None,
        'check_in_label': _attendance_clock_label(check_in_ts),
        'check_out_label': _attendance_clock_label(check_out_ts),
        'total_minutes': total_minutes,
        'late_minutes': late_minutes,
        'overtime_minutes': overtime_minutes,
        'exception_code': exception_code,
        'exception_label': exception_label,
        'punch_count': len(ordered_events),
    }


def _attendance_summary_seed(employee_id: UUID | str | None = None) -> dict[str, object]:
    return {
        'employee_id': str(employee_id) if employee_id else '',
        'employee_name': '',
        'total_minutes': 0,
        'late_days': 0,
        'overtime_minutes': 0,
        'present_days': 0,
        'absent_days': 0,
        'leave_days': 0,
        'sick_days': 0,
        'exception_days': 0,
    }


def _build_minimal_xlsx(sheet_name: str, headers: list[str], rows: list[list[str]]) -> bytes:
    def _escape_xml(value: str) -> str:
        return (
            value.replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
            .replace("'", '&apos;')
        )

    def _cell_ref(col_idx: int, row_idx: int) -> str:
        result = ''
        value = col_idx
        while value >= 0:
            result = chr(value % 26 + 65) + result
            value = value // 26 - 1
        return f'{result}{row_idx}'

    all_rows = [headers, *rows]
    worksheet_rows: list[str] = []
    for row_idx, row in enumerate(all_rows, start=1):
        cells = []
        for col_idx, value in enumerate(row):
            escaped = _escape_xml(str(value))
            cells.append(
                f'<c r="{_cell_ref(col_idx, row_idx)}" t="inlineStr"><is><t>{escaped}</t></is></c>'
            )
        worksheet_rows.append(f'<row r="{row_idx}">{"".join(cells)}</row>')
    worksheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(worksheet_rows)}</sheetData>'
        '</worksheet>'
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{_escape_xml(sheet_name[:31] or "Sheet1")}" sheetId="1" r:id="rId1"/></sheets>'
        '</workbook>'
    )
    workbook_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
        '</Relationships>'
    )
    root_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        '</Relationships>'
    )
    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '</Types>'
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
        '<borders count="1"><border/></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        '</styleSheet>'
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', content_types_xml)
        archive.writestr('_rels/.rels', root_rels_xml)
        archive.writestr('xl/workbook.xml', workbook_xml)
        archive.writestr('xl/_rels/workbook.xml.rels', workbook_rels_xml)
        archive.writestr('xl/worksheets/sheet1.xml', worksheet_xml)
        archive.writestr('xl/styles.xml', styles_xml)
    return buffer.getvalue()


def _attendance_export_response(
    *,
    sheet_name: str,
    file_stem: str,
    headers: list[str],
    rows: list[list[str]],
    export_format: str,
) -> Response:
    safe_file_stem = ''.join(ch if ch.isascii() and (ch.isalnum() or ch in {'_', '-'}) else '_' for ch in file_stem).strip('_') or 'attendance_export'
    if export_format.lower() == 'xlsx':
        workbook = _build_minimal_xlsx(sheet_name, headers, rows)
        response = Response(
            content=workbook,
            media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response.headers['Content-Disposition'] = f'attachment; filename={safe_file_stem}.xlsx'
        return response

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    writer.writerows(rows)
    response = Response(content=buffer.getvalue(), media_type='text/csv')
    response.headers['Content-Disposition'] = f'attachment; filename={safe_file_stem}.csv'
    return response


def _normalize_attendance_range(start_date: date | None, end_date: date | None) -> tuple[date, date]:
    today = _georgia_today()
    resolved_end = end_date or today
    resolved_start = start_date or resolved_end.replace(day=1)
    if resolved_end < resolved_start:
        raise HTTPException(status_code=400, detail='end_date must be on or after start_date')
    return resolved_start, resolved_end


def _summarize_attendance_for_employee(
    *,
    employee: dict[str, object],
    days: list[dict[str, object]],
    shifts_for_employee: dict[date, object],
    event_map: dict[tuple[UUID, date], list[dict[str, object]]],
    session_map: dict[tuple[UUID, date], dict[str, object]],
    leave_map: dict[tuple[UUID, date], dict[str, object]],
    today: date,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    employee_id = employee['id']
    day_statuses: list[dict[str, object]] = []
    report = {
        **_attendance_summary_seed(employee_id),
        'employee_name': f"{employee['first_name']} {employee['last_name']}".strip(),
        'employee_number': employee['employee_number'],
        'job_title': employee['job_title'],
        'department_name': employee['department_name'],
    }

    for day in days:
        current_day = date.fromisoformat(day['date'])
        shift = shifts_for_employee.get(current_day)
        leave_entry = leave_map.get((employee_id, current_day))
        metrics = _attendance_day_metrics(
            shift,
            session_map.get((employee_id, current_day)),
            event_map.get((employee_id, current_day), []),
        )
        shift_label = _attendance_shift_label(shift)

        if leave_entry is not None:
            status = leave_entry['status']
            icon = '🚑' if status == 'sick' else '🏖️'
            label = leave_entry['leave_name']
        elif metrics['has_activity']:
            status = 'present'
            icon = '✅'
            label = metrics['exception_label'] or metrics['check_in_label'] or shift_label
        elif current_day <= today:
            status = 'absent'
            icon = '❌'
            label = shift_label
        else:
            status = 'scheduled' if shift is not None else 'upcoming'
            icon = ''
            label = shift_label

        if status == 'present':
            report['present_days'] += 1
        elif status == 'absent':
            report['absent_days'] += 1
        elif status == 'leave':
            report['leave_days'] += 1
        elif status == 'sick':
            report['sick_days'] += 1

        if metrics['late_minutes'] > 0:
            report['late_days'] += 1
        if metrics['exception_code']:
            report['exception_days'] += 1

        report['total_minutes'] += int(metrics['total_minutes'])
        report['overtime_minutes'] += int(metrics['overtime_minutes'])

        day_statuses.append(
            {
                'date': day['date'],
                'status': status,
                'icon': icon,
                'label': label,
                'shift_label': shift_label,
                'check_in_ts': metrics['check_in_ts'],
                'check_out_ts': metrics['check_out_ts'],
                'check_in_label': metrics['check_in_label'],
                'check_out_label': metrics['check_out_label'],
                'total_minutes': metrics['total_minutes'],
                'late_minutes': metrics['late_minutes'],
                'overtime_minutes': metrics['overtime_minutes'],
                'exception_code': metrics['exception_code'],
                'exception_label': metrics['exception_label'],
                'punch_count': metrics['punch_count'],
            }
        )

    return day_statuses, report


async def _attendance_dataset(
    db,
    actor,
    *,
    start_date: date,
    end_date: date,
    department_id: UUID | None = None,
    employee_rows_override: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    today = _georgia_today()
    accessible_departments = await _attendance_accessible_departments(db, actor)
    selected_department_id = _resolve_attendance_department(actor, accessible_departments, department_id)
    selected_department_name = next(
        (department['name'] for department in accessible_departments if department['id'] == selected_department_id),
        None,
    )
    can_manage_selected = selected_department_id is not None and can_edit_shift_schedule(actor, selected_department_id)
    is_admin_attendance = bool({'ADMIN', 'TENANT_ADMIN'} & actor.role_codes) or actor.has('attendance.read_all') or actor.has('employee.manage')
    mode = 'admin' if is_admin_attendance else ('manager' if can_manage_selected else 'employee')
    scoped_department_id = selected_department_id if (can_manage_selected or is_admin_attendance) else None
    employee_rows = employee_rows_override or await _attendance_scope_employee_rows(db, actor, scoped_department_id)
    employee_ids = [row['id'] for row in employee_rows]

    event_map, session_map, leave_map = await asyncio.gather(
        _attendance_event_map(db, employee_ids, start_date, end_date),
        _attendance_session_map(db, employee_ids, start_date, end_date),
        _attendance_leave_map(db, employee_ids, start_date, end_date),
    )
    shift_map: dict[UUID, dict[date, object]] = {}
    for row in employee_rows:
        shift_map[row['id']] = await _fetch_resolved_shifts(db, row['id'], start_date, end_date)

    days = []
    for offset in range((end_date - start_date).days + 1):
        current_day = start_date + timedelta(days=offset)
        days.append(
            {
                'date': current_day.isoformat(),
                'label': ATTENDANCE_WEEKDAY_LABELS[current_day.isoweekday()],
                'day_index': current_day.isoweekday(),
            }
        )

    team_rows: list[dict[str, object]] = []
    reports: list[dict[str, object]] = []
    personal_days: list[dict[str, object]] = []
    personal_summary = _attendance_summary_seed(actor.employee_id)

    for employee in employee_rows:
        day_statuses, report = _summarize_attendance_for_employee(
            employee=employee,
            days=days,
            shifts_for_employee=shift_map.get(employee['id'], {}),
            event_map=event_map,
            session_map=session_map,
            leave_map=leave_map,
            today=today,
        )

        team_rows.append(
            {
                'employee_id': str(employee['id']),
                'employee_number': employee['employee_number'],
                'employee_name': f"{employee['first_name']} {employee['last_name']}".strip(),
                'first_name': employee['first_name'],
                'last_name': employee['last_name'],
                'job_title': employee['job_title'],
                'department_name': employee['department_name'],
                'day_statuses': day_statuses,
            }
        )
        reports.append(report)

        if employee['id'] == actor.employee_id:
            personal_days = day_statuses
            personal_summary = report

    reports.sort(key=lambda item: item['employee_name'])
    return {
        'mode': mode,
        'grace_period_minutes': ATTENDANCE_GRACE_MINUTES,
        'can_manage_schedule': can_manage_selected,
        'can_manage_templates': bool({'ADMIN', 'TENANT_ADMIN'} & actor.role_codes),
        'can_select_department': is_admin_attendance or len(accessible_departments) > 1,
        'selected_department_id': str(selected_department_id) if selected_department_id else None,
        'selected_department_name': selected_department_name,
        'departments': [
            {
                'id': str(department['id']),
                'name': department['name'],
            }
            for department in accessible_departments
        ],
        'month_start': start_date.isoformat(),
        'month_end': end_date.isoformat(),
        'calendar_title': _attendance_calendar_title(start_date),
        'days': days,
        'team_rows': team_rows,
        'reports': reports,
        'personal_summary': personal_summary,
        'personal_days': personal_days,
    }


async def _week_planned_minutes_fixed_weekly(db, employee_id: UUID, anchor: date) -> int:
    week_start = anchor - timedelta(days=anchor.weekday())
    week_end = week_start + timedelta(days=6)
    shifts = await _fetch_resolved_shifts(db, employee_id, week_start, week_end)
    return sum(int(shift.planned_minutes or 0) for shift in shifts.values())


def _is_custom_shift_code(code: str | None) -> bool:
    return bool(code and code.startswith('__CUSTOM__'))


def _parse_shift_time(value: str | None, field_name: str) -> time | None:
    if value is None or not value.strip():
        return None
    try:
        return time.fromisoformat(value.strip())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f'{field_name} must be in HH:MM format') from exc


def _custom_shift_minutes(start_value: time, end_value: time) -> tuple[int, bool]:
    start_dt = datetime.combine(date.today(), start_value)
    end_dt = datetime.combine(date.today(), end_value)
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)
    total_minutes = int((end_dt - start_dt).total_seconds() // 60)
    if total_minutes <= 0 or total_minutes > 24 * 60:
        raise HTTPException(status_code=422, detail='Custom shift duration must be between 1 minute and 24 hours')
    return total_minutes, end_dt.date() > start_dt.date()


async def _cleanup_single_day_shift_assignments(db, employee_id: UUID, shift_date: date) -> None:
    rows = await db.fetch(
        """
        SELECT a.id, sp.id AS shift_pattern_id, sp.code
          FROM assigned_shifts a
          JOIN shift_patterns sp ON sp.id = a.shift_pattern_id
         WHERE a.employee_id = $1
           AND a.effective_from = $2
           AND coalesce(a.effective_to, $2) = $2
        """,
        employee_id,
        shift_date,
    )
    if not rows:
        return
    assignment_ids = [row['id'] for row in rows]
    await db.execute(
        """
        DELETE FROM assigned_shifts
         WHERE id = ANY($1::uuid[])
        """,
        assignment_ids,
    )
    custom_pattern_ids = [row['shift_pattern_id'] for row in rows if _is_custom_shift_code(row['code'])]
    if custom_pattern_ids:
        await db.execute(
            """
            DELETE FROM shift_patterns sp
             WHERE sp.id = ANY($1::uuid[])
               AND NOT EXISTS (
                    SELECT 1
                      FROM assigned_shifts a
                     WHERE a.shift_pattern_id = sp.id
               )
            """,
            custom_pattern_ids,
        )

async def _create_custom_shift_pattern(
    db,
    *,
    legal_entity_id: UUID,
    employee_id: UUID,
    shift_date: date,
    start_value: time,
    end_value: time,
) -> UUID:
    planned_minutes, crosses_midnight = _custom_shift_minutes(start_value, end_value)
    code = f'__CUSTOM__{employee_id.hex[:8]}_{shift_date.isoformat()}_{start_value.strftime("%H%M")}_{end_value.strftime("%H%M")}'
    pattern_name = f'Custom {start_value.strftime("%H:%M")}-{end_value.strftime("%H:%M")}'
    pattern_id = await db.fetchval(
        """
        INSERT INTO shift_patterns (
            legal_entity_id,
            code,
            name,
            pattern_type,
            cycle_length_days,
            timezone,
            standard_weekly_hours,
            early_check_in_grace_minutes,
            late_check_out_grace_minutes,
            is_active
        )
        VALUES ($1, $2, $3, 'fixed_weekly', 7, 'Asia/Tbilisi', 40.00, 60, 240, true)
        RETURNING id
        """,
        legal_entity_id,
        code,
        pattern_name,
    )
    await db.execute(
        """
        INSERT INTO shift_pattern_segments (
            shift_pattern_id,
            day_index,
            start_time,
            planned_minutes,
            break_minutes,
            crosses_midnight,
            label
        )
        VALUES ($1, $2, $3, $4, 0, $5, 'Custom shift')
        """,
        pattern_id,
        shift_date.isoweekday(),
        start_value,
        planned_minutes,
        crosses_midnight,
    )
    return pattern_id


@UX_ROUTER.get('/bootstrap')
async def bootstrap_view(request: Request) -> dict[str, object]:
    tenant = getattr(request.state, 'tenant', None)
    db = get_db_from_request(request)
    ui_policy = None
    if tenant and tenant.get('legal_entity_id'):
        ui_policy = await db.fetchrow(
            """
            SELECT gps_only_check_in, company_dashboard_enabled, payroll_dashboard_enabled, dashboard_widget_visibility
              FROM entity_system_config
             WHERE legal_entity_id = $1
            """,
            tenant['legal_entity_id'],
        )
    return {
        'tenant': {
            'legal_entity_id': tenant['legal_entity_id'] if tenant else None,
            'trade_name': tenant['trade_name'] if tenant else 'ITGS HR',
            'logo_url': tenant['logo_url'] if tenant else None,
            'logo_text': tenant['logo_text'] if tenant else 'HR',
            'primary_color': tenant['primary_color'] if tenant else '#1A2238',
            'standalone_chat_url': tenant['standalone_chat_url'] if tenant else None,
            'feature_flags': tenant['feature_flags'] if tenant else DEFAULT_FEATURE_FLAGS,
            'ui_policies': {
                'gps_only_check_in': bool(ui_policy['gps_only_check_in']) if ui_policy else False,
                'company_dashboard_enabled': bool(ui_policy['company_dashboard_enabled']) if ui_policy and ui_policy['company_dashboard_enabled'] is not None else True,
                'payroll_dashboard_enabled': bool(ui_policy['payroll_dashboard_enabled']) if ui_policy and ui_policy['payroll_dashboard_enabled'] is not None else True,
                'dashboard_widget_visibility': _normalize_dashboard_widget_visibility(
                    ui_policy['dashboard_widget_visibility'] if ui_policy else None
                ),
            },
        },
    }


@UX_ROUTER.get('/dashboard/widgets')
async def widget_catalog(request: Request) -> list[dict[str, object]]:
    await require_actor(request)
    db = get_db_from_request(request)
    request_tenant_legal_entity_id = get_request_tenant_legal_entity_id(request)
    rows = await db.fetch(
        """
        SELECT widget_code::text AS widget_code, name_en, name_ka, description,
               default_w, default_h, is_mobile_supported
          FROM dashboard_widget_catalog
         ORDER BY widget_code
        """
    )
    return [dict(row) for row in rows]


@UX_ROUTER.get('/dashboard/preferences')
async def dashboard_preferences(request: Request) -> dict[str, object]:
    actor = await require_actor(request)
    db = get_db_from_request(request)
    row = await db.fetchrow(
        """
        SELECT theme_preference::text AS theme_preference, pinned_widgets, layout_json, mobile_layout_json
          FROM employee_dashboard_preferences
         WHERE employee_id = $1
        """,
        actor.employee_id,
    )
    if row is None:
        return {
            'theme_preference': 'system',
            'pinned_widgets': ['TEAM_CALENDAR', 'PENDING_APPROVALS', 'MY_KPI_PROGRESS'],
            'layout_json': [],
            'mobile_layout_json': [],
        }
    return dict(row)


@UX_ROUTER.put('/dashboard/preferences')
async def save_dashboard_preferences(request: Request, payload: DashboardPreferenceUpdate) -> dict[str, str]:
    actor = await require_actor(request)
    db = get_db_from_request(request)
    await db.execute(
        """
        INSERT INTO employee_dashboard_preferences (
            employee_id, theme_preference, pinned_widgets, layout_json, mobile_layout_json, updated_at
        ) VALUES ($1, $2::theme_preference, $3::text[], $4::jsonb, $5::jsonb, now())
        ON CONFLICT (employee_id) DO UPDATE
           SET theme_preference = EXCLUDED.theme_preference,
               pinned_widgets = EXCLUDED.pinned_widgets,
               layout_json = EXCLUDED.layout_json,
               mobile_layout_json = EXCLUDED.mobile_layout_json,
               updated_at = now()
        """,
        actor.employee_id,
        payload.theme_preference,
        payload.pinned_widgets,
        json.dumps([item.model_dump() for item in payload.layout]),
        json.dumps([item.model_dump() for item in payload.mobile_layout]),
    )
    return {'status': 'saved'}


@UX_ROUTER.get('/employee-form-options')
async def employee_form_options(request: Request) -> dict[str, object]:
    actor = await require_actor(request)
    can_access_recruitment_options = actor.has('recruitment.read') or actor.has('recruitment.manage')
    if not can_view_employee_directory(actor) and not can_access_recruitment_options:
        raise HTTPException(status_code=403, detail='Employee setup options require directory or recruitment access')
    db = get_db_from_request(request)
    can_edit = can_edit_employee_profiles(actor)
    can_view_salary = actor.has('compensation.read_all') or actor.has('employee.manage')
    can_sync_devices = actor.has('device.manage')
    can_create_department = actor.has('employee.manage')
    departments = await db.fetch(
        """
        SELECT id, name_en, name_ka
          FROM departments
         WHERE legal_entity_id = $1
           AND is_active = true
         ORDER BY name_en
        """,
        actor.legal_entity_id,
    )
    job_roles = await db.fetch(
        """
        SELECT id, title_en, title_ka
          FROM job_roles
         WHERE legal_entity_id = $1
         ORDER BY title_en
        """,
        actor.legal_entity_id,
    )
    pay_policies = (
        await db.fetch(
            """
            SELECT id, code, name
              FROM pay_policies
             WHERE legal_entity_id = $1
             ORDER BY code
            """,
            actor.legal_entity_id,
        )
        if can_view_salary
        else []
    )
    managers = await db.fetch(
        """
        SELECT e.id,
               e.first_name || ' ' || e.last_name ||
               coalesce(' ? ' || jr.title_ka, ' ? ' || jr.title_en, '') AS full_name
         FROM employees e
         LEFT JOIN job_roles jr ON jr.id = e.job_role_id
         WHERE e.legal_entity_id = $1
           AND e.employment_status = 'active'
           AND e.deleted_at IS NULL
         ORDER BY e.first_name, e.last_name
        """,
        actor.legal_entity_id,
    )
    devices = (
        await db.fetch(
            """
            SELECT id, device_name, brand::text AS brand, host, serial_number
              FROM device_registry
             WHERE legal_entity_id = $1
               AND is_active = true
             ORDER BY device_name
            """,
            actor.legal_entity_id,
        )
        if can_sync_devices
        else []
    )
    return {
        'legal_entity_id': str(actor.legal_entity_id),
        'departments': [dict(row) for row in departments],
        'job_roles': [dict(row) for row in job_roles],
        'pay_policies': [dict(row) for row in pay_policies],
        'managers': [dict(row) for row in managers],
        'devices': [dict(row) for row in devices],
        'permissions': {
            'can_edit': can_edit,
            'can_view_salary': can_view_salary,
            'can_sync_devices': can_sync_devices,
            'can_create_department': can_create_department,
        },
    }

@UX_ROUTER.get('/home-data')
async def home_data(request: Request) -> dict[str, object]:
    actor = await require_actor(request)
    db = get_db_from_request(request)
    widgets = await widget_catalog(request)
    ui_policy = await _entity_ui_policy_flags(db, actor.legal_entity_id)
    company_scope = _actor_can_access_company_home_dashboard(actor) and bool(ui_policy['company_dashboard_enabled'])
    if company_scope:
        summary = await db.fetchrow(
            """
            SELECT
                count(*) FILTER (WHERE employment_status = 'active') AS active_employees,
                count(*) FILTER (WHERE employment_status = 'terminated') AS terminated_employees
              FROM employees
             WHERE legal_entity_id = $1
               AND deleted_at IS NULL
            """,
            actor.legal_entity_id,
        )
        pending_approvals = await db.fetchval(
            """
            SELECT count(*)
              FROM leave_requests lr
              JOIN employees e ON e.id = lr.employee_id
             WHERE e.legal_entity_id = $1
               AND lr.status = 'submitted'
            """,
            actor.legal_entity_id,
        )
        online_devices = await db.fetchval(
            """
            SELECT count(*)
              FROM device_registry
             WHERE legal_entity_id = $1
               AND is_active = true
               AND last_seen_at >= now() - interval '10 minutes'
            """,
            actor.legal_entity_id,
        )
        weekly_rows = await db.fetch(
            """
            SELECT work_date,
                   count(DISTINCT employee_id) AS checked_in
              FROM (
                     SELECT ral.employee_id,
                            (ral.event_ts AT TIME ZONE 'Asia/Tbilisi')::date AS work_date
                       FROM raw_attendance_logs ral
                       JOIN employees e ON e.id = ral.employee_id
                      WHERE e.legal_entity_id = $1
                        AND (ral.event_ts AT TIME ZONE 'Asia/Tbilisi')::date BETWEEN date_trunc('week', now() AT TIME ZONE 'Asia/Tbilisi')::date
                            AND date_trunc('week', now() AT TIME ZONE 'Asia/Tbilisi')::date + interval '6 days'
                        AND ral.direction::text = 'in'
                     UNION
                     SELECT wpe.employee_id,
                            (wpe.punch_ts AT TIME ZONE 'Asia/Tbilisi')::date AS work_date
                       FROM web_punch_events wpe
                      WHERE wpe.legal_entity_id = $1
                        AND wpe.is_valid = true
                        AND (wpe.punch_ts AT TIME ZONE 'Asia/Tbilisi')::date BETWEEN date_trunc('week', now() AT TIME ZONE 'Asia/Tbilisi')::date
                            AND date_trunc('week', now() AT TIME ZONE 'Asia/Tbilisi')::date + interval '6 days'
                 ) t
             GROUP BY work_date
             ORDER BY work_date
            """,
            actor.legal_entity_id,
        )
        summary_payload = {
            'scope': 'company',
            'active_employees': int(summary['active_employees'] or 0),
            'terminated_employees': int(summary['terminated_employees'] or 0),
            'pending_approvals': int(pending_approvals or 0),
            'online_devices': int(online_devices or 0),
            'pending_leave_requests': None,
            'last_punch_at': None,
            'last_punch_direction': None,
            'is_checked_in': None,
        }
    else:
        pending_leave_requests = await db.fetchval(
            """
            SELECT count(*)
              FROM leave_requests
             WHERE employee_id = $1
               AND status::text IN ('submitted', 'manager_pending', 'hr_pending')
            """,
            actor.employee_id,
        )
        last_punch = await db.fetchrow(
            """
            SELECT event_ts, direction
              FROM (
                    SELECT ral.event_ts, ral.direction::text AS direction
                      FROM raw_attendance_logs ral
                     WHERE ral.employee_id = $1
                    UNION ALL
                    SELECT wpe.punch_ts AS event_ts, wpe.direction::text AS direction
                      FROM web_punch_events wpe
                     WHERE wpe.employee_id = $1
                       AND wpe.is_valid = true
              ) punches
             ORDER BY event_ts DESC
             LIMIT 1
            """,
            actor.employee_id,
        )
        current_day_rows = await db.fetch(
            """
            SELECT punch_ts, direction
              FROM (
                    SELECT ral.event_ts AS punch_ts, ral.direction::text AS direction
                      FROM raw_attendance_logs ral
                     WHERE ral.employee_id = $1
                       AND (ral.event_ts AT TIME ZONE 'Asia/Tbilisi')::date = current_date
                    UNION ALL
                    SELECT wpe.punch_ts, wpe.direction::text AS direction
                      FROM web_punch_events wpe
                     WHERE wpe.employee_id = $1
                       AND wpe.is_valid = true
                       AND (wpe.punch_ts AT TIME ZONE 'Asia/Tbilisi')::date = current_date
              ) punches
             ORDER BY punch_ts
            """,
            actor.employee_id,
        )
        web_punch_summary = _summarize_web_punch_rows([dict(row) for row in current_day_rows])
        weekly_rows = await db.fetch(
            """
            SELECT work_date, count(*) AS checked_in
              FROM (
                     SELECT DISTINCT (ral.event_ts AT TIME ZONE 'Asia/Tbilisi')::date AS work_date
                       FROM raw_attendance_logs ral
                      WHERE ral.employee_id = $1
                        AND ral.direction::text = 'in'
                        AND (ral.event_ts AT TIME ZONE 'Asia/Tbilisi')::date BETWEEN date_trunc('week', now() AT TIME ZONE 'Asia/Tbilisi')::date
                            AND date_trunc('week', now() AT TIME ZONE 'Asia/Tbilisi')::date + interval '6 days'
                     UNION
                     SELECT DISTINCT (wpe.punch_ts AT TIME ZONE 'Asia/Tbilisi')::date AS work_date
                       FROM web_punch_events wpe
                      WHERE wpe.employee_id = $1
                        AND wpe.is_valid = true
                        AND (wpe.punch_ts AT TIME ZONE 'Asia/Tbilisi')::date BETWEEN date_trunc('week', now() AT TIME ZONE 'Asia/Tbilisi')::date
                            AND date_trunc('week', now() AT TIME ZONE 'Asia/Tbilisi')::date + interval '6 days'
                 ) t
             GROUP BY work_date
             ORDER BY work_date
            """,
            actor.employee_id,
        )
        summary_payload = {
            'scope': 'self',
            'active_employees': 0,
            'terminated_employees': 0,
            'pending_approvals': int(pending_leave_requests or 0),
            'online_devices': 0,
            'pending_leave_requests': int(pending_leave_requests or 0),
            'last_punch_at': last_punch['event_ts'].isoformat() if last_punch else None,
            'last_punch_direction': last_punch['direction'] if last_punch else None,
            'is_checked_in': bool(web_punch_summary['is_checked_in']),
        }

    week_start = date.today() - timedelta(days=date.today().weekday())
    attendance_map = {row['work_date']: int(row['checked_in'] or 0) for row in weekly_rows}
    weekly_attendance = [
        {
            'label': ATTENDANCE_WEEKDAY_LABELS[(week_start + timedelta(days=i)).isoweekday()],
            'count': attendance_map.get(week_start + timedelta(days=i), 0),
        }
        for i in range(7)
    ]
    preferences = await dashboard_preferences(request)
    upcoming_schedule = await get_upcoming_google_schedule(db, actor.employee_id)
    return {
        'summary': summary_payload,
        'weekly_attendance': weekly_attendance,
        'upcoming_schedule': upcoming_schedule,
        'widgets': widgets,
        'preferences': preferences,
    }


@UX_ROUTER.get('/employees-grid')
async def employees_grid(
    request: Request,
    search: str | None = None,
    status_filter: str | None = None,
    department_id: UUID | None = None,
    email_contains: str | None = None,
    phone_contains: str | None = None,
    salary_min: Decimal | None = None,
    salary_max: Decimal | None = None,
    sort_by: Literal['employee_number', 'full_name', 'department_name', 'job_title', 'employment_status', 'hire_date'] = 'employee_number',
    sort_direction: Literal['asc', 'desc'] = 'asc',
    page: int = 1,
    page_size: int = 12,
) -> dict[str, object]:
    actor = await require_actor(request)
    if not can_view_employee_directory(actor):
        raise HTTPException(status_code=403, detail='თანამშრომლების ბადისთვის საჭიროა employee.manage უფლება')
    db = get_db_from_request(request)
    directory_scope = employee_directory_scope(actor)
    managed_department_ids = list(actor.managed_department_ids)
    can_view_salary = actor.has('compensation.read_all') or actor.has('employee.manage')
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    sortable_columns = {
        'employee_number': 'e.employee_number',
        'full_name': "e.first_name || ' ' || e.last_name",
        'department_name': 'd.name_en',
        'job_title': 'jr.title_en',
        'employment_status': 'e.employment_status::text',
        'hire_date': 'e.hire_date',
    }
    order_by = sortable_columns[sort_by]
    direction = 'DESC' if sort_direction == 'desc' else 'ASC'
    q = f'%{search.strip()}%' if search else None
    em = f'%{email_contains.strip()}%' if email_contains else None
    ph = f'%{phone_contains.strip()}%' if phone_contains else None
    total_count = await db.fetchval(
        """
        SELECT count(*)
          FROM employees e
          LEFT JOIN LATERAL (
              SELECT base_salary
                FROM employee_compensation
               WHERE employee_id = e.id
               ORDER BY effective_from DESC
               LIMIT 1
         ) ec ON true
         WHERE e.legal_entity_id = $1
           AND e.deleted_at IS NULL
           AND (
                $2::text = 'all'
                OR ($2::text = 'department' AND e.department_id = ANY($3::uuid[]))
                OR ($2::text = 'self' AND e.id = $4)
           )
           AND ($5::text IS NULL OR e.first_name ILIKE $5 OR e.last_name ILIKE $5
                OR e.employee_number ILIKE $5 OR e.email ILIKE $5 OR e.mobile_phone ILIKE $5)
           AND ($6::text IS NULL OR e.employment_status::text = $6)
           AND ($7::uuid IS NULL OR e.department_id = $7)
           AND ($8::text IS NULL OR e.email ILIKE $8)
           AND ($9::text IS NULL OR e.mobile_phone ILIKE $9)
           AND ($10::numeric IS NULL OR coalesce(ec.base_salary, 0) >= $10)
           AND ($11::numeric IS NULL OR coalesce(ec.base_salary, 0) <= $11)
        """,
        actor.legal_entity_id,
        directory_scope,
        managed_department_ids,
        actor.employee_id,
        q,
        status_filter,
        department_id,
        em,
        ph,
        salary_min if can_view_salary else None,
        salary_max if can_view_salary else None,
    )
    rows = await db.fetch(
        f"""
        SELECT e.id,
               e.employee_number,
               e.first_name,
               e.last_name,
               e.email,
               e.mobile_phone,
               e.hire_date,
               e.department_id,
               e.employment_status::text AS employment_status,
               d.name_en AS department_name,
               jr.title_en AS job_title,
               m.first_name || ' ' || m.last_name AS manager_name,
               p.file_url AS profile_photo_url,
               coalesce(ec.base_salary, 0) AS base_salary,
               coalesce(ec.hourly_rate_override, 0) AS hourly_rate_override,
               EXISTS (
                   SELECT 1
                     FROM auth_identities ai
                    WHERE ai.employee_id = e.id
                      AND ai.is_active = true
               ) AS has_login_access,
               la.punch_ts AS last_attendance_at,
               la.direction AS last_attendance_direction,
               coalesce(la.direction = 'in', false) AS is_checked_in
          FROM employees e
          LEFT JOIN departments d ON d.id = e.department_id
          LEFT JOIN job_roles jr ON jr.id = e.job_role_id
          LEFT JOIN employees m ON m.id = coalesce(e.line_manager_id, e.manager_employee_id)
          LEFT JOIN LATERAL (
              SELECT file_url
                FROM employee_file_uploads
               WHERE employee_id = e.id
                 AND file_category = 'profile_photo'
               ORDER BY created_at DESC
               LIMIT 1
          ) p ON true
          LEFT JOIN LATERAL (
              SELECT base_salary, hourly_rate_override
                FROM employee_compensation
               WHERE employee_id = e.id
               ORDER BY effective_from DESC
               LIMIT 1
         ) ec ON true
          LEFT JOIN LATERAL (
              SELECT punch_ts, direction
                FROM (
                      SELECT ral.event_ts AS punch_ts,
                             ral.direction::text AS direction
                        FROM raw_attendance_logs ral
                       WHERE ral.employee_id = e.id
                         AND (ral.event_ts AT TIME ZONE 'Asia/Tbilisi')::date = (timezone('Asia/Tbilisi', now()))::date
                         AND ral.direction IN ('in', 'out')
                      UNION ALL
                      SELECT wpe.punch_ts,
                             wpe.direction::text AS direction
                        FROM web_punch_events wpe
                       WHERE wpe.employee_id = e.id
                         AND wpe.is_valid = true
                         AND (wpe.punch_ts AT TIME ZONE 'Asia/Tbilisi')::date = (timezone('Asia/Tbilisi', now()))::date
                         AND wpe.direction IN ('in', 'out')
                ) punches
               ORDER BY punch_ts DESC
               LIMIT 1
          ) la ON true
         WHERE e.legal_entity_id = $1
           AND e.deleted_at IS NULL
           AND (
                $2::text = 'all'
                OR ($2::text = 'department' AND e.department_id = ANY($3::uuid[]))
                OR ($2::text = 'self' AND e.id = $4)
           )
           AND ($5::text IS NULL OR e.first_name ILIKE $5 OR e.last_name ILIKE $5
                OR e.employee_number ILIKE $5 OR e.email ILIKE $5 OR e.mobile_phone ILIKE $5)
           AND ($6::text IS NULL OR e.employment_status::text = $6)
           AND ($7::uuid IS NULL OR e.department_id = $7)
           AND ($8::text IS NULL OR e.email ILIKE $8)
           AND ($9::text IS NULL OR e.mobile_phone ILIKE $9)
           AND ($10::numeric IS NULL OR coalesce(ec.base_salary, 0) >= $10)
           AND ($11::numeric IS NULL OR coalesce(ec.base_salary, 0) <= $11)
         ORDER BY {order_by} {direction}, e.employee_number ASC
         LIMIT $12 OFFSET $13
        """,
        actor.legal_entity_id,
        directory_scope,
        managed_department_ids,
        actor.employee_id,
        q,
        status_filter,
        department_id,
        em,
        ph,
        salary_min if can_view_salary else None,
        salary_max if can_view_salary else None,
        page_size,
        (page - 1) * page_size,
    )
    items = []
    for row in rows:
        payload = dict(row)
        if not can_view_salary:
            payload['base_salary'] = None
            payload['hourly_rate_override'] = None
        payload['can_edit'] = can_edit_employee_profiles(actor, row['department_id'])
        items.append(payload)
    return {
        'items': items,
        'total': int(total_count or 0),
        'page': page,
        'page_size': page_size,
        'page_count': max((int(total_count or 0) + page_size - 1) // page_size, 1),
        'permissions': {
            'can_create': actor.has('employee.manage'),
            'can_create_department': actor.has('employee.manage'),
            'can_edit': can_edit_employee_profiles(actor),
            'can_view_salary': can_view_salary,
            'can_import': can_import_employees(actor),
            'can_export': can_export_employees(actor),
            'can_grant_access': actor.has('employee.manage'),
            'can_sync_devices': actor.has('device.manage'),
            'can_view_attendance': actor.has('attendance.read_all') or actor.has('attendance.read_department') or actor.has('employee.manage'),
            'can_offboard': actor.has('employee.manage'),
            'can_delete': actor.has('employee.manage'),
        },
    }


@UX_ROUTER.get('/employee-attendance/{employee_id}')
async def employee_attendance_preview(request: Request, employee_id: UUID) -> list[dict[str, object]]:
    actor = await require_actor(request)
    db = get_db_from_request(request)
    employee_row = await db.fetchrow(
        'SELECT department_id FROM employees WHERE id = $1 AND deleted_at IS NULL',
        employee_id,
    )
    if employee_row is None:
        raise HTTPException(status_code=404, detail='Employee not found')
    try:
        ensure_can_view_attendance(actor, employee_id, employee_row['department_id'])
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    rows = await db.fetch(
        """
        SELECT ral.id,
               ral.event_ts,
               ral.direction::text AS direction,
               ral.verify_mode,
               coalesce(dr.device_name, ral.raw_payload ->> 'device_name', 'Middleware') AS device_name,
               (ral.event_ts AT TIME ZONE 'Asia/Tbilisi')::date AS work_date
          FROM raw_attendance_logs ral
          LEFT JOIN device_registry dr ON dr.id = ral.device_id
         WHERE ral.employee_id = $1
         ORDER BY ral.event_ts DESC
         LIMIT 60
        """,
        employee_id,
    )
    if not rows:
        return []
    work_dates = sorted({row['work_date'] for row in rows if row['work_date'] is not None})
    min_date = min(work_dates)
    max_date = max(work_dates)
    threshold_minutes = await db.fetchval(
        'SELECT late_arrival_threshold_minutes FROM entity_operation_settings WHERE legal_entity_id = $1',
        actor.legal_entity_id,
    ) or 15
    shifts = await _fetch_resolved_shifts(db, employee_id, min_date, max_date)
    first_logs = await db.fetch(
        """
        SELECT (event_ts AT TIME ZONE 'Asia/Tbilisi')::date AS work_date,
               min(event_ts) AS first_event_ts
          FROM raw_attendance_logs
         WHERE employee_id = $1
           AND (event_ts AT TIME ZONE 'Asia/Tbilisi')::date = ANY($2::date[])
         GROUP BY 1
        """,
        employee_id,
        work_dates,
    )
    first_log_map = {row['work_date']: row['first_event_ts'] for row in first_logs}
    session_rows = await db.fetch(
        """
        SELECT work_date,
               coalesce(sum(total_minutes), 0) AS total_minutes,
               coalesce(sum(overtime_minutes), 0) AS overtime_minutes
          FROM attendance_work_sessions
         WHERE employee_id = $1
           AND work_date BETWEEN $2 AND $3
         GROUP BY work_date
        """,
        employee_id,
        min_date,
        max_date,
    )
    session_map = {row['work_date']: dict(row) for row in session_rows}
    weekly_rows = await db.fetch(
        """
        SELECT date_trunc('week', work_date::timestamp)::date AS week_start,
               coalesce(sum(total_minutes), 0) AS weekly_minutes
         FROM attendance_work_sessions
         WHERE employee_id = $1
           AND work_date BETWEEN ($2::date - 6) AND $3::date
         GROUP BY 1
        """,
        employee_id,
        min_date,
        max_date,
    )
    weekly_map = {row['week_start']: int(row['weekly_minutes'] or 0) for row in weekly_rows}

    payload = []
    for row in rows:
        record = dict(row)
        work_date = record['work_date']
        shift = shifts.get(work_date)
        first_event_ts = first_log_map.get(work_date)
        late_minutes = 0
        is_late = False
        if shift is not None and first_event_ts is not None:
            late_threshold = shift.start_local + timedelta(minutes=int(threshold_minutes))
            if first_event_ts > late_threshold:
                late_minutes = int((first_event_ts - late_threshold).total_seconds() // 60)
                is_late = late_minutes > 0
        week_start = work_date - timedelta(days=work_date.weekday())
        weekly_minutes = weekly_map.get(week_start, 0)
        overtime_minutes = int((session_map.get(work_date) or {}).get('overtime_minutes') or max(weekly_minutes - 2400, 0))
        record['weekly_minutes'] = weekly_minutes
        record['overtime_minutes'] = overtime_minutes
        record['late_minutes'] = late_minutes
        record['is_late'] = is_late
        record['is_overtime'] = overtime_minutes > 0
        record['highlight_tags'] = [tag for tag, enabled in (('late', is_late), ('ot', overtime_minutes > 0)) if enabled]
        payload.append(record)
    return payload


@UX_ROUTER.get('/personal-reports')
async def personal_reports(request: Request) -> dict[str, object]:
    actor = await require_actor(request)
    db = get_db_from_request(request)
    today = date.today()
    month_start = today.replace(day=1)
    movement_rows = await db.fetch(
        """
        SELECT ral.id::text AS id,
               ral.event_ts,
               ral.direction::text AS direction,
               coalesce(dr.device_name, 'Web') AS device_name,
               'device'::text AS source_type
          FROM raw_attendance_logs ral
          LEFT JOIN device_registry dr ON dr.id = ral.device_id
         WHERE ral.employee_id = $1
           AND (ral.event_ts AT TIME ZONE 'Asia/Tbilisi')::date >= $2
        UNION ALL
        SELECT wpe.id::text AS id,
               wpe.punch_ts AS event_ts,
               wpe.direction::text AS direction,
               'Web Punch' AS device_name,
               'web'::text AS source_type
          FROM web_punch_events wpe
         WHERE wpe.employee_id = $1
           AND (wpe.punch_ts AT TIME ZONE 'Asia/Tbilisi')::date >= $2
         ORDER BY event_ts DESC
         LIMIT 80
        """,
        actor.employee_id,
        month_start,
    )
    report_rows = await db.fetch(
        """
        SELECT work_date, total_minutes, overtime_minutes
          FROM attendance_work_sessions
         WHERE employee_id = $1
           AND work_date >= $2
         ORDER BY work_date DESC
        """,
        actor.employee_id,
        month_start,
    )
    late_days = 0
    overtime_minutes = 0
    for row in report_rows:
        overtime_minutes += int(row['overtime_minutes'] or 0)
        if int(row['total_minutes'] or 0) > 480:
            late_days += 0
    attendance_items = await employee_attendance_preview(request, actor.employee_id)
    late_days = sum(1 for item in attendance_items if item.get('is_late'))
    return {
        'movement_log': [
            {
                'id': row['id'],
                'event_ts': row['event_ts'].isoformat(),
                'direction': row['direction'],
                'device_name': row['device_name'],
                'source_type': row['source_type'],
            }
            for row in movement_rows
        ],
        'summary': {
            'month_start': month_start.isoformat(),
            'late_days': late_days,
            'overtime_hours': round(overtime_minutes / 60, 2),
        },
        'lateness_overtime_report': attendance_items,
    }


@UX_ROUTER.get('/attendance-live-feed')
async def attendance_live_feed(request: Request) -> list[dict[str, object]]:
    actor = await require_actor(request)
    if not (actor.has('attendance.read_all') or actor.has('employee.manage') or bool({'ADMIN', 'TENANT_ADMIN'} & actor.role_codes)):
        raise HTTPException(status_code=403, detail='Live feed is available only for company-wide attendance access')
    db = get_db_from_request(request)
    ui_policy = await _entity_ui_policy_flags(db, actor.legal_entity_id)
    if not ui_policy['company_dashboard_enabled']:
        raise HTTPException(status_code=403, detail='Company dashboard is disabled in system settings')
    rows = await db.fetch(
        """
        SELECT *
          FROM (
                SELECT 'attendance' AS event_type,
                       ral.id::text AS event_id,
                       ral.event_ts AS ts,
                       ral.direction::text AS direction,
                       e.id AS employee_id,
                       e.first_name,
                       e.last_name,
                       e.employee_number,
                       coalesce(dr.device_name, ral.raw_payload ->> 'device_name', 'Middleware') AS device_name,
                       coalesce(dr.host, ral.raw_payload ->> 'device_serial', ral.raw_payload ->> 'device_name', 'Middleware') AS host,
                       NULL::text AS device_status
                  FROM raw_attendance_logs ral
                  JOIN employees e ON e.id = ral.employee_id
                  LEFT JOIN device_registry dr ON dr.id = ral.device_id
                 WHERE e.legal_entity_id = $1
                   AND ral.event_ts >= now() - interval '7 days'

                UNION ALL

                SELECT 'web_punch' AS event_type,
                       wpe.id::text AS event_id,
                       wpe.punch_ts AS ts,
                       wpe.direction::text AS direction,
                       e.id AS employee_id,
                       e.first_name,
                       e.last_name,
                       e.employee_number,
                       'Web Punch' AS device_name,
                       coalesce(wpe.source_ip, 'Web') AS host,
                       NULL::text AS device_status
                  FROM web_punch_events wpe
                  JOIN employees e ON e.id = wpe.employee_id
                 WHERE wpe.legal_entity_id = $1
                   AND wpe.is_valid = true
                   AND wpe.punch_ts >= now() - interval '7 days'
               ) live_union
         ORDER BY ts DESC
         LIMIT 25
        """,
        actor.legal_entity_id,
    )
    offline_devices = await db.fetch(
        """
        SELECT 'device' AS event_type,
               dr.id::text AS event_id,
               coalesce(dr.last_seen_at, now() - interval '1 day') AS ts,
               'unknown' AS direction,
               NULL::uuid AS employee_id,
               NULL::text AS first_name,
               NULL::text AS last_name,
               NULL::text AS employee_number,
               dr.device_name,
               dr.host,
               'offline' AS device_status
          FROM device_registry dr
         WHERE dr.legal_entity_id = $1
           AND dr.is_active = true
           AND dr.transport::text IN ('sdk_bridge', 'raw_socket', 'adms', 'adms_push')
           AND (dr.last_seen_at IS NULL OR dr.last_seen_at < now() - interval '10 minutes')
         ORDER BY dr.last_seen_at NULLS FIRST
         LIMIT 10
        """,
        actor.legal_entity_id,
    )
    events = [dict(row) for row in rows] + [dict(row) for row in offline_devices]
    events.sort(key=lambda item: item['ts'], reverse=True)
    return events[:25]


@UX_ROUTER.get('/analytics-overview')
async def analytics_overview(request: Request) -> dict[str, object]:
    actor = await require_actor(request)
    if not (actor.has('attendance.read_all') or actor.has('employee.manage') or bool({'ADMIN', 'TENANT_ADMIN'} & actor.role_codes)):
        raise HTTPException(status_code=403, detail='Analytics overview is available only for company-wide attendance access')
    db = get_db_from_request(request)
    ui_policy = await _entity_ui_policy_flags(db, actor.legal_entity_id)
    if not ui_policy['company_dashboard_enabled']:
        raise HTTPException(status_code=403, detail='Company dashboard is disabled in system settings')
    today = _georgia_today()
    this_week_start = _georgia_range_start(today)
    last_week_start = this_week_start - timedelta(days=7)
    this_week_days = [this_week_start + timedelta(days=index) for index in range(7)]
    last_week_days = [last_week_start + timedelta(days=index) for index in range(7)]
    trend_rows = await db.fetch(
        """
        WITH days AS (
            SELECT generate_series(current_date - 6, current_date, interval '1 day')::date AS work_date
        )
        SELECT days.work_date,
               round(coalesce(sum(aws.total_minutes), 0)::numeric / 60, 2) AS worked_hours
          FROM days
          LEFT JOIN attendance_work_sessions aws ON aws.work_date = days.work_date
          LEFT JOIN employees e ON e.id = aws.employee_id
         WHERE e.legal_entity_id = $1 OR e.id IS NULL
         GROUP BY days.work_date
         ORDER BY days.work_date
        """,
        actor.legal_entity_id,
    )
    attendance_rows = await db.fetch(
        """
        WITH attendance_events AS (
            SELECT (ral.event_ts AT TIME ZONE 'Asia/Tbilisi')::date AS work_date,
                   ral.employee_id
              FROM raw_attendance_logs ral
              JOIN employees e ON e.id = ral.employee_id
             WHERE e.legal_entity_id = $1
               AND ral.direction::text = 'in'
               AND (ral.event_ts AT TIME ZONE 'Asia/Tbilisi')::date BETWEEN $2 AND $3
            UNION
            SELECT (wpe.punch_ts AT TIME ZONE 'Asia/Tbilisi')::date AS work_date,
                   wpe.employee_id
              FROM web_punch_events wpe
             WHERE wpe.legal_entity_id = $1
               AND wpe.is_valid = true
               AND wpe.direction::text = 'in'
               AND (wpe.punch_ts AT TIME ZONE 'Asia/Tbilisi')::date BETWEEN $2 AND $3
        )
        SELECT work_date, count(DISTINCT employee_id) AS total_count
          FROM attendance_events
         GROUP BY work_date
        """,
        actor.legal_entity_id,
        last_week_start,
        today,
    )
    leave_rows = await db.fetch(
        """
        WITH days AS (
            SELECT generate_series($2::date, $3::date, interval '1 day')::date AS work_date
        )
        SELECT days.work_date,
               count(DISTINCT lr.employee_id) AS total_count
          FROM days
          LEFT JOIN leave_requests lr
            ON days.work_date BETWEEN lr.start_date AND lr.end_date
           AND lr.status = 'approved'
          LEFT JOIN employees e ON e.id = lr.employee_id
         WHERE e.legal_entity_id = $1 OR e.id IS NULL
         GROUP BY days.work_date
        """,
        actor.legal_entity_id,
        last_week_start,
        today,
    )
    active_employee_rows = await db.fetch(
        """
        SELECT id
          FROM employees
         WHERE legal_entity_id = $1
           AND employment_status = 'active'
        """,
        actor.legal_entity_id,
    )
    threshold_minutes = await db.fetchval(
        'SELECT late_arrival_threshold_minutes FROM entity_operation_settings WHERE legal_entity_id = $1',
        actor.legal_entity_id,
    ) or 15
    first_in_rows = await db.fetch(
        """
        WITH first_in AS (
            SELECT employee_id,
                   work_date,
                   min(event_ts) AS first_event_ts
              FROM (
                    SELECT ral.employee_id,
                           (ral.event_ts AT TIME ZONE 'Asia/Tbilisi')::date AS work_date,
                           ral.event_ts
                      FROM raw_attendance_logs ral
                      JOIN employees e ON e.id = ral.employee_id
                     WHERE e.legal_entity_id = $1
                       AND ral.direction::text = 'in'
                       AND (ral.event_ts AT TIME ZONE 'Asia/Tbilisi')::date BETWEEN $2 AND $3
                    UNION ALL
                    SELECT wpe.employee_id,
                           (wpe.punch_ts AT TIME ZONE 'Asia/Tbilisi')::date AS work_date,
                           wpe.punch_ts AS event_ts
                      FROM web_punch_events wpe
                     WHERE wpe.legal_entity_id = $1
                       AND wpe.is_valid = true
                       AND wpe.direction::text = 'in'
                       AND (wpe.punch_ts AT TIME ZONE 'Asia/Tbilisi')::date BETWEEN $2 AND $3
              ) events
             GROUP BY employee_id, work_date
        )
        SELECT employee_id, work_date, first_event_ts
          FROM first_in
        """,
        actor.legal_entity_id,
        last_week_start,
        today,
    )
    late_map: dict[date, int] = {}
    if first_in_rows:
        employee_shift_cache: dict[UUID, dict[date, object]] = {}
        for employee_id in {row['employee_id'] for row in first_in_rows}:
            employee_shift_cache[employee_id] = await _fetch_resolved_shifts(db, employee_id, last_week_start, today)
        for row in first_in_rows:
            shift = employee_shift_cache.get(row['employee_id'], {}).get(row['work_date'])
            if shift is None:
                continue
            late_threshold = shift.start_local + timedelta(minutes=int(threshold_minutes))
            first_event_ts = row['first_event_ts'].astimezone(GEORGIA_TZ)
            if first_event_ts > late_threshold:
                late_map[row['work_date']] = late_map.get(row['work_date'], 0) + 1

    attendance_map = {row['work_date']: int(row['total_count'] or 0) for row in attendance_rows}
    leave_map = {row['work_date']: int(row['total_count'] or 0) for row in leave_rows}
    active_total = len(active_employee_rows)
    absences_map = {
        day: max(0, active_total - attendance_map.get(day, 0) - leave_map.get(day, 0))
        for day in [*last_week_days, *this_week_days]
    }
    presence = await db.fetchrow(
        """
        WITH latest_logs AS (
            SELECT DISTINCT ON (events.employee_id)
                   events.employee_id,
                   events.direction
              FROM (
                    SELECT ral.employee_id,
                           ral.direction::text AS direction,
                           ral.event_ts
                      FROM raw_attendance_logs ral
                      JOIN employees e ON e.id = ral.employee_id
                     WHERE e.legal_entity_id = $1
                       AND (ral.event_ts AT TIME ZONE 'Asia/Tbilisi')::date = (timezone('Asia/Tbilisi', now()))::date
                    UNION ALL
                    SELECT wpe.employee_id,
                           wpe.direction::text AS direction,
                           wpe.punch_ts AS event_ts
                      FROM web_punch_events wpe
                     WHERE wpe.legal_entity_id = $1
                       AND wpe.is_valid = true
                       AND (wpe.punch_ts AT TIME ZONE 'Asia/Tbilisi')::date = (timezone('Asia/Tbilisi', now()))::date
              ) events
             ORDER BY events.employee_id, events.event_ts DESC
        )
        SELECT
            count(*) FILTER (WHERE e.employment_status = 'active') AS active_total,
            count(*) FILTER (WHERE e.employment_status = 'active' AND ll.direction = 'in') AS present_now
          FROM employees e
          LEFT JOIN latest_logs ll ON ll.employee_id = e.id
         WHERE e.legal_entity_id = $1
        """,
        actor.legal_entity_id,
    )
    performers = await db.fetch(
        """
        WITH week_bounds AS (
            SELECT date_trunc('week', current_date)::date AS wstart,
                   (date_trunc('week', current_date) + interval '6 days')::date AS wend
        ),
        sched AS (
            SELECT a.employee_id,
                   sum(sps.planned_minutes)::numeric AS sched_min
              FROM assigned_shifts a
              JOIN week_bounds wb ON true
              JOIN shift_pattern_segments sps ON sps.shift_pattern_id = a.shift_pattern_id
                 AND sps.day_index = extract(isodow from a.effective_from)::int
             WHERE a.effective_from BETWEEN wb.wstart AND wb.wend
             GROUP BY a.employee_id
        ),
        work AS (
            SELECT aws.employee_id,
                   sum(aws.total_minutes)::numeric AS work_min
              FROM attendance_work_sessions aws
              JOIN week_bounds wb ON aws.work_date BETWEEN wb.wstart AND wb.wend
             GROUP BY aws.employee_id
        ),
        pen AS (
            SELECT arf.employee_id,
                   count(*)::numeric AS penalty
              FROM attendance_review_flags arf
              JOIN week_bounds wb ON arf.raised_at::date BETWEEN wb.wstart AND wb.wend
             GROUP BY arf.employee_id
        )
        SELECT e.id,
               e.first_name,
               e.last_name,
               coalesce(w.work_min, 0) AS work_min,
               coalesce(s.sched_min, 1) AS sched_min,
               coalesce(p.penalty, 0) AS penalty
          FROM employees e
          LEFT JOIN work w ON w.employee_id = e.id
          LEFT JOIN sched s ON s.employee_id = e.id
          LEFT JOIN pen p ON p.employee_id = e.id
         WHERE e.legal_entity_id = $1
           AND e.employment_status = 'active'
         ORDER BY (
           (coalesce(w.work_min, 0) / greatest(coalesce(s.sched_min, 1), 1)) - 0.05 * coalesce(p.penalty, 0)
         ) DESC NULLS LAST
         LIMIT 3
        """,
        actor.legal_entity_id,
    )
    top_performers = []
    for row in performers:
        ratio = float(row['work_min'] or 0) / max(float(row['sched_min'] or 1), 1.0)
        penalty = float(row['penalty'] or 0)
        score = max(0.0, min(1.0, ratio - 0.05 * penalty))
        present_ratio = float(row['work_min'] or 0) / max(float(row['sched_min'] or 1), 1.0)
        if present_ratio >= 0.95:
            status = 'present'
        elif present_ratio >= 0.7:
            status = 'late'
        else:
            status = 'absent'
        top_performers.append(
            {
                'employee_id': str(row['id']),
                'full_name': f"{row['first_name']} {row['last_name']}".strip(),
                'score': round(score, 3),
                'status': status,
            }
        )

    return {
        'weekly_hours_trend': [
            {'label': row['work_date'].isoformat(), 'worked_hours': float(row['worked_hours'])}
            for row in trend_rows
        ],
        'staff_presence_ratio': {
            'present': int(presence['present_now'] or 0),
            'away': max(int(presence['active_total'] or 0) - int(presence['present_now'] or 0), 0),
            'total': int(presence['active_total'] or 0),
        },
        'dashboard_series': {
            'labels': [ATTENDANCE_WEEKDAY_LABELS[day.isoweekday()] for day in this_week_days],
            'this_week': {
                'attendance': _build_series(this_week_days, attendance_map),
                'late': _build_series(this_week_days, late_map),
                'leave': _build_series(this_week_days, leave_map),
                'absences': _build_series(this_week_days, absences_map),
            },
            'last_week': {
                'attendance': _build_series(last_week_days, attendance_map),
                'late': _build_series(last_week_days, late_map),
                'leave': _build_series(last_week_days, leave_map),
                'absences': _build_series(last_week_days, absences_map),
            },
        },
        'top_performers': top_performers,
    }


@UX_ROUTER.get('/celebration-hub')
async def celebration_hub(request: Request) -> dict[str, object]:
    actor = await require_actor(request)
    db = get_db_from_request(request)
    today = datetime.now().date()
    birthdays = await db.fetch(
        """
        SELECT id,
               first_name,
               last_name,
               birth_date,
               extract(day from birth_date)::int AS day_of_month
          FROM employees
         WHERE legal_entity_id = $1
           AND birth_date IS NOT NULL
           AND employment_status = 'active'
           AND extract(month from birth_date) = $2
           AND extract(day from birth_date) >= $3
         ORDER BY extract(day from birth_date), first_name, last_name
         LIMIT 8
        """,
        actor.legal_entity_id,
        today.month,
        today.day,
    )
    anniversaries = await db.fetch(
        """
        SELECT id,
               first_name,
               last_name,
               hire_date,
               extract(day from hire_date)::int AS day_of_month,
               extract(year from age($2::date, hire_date))::int AS years_completed
          FROM employees
         WHERE legal_entity_id = $1
           AND employment_status = 'active'
           AND hire_date < $2
           AND extract(month from hire_date) = $3
           AND extract(day from hire_date) >= $4
         ORDER BY extract(day from hire_date), first_name, last_name
         LIMIT 8
        """,
        actor.legal_entity_id,
        today,
        today.month,
        today.day,
    )
    return {
        'month': today.month,
        'birthdays': [
            {
                'id': str(row['id']),
                'first_name': row['first_name'],
                'last_name': row['last_name'],
                'date': row['birth_date'].isoformat() if row['birth_date'] else None,
                'day_of_month': row['day_of_month'],
            }
            for row in birthdays
        ],
        'anniversaries': [
            {
                'id': str(row['id']),
                'first_name': row['first_name'],
                'last_name': row['last_name'],
                'date': row['hire_date'].isoformat() if row['hire_date'] else None,
                'day_of_month': row['day_of_month'],
                'years_completed': int(row['years_completed'] or 0),
            }
            for row in anniversaries
        ],
    }


@UX_ROUTER.get('/team-chat-config')
async def team_chat_config(request: Request) -> dict[str, object]:
    actor = await require_actor(request)
    db = get_db_from_request(request)
    chat_enabled = await db.fetchval(
        """
        SELECT coalesce(chat_enabled, true)
          FROM tenant_subscriptions
         WHERE legal_entity_id = $1
        """,
        actor.legal_entity_id,
    )
    if chat_enabled is False:
        return {
            'linked': False,
            'mattermost_user_id': None,
            'mattermost_username': None,
            'server_base_url': None,
            'default_team': None,
            'preferred_channel': None,
            'channel_url': None,
        }
    integration = await _fetch_mattermost_config(db, actor.legal_entity_id)
    account = await db.fetchrow(
        """
        SELECT mattermost_user_id, mattermost_username
          FROM employee_chat_accounts
         WHERE employee_id = $1
        """,
        actor.employee_id,
    )
    if account is None and integration is not None and integration.enabled and integration.bot_access_token:
        try:
            from .mattermost_integration import ensure_mattermost_account_for_employee
            await ensure_mattermost_account_for_employee(db, actor.employee_id)
            account = await db.fetchrow(
                """
                SELECT mattermost_user_id, mattermost_username
                  FROM employee_chat_accounts
                 WHERE employee_id = $1
                """,
                actor.employee_id,
            )
        except Exception:
            pass
    preferred_channel = None
    channel_url = None
    public_mm = (settings.mattermost_public_url or '').rstrip('/')
    if integration is not None:
        preferred_channel = integration.general_channel or integration.hr_channel
        base_for_links = public_mm or (str(integration.server_base_url).rstrip('/') if integration.server_base_url else '')
        if base_for_links and integration.default_team and preferred_channel:
            channel_url = f"{base_for_links}/{integration.default_team}/channels/{preferred_channel}"
    if channel_url is None and integration is not None:
        fallback_base = public_mm or (str(integration.server_base_url).rstrip('/') if integration.server_base_url else '')
        if fallback_base:
            channel_url = fallback_base
    return {
        'linked': account is not None,
        'mattermost_user_id': account['mattermost_user_id'] if account else None,
        'mattermost_username': account['mattermost_username'] if account else None,
        'server_base_url': integration.server_base_url if integration else None,
        'default_team': integration.default_team if integration else None,
        'preferred_channel': preferred_channel,
        'channel_url': channel_url,
    }


@UX_ROUTER.get('/leave-self-service')
async def leave_self_service(request: Request) -> dict[str, object]:
    actor = await require_actor(request)
    db = get_db_from_request(request)
    employee = await db.fetchrow(
        """
        SELECT id, hire_date, first_name, last_name
          FROM employees
         WHERE id = $1
        """,
        actor.employee_id,
    )
    if employee is None:
        raise HTTPException(status_code=404, detail='Employee not found')
    today = datetime.now().date()
    year_start = date(today.year, 1, 1)
    accrual_start = max(employee['hire_date'], year_start)
    months_worked = _completed_months(accrual_start, today)
    policy = await _leave_policy_settings(db, actor.legal_entity_id)
    paid_allowance_days = Decimal(str(policy['paid_leave_allowance_days']))
    unpaid_allowance_days = Decimal(str(policy['unpaid_leave_allowance_days']))
    eligibility_months = int(policy['eligibility_months'] or 0)
    eligible_for_paid_leave = _completed_months(employee['hire_date'], today) >= eligibility_months
    monthly_accrual_rate = (paid_allowance_days / Decimal('12')) if paid_allowance_days else Decimal('0')
    statutory_earned_days = min(Decimal(months_worked) * monthly_accrual_rate, paid_allowance_days) if eligible_for_paid_leave else Decimal('0')

    leave_types = await db.fetch(
        """
        SELECT id, code, name_en, name_ka, is_paid, annual_allowance_days
          FROM leave_types
         WHERE legal_entity_id = $1
           AND is_active = true
         ORDER BY is_paid DESC, annual_allowance_days DESC, name_en
        """,
        actor.legal_entity_id,
    )
    visible_leave_types = [row for row in leave_types if _leave_type_visible_for_policy(row['code'], policy)]
    primary_leave_type = next((row for row in visible_leave_types if row['is_paid']), visible_leave_types[0] if visible_leave_types else None)

    opening_days = Decimal('0.0')
    adjusted_days = Decimal('0.0')
    used_days = Decimal('0.0')
    system_earned_days = Decimal('0.0')
    if primary_leave_type is not None:
        balance_row = await db.fetchrow(
            """
            SELECT opening_days, earned_days, used_days, adjusted_days
              FROM leave_balances
             WHERE employee_id = $1
               AND leave_type_id = $2
               AND balance_year = $3
            """,
            actor.employee_id,
            primary_leave_type['id'],
            today.year,
        )
        if balance_row is not None:
            opening_days = balance_row['opening_days']
            adjusted_days = balance_row['adjusted_days']
            system_earned_days = balance_row['earned_days']
            used_days = balance_row['used_days']
        used_query = await db.fetchval(
            """
            SELECT coalesce(sum(requested_days), 0)
              FROM leave_requests
             WHERE employee_id = $1
               AND leave_type_id = $2
               AND status = 'approved'
               AND start_date >= $3
            """,
            actor.employee_id,
            primary_leave_type['id'],
            year_start,
        )
        used_days = max(used_days, used_query or Decimal('0.0'))

    earned_days = max(system_earned_days, statutory_earned_days) if eligible_for_paid_leave else Decimal('0.0')
    available_days = max(opening_days + adjusted_days + earned_days - used_days, Decimal('0.0'))

    unpaid_leave_type = next((row for row in visible_leave_types if not row['is_paid']), None)
    unpaid_used_days = Decimal('0.0')
    if unpaid_leave_type is not None:
        unpaid_used_query = await db.fetchval(
            """
            SELECT coalesce(sum(requested_days), 0)
              FROM leave_requests
             WHERE employee_id = $1
               AND leave_type_id = $2
               AND status = 'approved'
               AND start_date >= $3
            """,
            actor.employee_id,
            unpaid_leave_type['id'],
            year_start,
        )
        unpaid_used_days = unpaid_used_query or Decimal('0.0')
    unpaid_available_days = max(unpaid_allowance_days - unpaid_used_days, Decimal('0.0'))

    requests = await db.fetch(
        """
        SELECT lr.id,
               lr.start_date,
               lr.end_date,
               lr.requested_days,
               lr.status::text AS status,
               lr.reason,
               coalesce(lt.name_ka, lt.name_en) AS leave_type_name
          FROM leave_requests lr
          JOIN leave_types lt ON lt.id = lr.leave_type_id
         WHERE lr.employee_id = $1
         ORDER BY lr.created_at DESC
         LIMIT 12
        """,
        actor.employee_id,
    )
    return {
        'employee_id': str(actor.employee_id),
        'employee_name': f"{employee['first_name']} {employee['last_name']}",
        'hire_date': employee['hire_date'].isoformat(),
        'current_year': today.year,
        'months_worked': months_worked,
        'eligible_for_paid_leave': eligible_for_paid_leave,
        'eligibility_months': eligibility_months,
        'statutory_earned_days': _to_float(statutory_earned_days),
        'earned_days': _to_float(earned_days),
        'used_days': _to_float(used_days),
        'available_days': _to_float(available_days),
        'opening_days': _to_float(opening_days),
        'adjusted_days': _to_float(adjusted_days),
        'unpaid_available_days': _to_float(unpaid_available_days),
        'policy': {
            'paid_leave_allowance_days': int(policy['paid_leave_allowance_days']),
            'unpaid_leave_allowance_days': int(policy['unpaid_leave_allowance_days']),
            'eligibility_months': eligibility_months,
            'enable_birthday_off': bool(policy['enable_birthday_off']),
            'enable_day_off': bool(policy['enable_day_off']),
        },
        'primary_leave_type': (
            {
                'id': str(primary_leave_type['id']),
                'code': primary_leave_type['code'],
                'name_en': primary_leave_type['name_en'],
                'name_ka': primary_leave_type['name_ka'],
                'annual_allowance_days': _to_float(primary_leave_type['annual_allowance_days'] or paid_allowance_days),
            }
            if primary_leave_type
            else None
        ),
        'leave_types': [
            {
                'id': str(row['id']),
                'code': row['code'],
                'name_en': row['name_en'],
                'name_ka': row['name_ka'],
                'is_paid': row['is_paid'],
                'annual_allowance_days': _to_float(
                    row['annual_allowance_days']
                    if row['annual_allowance_days'] is not None
                    else (paid_allowance_days if row['is_paid'] else unpaid_allowance_days)
                ),
            }
            for row in visible_leave_types
        ],
        'requests': [
            {
                'id': str(row['id']),
                'start_date': row['start_date'].isoformat(),
                'end_date': row['end_date'].isoformat(),
                'requested_days': _to_float(row['requested_days']),
                'status': row['status'],
                'reason': row['reason'],
                'leave_type_name': row['leave_type_name'],
            }
            for row in requests
        ],
    }

@UX_ROUTER.get('/ats-board')
async def ats_board(request: Request) -> dict[str, object]:
    actor = await require_actor(request)
    if not actor.has('recruitment.read') and not actor.has('recruitment.manage'):
        raise HTTPException(status_code=403, detail='ATS დაფისთვის საჭიროა recruitment.read უფლება')
    db = get_db_from_request(request)
    configured_stages = await db.fetch(
        """
        SELECT upper(code::text) AS code, name_en, name_ka, sort_order
          FROM candidate_pipeline_stages
         WHERE legal_entity_id = $1
           AND upper(code::text) IN ('APPLIED', 'INTERVIEW', 'OFFER', 'HIRED')
         ORDER BY sort_order
        """,
        actor.legal_entity_id,
    )
    default_stage_map = {
        'APPLIED': {'name_en': 'Applied', 'name_ka': 'აპლიკაციები'},
        'INTERVIEW': {'name_en': 'Interview', 'name_ka': 'ინტერვიუ'},
        'OFFER': {'name_en': 'Offer', 'name_ka': 'შეთავაზება'},
        'HIRED': {'name_en': 'Hired', 'name_ka': 'დაქირავებული'},
    }
    columns: list[dict[str, object]] = []
    seen_codes = set()
    for row in configured_stages:
        seen_codes.add(row['code'])
        columns.append({'code': row['code'], 'name_en': row['name_en'], 'name_ka': row['name_ka']})
    for code in ('APPLIED', 'INTERVIEW', 'OFFER', 'HIRED'):
        if code not in seen_codes:
            columns.append({'code': code, **default_stage_map[code]})

    rows = await db.fetch(
        """
        SELECT ca.id,
               upper(cps.code::text) AS stage_code,
               c.first_name,
               c.last_name,
               c.email,
               c.phone,
               c.city,
               jp.posting_code,
               coalesce(jp.title_ka, jp.title_en) AS job_title,
               coalesce(d.name_ka, d.name_en) AS department_name,
               ca.applied_at,
               coalesce(owner.first_name || ' ' || owner.last_name, '') AS owner_name,
               jp.salary_min,
               jp.salary_max,
               ca.compatibility_score,
               ca.compatibility_summary,
               ca.interview_scheduled_at,
               ca.interview_duration_minutes,
               ca.interview_notes,
               ca.interview_calendar_url
          FROM candidate_applications ca
          JOIN candidates c ON c.id = ca.candidate_id
          JOIN job_postings jp ON jp.id = ca.job_posting_id
          JOIN candidate_pipeline_stages cps ON cps.id = ca.current_stage_id
          LEFT JOIN departments d ON d.id = jp.department_id
          LEFT JOIN employees owner ON owner.id = ca.owner_employee_id
         WHERE jp.legal_entity_id = $1
           AND ca.application_status <> 'rejected'
         ORDER BY ca.applied_at DESC
        """,
        actor.legal_entity_id,
    )
    cards = {column['code']: [] for column in columns}
    for row in rows:
        bucket = 'APPLIED' if row['stage_code'] in {'APPLIED', 'SCREEN'} else row['stage_code']
        if bucket not in cards:
            continue
        cards[bucket].append(
            {
                'id': str(row['id']),
                'stage_code': bucket,
                'actual_stage_code': row['stage_code'],
                'first_name': row['first_name'],
                'last_name': row['last_name'],
                'email': row['email'],
                'phone': row['phone'],
                'city': row['city'],
                'posting_code': row['posting_code'],
                'job_title': row['job_title'],
                'department_name': row['department_name'],
                'applied_at': row['applied_at'].isoformat() if row['applied_at'] else None,
                'owner_name': row['owner_name'],
                'salary_min': float(row['salary_min']) if row['salary_min'] is not None else None,
                'salary_max': float(row['salary_max']) if row['salary_max'] is not None else None,
                'compatibility_score': float(row['compatibility_score']) if row['compatibility_score'] is not None else None,
                'compatibility_summary': row['compatibility_summary'],
                'interview_scheduled_at': row['interview_scheduled_at'].isoformat() if row['interview_scheduled_at'] else None,
                'interview_duration_minutes': int(row['interview_duration_minutes']) if row['interview_duration_minutes'] is not None else None,
                'interview_notes': row['interview_notes'],
                'interview_calendar_url': row['interview_calendar_url'],
            }
        )
    return {'legal_entity_id': str(actor.legal_entity_id), 'columns': columns, 'cards': cards}


@UX_ROUTER.get('/attendance-hub')
async def attendance_hub(
    request: Request,
    month_start: date | None = None,
    department_id: UUID | None = None,
) -> dict[str, object]:
    actor = await require_actor(request)
    if not _actor_can_open_attendance_hub(actor):
        raise HTTPException(status_code=403, detail='Attendance hub access is not enabled for this account')

    db = get_db_from_request(request)
    anchor_date = (month_start or _georgia_today()).replace(day=1)
    start_date, end_date = _month_bounds(anchor_date)
    return await _attendance_dataset(
        db,
        actor,
        start_date=start_date,
        end_date=end_date,
        department_id=department_id,
    )


@UX_ROUTER.get('/attendance-personal-report')
async def attendance_personal_report(
    request: Request,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, object]:
    actor = await require_actor(request)
    if not _actor_can_open_attendance_hub(actor):
        raise HTTPException(status_code=403, detail='Attendance hub access is not enabled for this account')

    db = get_db_from_request(request)
    resolved_start, resolved_end = _normalize_attendance_range(start_date, end_date)
    employee_rows = await db.fetch(
        """
        SELECT e.id,
               e.employee_number,
               e.first_name,
               e.last_name,
               e.department_id,
               coalesce(d.name_ka, d.name_en) AS department_name,
               coalesce(jr.title_ka, jr.title_en) AS job_title
          FROM employees e
          LEFT JOIN departments d ON d.id = e.department_id
          LEFT JOIN job_roles jr ON jr.id = e.job_role_id
         WHERE e.id = $1
           AND e.deleted_at IS NULL
        """,
        actor.employee_id,
    )
    employee_list = [dict(row) for row in employee_rows]
    dataset = await _attendance_dataset(
        db,
        actor,
        start_date=resolved_start,
        end_date=resolved_end,
        department_id=actor.department_id,
        employee_rows_override=employee_list,
    )
    return {
        'start_date': resolved_start.isoformat(),
        'end_date': resolved_end.isoformat(),
        'summary': dataset['personal_summary'],
        'days': dataset['personal_days'],
    }


@UX_ROUTER.get('/attendance-personal-report/export')
async def export_personal_attendance_report(
    request: Request,
    start_date: date | None = None,
    end_date: date | None = None,
    format: str = 'csv',
) -> Response:
    actor = await require_actor(request)
    if not _actor_can_open_attendance_hub(actor):
        raise HTTPException(status_code=403, detail='Attendance hub access is not enabled for this account')

    resolved_start, resolved_end = _normalize_attendance_range(start_date, end_date)
    report = await attendance_personal_report(request, resolved_start, resolved_end)
    headers = ['Date', 'Status', 'Shift', 'Check In', 'Check Out', 'Hours', 'Late Minutes', 'Overtime Minutes', 'Exception']
    rows = [
        [
            day['date'],
            day['status'],
            day['shift_label'] or '',
            day['check_in_label'] or '',
            day['check_out_label'] or '',
            f"{round((day['total_minutes'] or 0) / 60, 2):.2f}",
            str(day['late_minutes']),
            str(day['overtime_minutes']),
            day.get('exception_label') or '',
        ]
        for day in report['days']
    ]
    return _attendance_export_response(
        sheet_name='Personal Attendance',
        file_stem=f"personal_attendance_{resolved_start.isoformat()}_{resolved_end.isoformat()}",
        headers=headers,
        rows=rows,
        export_format=format,
    )


@UX_ROUTER.get('/attendance-team-report/export')
async def export_team_attendance_report(
    request: Request,
    start_date: date | None = None,
    end_date: date | None = None,
    department_id: UUID | None = None,
    format: str = 'csv',
) -> Response:
    actor = await require_actor(request)
    if not _actor_can_open_attendance_hub(actor):
        raise HTTPException(status_code=403, detail='Attendance hub access is not enabled for this account')

    db = get_db_from_request(request)
    resolved_start, resolved_end = _normalize_attendance_range(start_date, end_date)
    dataset = await _attendance_dataset(
        db,
        actor,
        start_date=resolved_start,
        end_date=resolved_end,
        department_id=department_id,
    )
    headers = ['Employee', 'Employee Number', 'Department', 'Job Title', 'Hours', 'Late Days', 'Overtime Minutes', 'Present', 'Absent', 'Leave', 'Sick', 'Exceptions']
    rows = [
        [
            report['employee_name'],
            report['employee_number'],
            report['department_name'] or '',
            report['job_title'] or '',
            f"{round((report['total_minutes'] or 0) / 60, 2):.2f}",
            str(report['late_days']),
            str(report['overtime_minutes']),
            str(report['present_days']),
            str(report['absent_days']),
            str(report['leave_days']),
            str(report['sick_days']),
            str(report.get('exception_days') or 0),
        ]
        for report in dataset['reports']
    ]
    department_name = dataset['selected_department_name'] or 'team'
    safe_department = ''.join(ch.lower() if ch.isalnum() else '_' for ch in department_name).strip('_') or 'team'
    return _attendance_export_response(
        sheet_name='Team Attendance',
        file_stem=f"{safe_department}_attendance_{resolved_start.isoformat()}_{resolved_end.isoformat()}",
        headers=headers,
        rows=rows,
        export_format=format,
    )


@UX_ROUTER.get('/shift-planner')
async def shift_planner(
    request: Request,
    month_start: date | None = None,
    department_id: UUID | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 8,
) -> dict[str, object]:
    actor = await require_actor(request)
    if not actor.has('attendance.review') and not actor.has('employee.manage') and not actor.managed_department_ids:
        raise HTTPException(status_code=403, detail='ცვლის დაგეგმვა ხელმისაწვდომია მხოლოდ ადმინისტრატორისთვის ან დეპარტამენტის მენეჯერისთვის')
    db = get_db_from_request(request)
    page = max(page, 1)
    page_size = min(max(page_size, 1), 20)
    anchor_date = (month_start or date.today()).replace(day=1)
    start_date, end_date = _month_bounds(anchor_date)
    day_count = (end_date - start_date).days + 1
    accessible_departments = await _attendance_accessible_departments(db, actor)
    selected_department_id = _resolve_attendance_department(actor, accessible_departments, department_id)
    search_query = f'%{search.strip()}%' if search else None

    total_count = await db.fetchval(
        """
        SELECT count(*)
          FROM employees e
         WHERE e.legal_entity_id = $1
           AND e.employment_status = 'active'
           AND e.deleted_at IS NULL
           AND ($2::uuid IS NULL OR e.department_id = $2)
           AND ($3::text IS NULL OR e.first_name ILIKE $3 OR e.last_name ILIKE $3 OR e.employee_number ILIKE $3)
        """,
        actor.legal_entity_id,
        selected_department_id,
        search_query,
    )
    employee_rows = await db.fetch(
        """
        SELECT e.id,
               e.employee_number,
               e.first_name,
               e.last_name,
               e.department_id,
               coalesce(d.name_ka, d.name_en) AS department_name,
               coalesce(jr.title_ka, jr.title_en) AS job_title
          FROM employees e
          LEFT JOIN departments d ON d.id = e.department_id
          LEFT JOIN job_roles jr ON jr.id = e.job_role_id
         WHERE e.legal_entity_id = $1
           AND e.employment_status = 'active'
           AND e.deleted_at IS NULL
           AND ($2::uuid IS NULL OR e.department_id = $2)
           AND ($3::text IS NULL OR e.first_name ILIKE $3 OR e.last_name ILIKE $3 OR e.employee_number ILIKE $3)
         ORDER BY e.first_name, e.last_name
         LIMIT $4 OFFSET $5
        """,
        actor.legal_entity_id,
        selected_department_id,
        search_query,
        page_size,
        (page - 1) * page_size,
    )
    employee_ids = [row['id'] for row in employee_rows]
    pattern_rows = await db.fetch(
        """
        SELECT sp.id,
               sp.code,
               sp.name,
               sp.pattern_type::text AS pattern_type,
               sp.cycle_length_days,
               sp.standard_weekly_hours,
               coalesce(
                   json_agg(
                       json_build_object(
                           'day_index', sps.day_index,
                           'start_time', to_char(sps.start_time, 'HH24:MI'),
                           'planned_minutes', sps.planned_minutes,
                           'break_minutes', sps.break_minutes,
                           'crosses_midnight', sps.crosses_midnight,
                           'label', sps.label
                       )
                       ORDER BY sps.day_index
                   ) FILTER (WHERE sps.id IS NOT NULL),
                   '[]'::json
               ) AS segments
          FROM shift_patterns sp
          LEFT JOIN shift_pattern_segments sps ON sps.shift_pattern_id = sp.id
         WHERE sp.legal_entity_id = $1
           AND sp.is_active = true
         GROUP BY sp.id
         ORDER BY sp.name
        """,
        actor.legal_entity_id,
    )
    patterns = []
    pattern_map: dict[str, dict[str, object]] = {}
    for row in pattern_rows:
        segments = row['segments'] or []
        if isinstance(segments, str):
            segments = json.loads(segments)
        pattern = {
            'id': str(row['id']),
            'code': row['code'],
            'name': row['name'],
            'pattern_type': row['pattern_type'],
            'cycle_length_days': row['cycle_length_days'],
            'standard_weekly_hours': float(row['standard_weekly_hours']),
            'segments': segments,
        }
        pattern_map[str(row['id'])] = pattern
        if not _is_custom_shift_code(row['code']):
            patterns.append(pattern)

    assignment_rows = []
    if employee_ids:
        assignment_rows = await db.fetch(
            """
            SELECT a.id,
                   a.employee_id,
                   a.shift_pattern_id,
                   a.effective_from,
                   a.effective_to,
                   a.rotation_anchor_date,
                   a.created_at
              FROM assigned_shifts a
             WHERE a.employee_id = ANY($1::uuid[])
               AND a.effective_from <= $3
               AND coalesce(a.effective_to, $3) >= $2
             ORDER BY a.created_at DESC, a.effective_from DESC
            """,
            employee_ids,
            start_date,
            end_date,
        )

    def resolve_segment(pattern: dict[str, object], assignment_row: dict[str, object], shift_date_value: date) -> dict[str, object] | None:
        segments = pattern.get('segments', [])
        if not segments:
            return None
        if pattern['pattern_type'] == 'fixed_weekly':
            target_day_index = shift_date_value.isoweekday()
        else:
            anchor = assignment_row['rotation_anchor_date'] or assignment_row['effective_from']
            delta_days = (shift_date_value - anchor).days
            target_day_index = (delta_days % int(pattern['cycle_length_days'])) + 1
        for segment in segments:
            if int(segment['day_index']) == target_day_index:
                return segment
        return None

    assignments: list[dict[str, object]] = []
    for employee_row in employee_rows:
        employee_id = employee_row['id']
        overlapping = [dict(row) for row in assignment_rows if row['employee_id'] == employee_id]
        for offset in range(day_count):
            shift_date_value = start_date + timedelta(days=offset)
            candidates = []
            for row in overlapping:
                effective_to = row['effective_to'] or shift_date_value
                if row['effective_from'] <= shift_date_value <= effective_to:
                    span = (effective_to - row['effective_from']).days if row['effective_to'] else 9999
                    candidates.append((span, row['created_at'], row))
            if not candidates:
                continue
            candidates.sort(key=lambda item: (item[0], item[1]), reverse=False)
            selected = candidates[0][2]
            pattern = pattern_map.get(str(selected['shift_pattern_id']))
            if pattern is None:
                continue
            segment = resolve_segment(pattern, selected, shift_date_value)
            if segment is None:
                continue
            assignments.append(
                {
                    'assignment_id': str(selected['id']),
                    'employee_id': str(employee_id),
                    'shift_date': shift_date_value.isoformat(),
                    'shift_pattern_id': str(selected['shift_pattern_id']),
                    'pattern_name': pattern['name'],
                    'pattern_code': pattern['code'],
                    'planned_minutes': int(segment['planned_minutes']),
                    'start_time': segment['start_time'],
                    'end_time': _segment_end_time(segment['start_time'], int(segment['planned_minutes'])),
                    'break_minutes': int(segment['break_minutes']),
                    'crosses_midnight': bool(segment['crosses_midnight']),
                    'label': segment['label'] or pattern['name'],
                    'is_custom': _is_custom_shift_code(pattern['code']),
                }
            )

    weekly_minutes_by_employee: dict[str, dict[str, int]] = {}
    for item in assignments:
        employee_minutes = weekly_minutes_by_employee.setdefault(item['employee_id'], {})
        week_key = _week_bucket_key(date.fromisoformat(str(item['shift_date'])))
        employee_minutes[week_key] = employee_minutes.get(week_key, 0) + int(item['planned_minutes'])

    employees = []
    for row in employee_rows:
        employee_id = str(row['id'])
        weekly_minutes_map = weekly_minutes_by_employee.get(employee_id, {})
        dept_id = row['department_id']
        employees.append(
            {
                'id': employee_id,
                'employee_number': row['employee_number'],
                'first_name': row['first_name'],
                'last_name': row['last_name'],
                'department_name': row['department_name'],
                'job_title': row['job_title'],
                'weekly_minutes': max(weekly_minutes_map.values(), default=0),
                'weekly_minutes_map': weekly_minutes_map,
                'can_edit': can_edit_shift_schedule(actor, dept_id),
            }
        )

    days = []
    for offset in range(day_count):
        value = start_date + timedelta(days=offset)
        days.append(
            {
                'date': value.isoformat(),
                'label': ATTENDANCE_WEEKDAY_LABELS[value.isoweekday()],
                'day_index': value.isoweekday(),
            }
        )

    return {
        'month_start': start_date.isoformat(),
        'month_end': end_date.isoformat(),
        'calendar_title': _calendar_title(start_date),
        'selected_department_id': str(selected_department_id) if selected_department_id else None,
        'days': days,
        'patterns': patterns,
        'employees': employees,
        'assignments': assignments,
        'total': int(total_count or 0),
        'page': page,
        'page_size': page_size,
        'page_count': max((int(total_count or 0) + page_size - 1) // page_size, 1),
        'user_can_edit_shifts': bool(selected_department_id and can_edit_shift_schedule(actor, selected_department_id)),
    }


@UX_ROUTER.post('/shift-planner/assignments')
async def upsert_shift_assignment(request: Request, payload: ShiftAssignmentUpsert) -> dict[str, object]:
    actor = await require_actor(request)
    if not actor.has('attendance.review') and not actor.has('employee.manage') and not actor.managed_department_ids:
        raise HTTPException(status_code=403, detail='????? ???????? ?????????????? ?????? ??????????????????? ?? ????????????? ?????????????')
    db = get_db_from_request(request)
    emp_row = await db.fetchrow(
        'SELECT legal_entity_id, department_id FROM employees WHERE id = $1',
        payload.employee_id,
    )
    pattern_entity_id = await db.fetchval(
        'SELECT legal_entity_id FROM shift_patterns WHERE id = $1',
        payload.shift_pattern_id,
    ) if payload.shift_pattern_id else None
    if emp_row is None:
        raise HTTPException(status_code=404, detail='???????????? ??? ????????')
    if emp_row['legal_entity_id'] != actor.legal_entity_id:
        raise HTTPException(status_code=403, detail='???? ???????? ???????? ????? ???????? ??????????')
    if not can_edit_shift_schedule(actor, emp_row['department_id']):
        raise HTTPException(status_code=403, detail='????? ??????????? ? ?????? ?????????????? ?? ????????????? ????????????')

    start_value = _parse_shift_time(payload.start_time, 'start_time')
    end_value = _parse_shift_time(payload.end_time, 'end_time')
    using_manual_times = start_value is not None or end_value is not None
    if using_manual_times and (start_value is None or end_value is None):
        raise HTTPException(status_code=422, detail='Both start_time and end_time are required for a custom shift')

    if using_manual_times:
        shift_pattern_id = await _create_custom_shift_pattern(
            db,
            legal_entity_id=actor.legal_entity_id,
            employee_id=payload.employee_id,
            shift_date=payload.shift_date,
            start_value=start_value,
            end_value=end_value,
        )
    else:
        if payload.shift_pattern_id is None:
            raise HTTPException(status_code=422, detail='Select a shift template or enter manual start/end times')
        if pattern_entity_id is None:
            raise HTTPException(status_code=404, detail='????? ??????? ??? ????????')
        if pattern_entity_id != actor.legal_entity_id:
            raise HTTPException(status_code=403, detail='???? ???????? ???????? ????? ???????? ??????????')
        shift_pattern_id = payload.shift_pattern_id

    await _cleanup_single_day_shift_assignments(db, payload.employee_id, payload.shift_date)
    await db.execute(
        """
        INSERT INTO assigned_shifts (
            shift_pattern_id, employee_id, effective_from, effective_to, rotation_anchor_date, created_by_employee_id
        )
        VALUES ($1, $2, $3, $3, $3, $4)
        """,
        shift_pattern_id,
        payload.employee_id,
        payload.shift_date,
        actor.employee_id,
    )
    week_minutes = await _week_planned_minutes_fixed_weekly(db, payload.employee_id, payload.shift_date)
    return {
        'status': 'assigned',
        'week_planned_minutes': week_minutes,
        'over_40h_warning': week_minutes > 40 * 60,
        'used_custom_times': using_manual_times,
    }

@UX_ROUTER.delete('/shift-planner/assignments/{employee_id}/{shift_date}')
async def clear_shift_assignment(request: Request, employee_id: UUID, shift_date: date) -> dict[str, str]:
    actor = await require_actor(request)
    if not actor.has('attendance.review') and not actor.has('employee.manage') and not actor.managed_department_ids:
        raise HTTPException(status_code=403, detail='????? ???????? ?????????????? ?????? ??????????????????? ?? ????????????? ?????????????')
    db = get_db_from_request(request)
    emp = await db.fetchrow('SELECT legal_entity_id, department_id FROM employees WHERE id = $1', employee_id)
    if emp is None:
        raise HTTPException(status_code=404, detail='???????????? ??? ????????')
    if emp['legal_entity_id'] != actor.legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='???????????? ???? ???????? ??????? ????????')
    if not can_edit_shift_schedule(actor, emp['department_id']):
        raise HTTPException(status_code=403, detail='????? ??????????? ? ?????? ?????????????? ?? ????????????? ????????????')
    await _cleanup_single_day_shift_assignments(db, employee_id, shift_date)
    return {'status': 'cleared'}

@UX_ROUTER.get('/live-monitoring')
async def live_monitoring(request: Request) -> dict[str, object]:
    actor = await require_actor(request)
    if not actor.has('employee.manage'):
        raise HTTPException(status_code=403, detail='მონიტორინგის ხედისთვის საჭიროა employee.manage უფლება')
    db = get_db_from_request(request)
    device_rows = await db.fetch(
        """
        SELECT id,
               device_name,
               brand::text AS brand,
               host,
               port,
               last_seen_at,
               transport::text AS transport,
               CASE
                   WHEN transport::text IN ('sdk_bridge', 'raw_socket', 'adms', 'adms_push')
                        AND last_seen_at >= now() - interval '10 minutes' THEN 'online'
                   WHEN transport::text IN ('sdk_bridge', 'raw_socket', 'adms', 'adms_push')
                        THEN 'offline'
                   ELSE 'unknown'
               END AS connectivity
          FROM device_registry
         WHERE legal_entity_id = $1
         ORDER BY device_name
        """,
        actor.legal_entity_id,
    )
    node_rows = await db.fetch(
        """
        SELECT dn.node_code,
               dn.node_role,
               dn.base_url,
               dn.region,
               dn.last_heartbeat_at,
               dn.metadata,
               sh.service_name,
               sh.status,
               sh.details
          FROM deployment_nodes dn
          LEFT JOIN service_heartbeats sh ON sh.node_id = dn.id
         ORDER BY dn.node_code, sh.service_name
        """
    )
    return {
        'devices': [dict(row) for row in device_rows],
        'nodes': [dict(row) for row in node_rows],
    }


@UX_ROUTER.get('/shift-builder')
async def shift_builder(request: Request) -> dict[str, object]:
    actor = await require_actor(request)
    if not bool({'ADMIN', 'TENANT_ADMIN'} & actor.role_codes):
        raise HTTPException(status_code=403, detail='ცვლის შაბლონები ხელმისაწვდომია მხოლოდ სუპერ ადმინისტრატორისთვის')
    db = get_db_from_request(request)
    pattern_rows = await db.fetch(
        """
        SELECT sp.id,
               sp.code,
               sp.name,
               sp.pattern_type::text AS pattern_type,
               sp.cycle_length_days,
               sp.timezone,
               sp.standard_weekly_hours,
               sp.early_check_in_grace_minutes,
               sp.late_check_out_grace_minutes,
               sp.grace_period_minutes,
               count(DISTINCT a.id) AS assignment_count,
               coalesce(
                   json_agg(
                       json_build_object(
                           'day_index', sps.day_index,
                           'start_time', to_char(sps.start_time, 'HH24:MI'),
                           'planned_minutes', sps.planned_minutes,
                           'break_minutes', sps.break_minutes,
                           'crosses_midnight', sps.crosses_midnight,
                           'label', sps.label
                       )
                       ORDER BY sps.day_index
                   ) FILTER (WHERE sps.id IS NOT NULL),
                   '[]'::json
               ) AS segments
          FROM shift_patterns sp
          LEFT JOIN shift_pattern_segments sps ON sps.shift_pattern_id = sp.id
          LEFT JOIN assigned_shifts a ON a.shift_pattern_id = sp.id
         WHERE sp.legal_entity_id = $1
         GROUP BY sp.id
         ORDER BY sp.name
        """,
        actor.legal_entity_id,
    )
    patterns = []
    for row in pattern_rows:
        segments = row['segments'] or []
        if isinstance(segments, str):
            segments = json.loads(segments)
        patterns.append(
            {
                'id': str(row['id']),
                'code': row['code'],
                'name': row['name'],
                'pattern_type': row['pattern_type'],
                'cycle_length_days': row['cycle_length_days'],
                'timezone': row['timezone'],
                'standard_weekly_hours': _to_float(row['standard_weekly_hours']),
                'early_check_in_grace_minutes': int(row['early_check_in_grace_minutes']),
                'late_check_out_grace_minutes': int(row['late_check_out_grace_minutes']),
                'grace_period_minutes': int(row['grace_period_minutes'] or 0),
                'assignment_count': int(row['assignment_count'] or 0),
                'segments': [
                    {
                        **segment,
                        'end_time': _segment_end_time(segment['start_time'], int(segment['planned_minutes'])),
                    }
                    for segment in segments
                ],
            }
        )
    return {'patterns': patterns}


@UX_ROUTER.get('/web-punch-config')
async def web_punch_config(request: Request) -> dict[str, object]:
    actor = await require_actor(request)
    db = get_db_from_request(request)
    today = _georgia_today()
    config = await db.fetchrow(
        """
        SELECT allowed_web_punch_ips, geofence_latitude, geofence_longitude, geofence_radius_meters
          FROM entity_system_config
         WHERE legal_entity_id = $1
        """,
        actor.legal_entity_id,
    )
    recent_rows = await db.fetch(
        """
        SELECT *
          FROM (
                SELECT wpe.id::text AS id,
                       wpe.punch_ts,
                       wpe.direction::text AS direction,
                       wpe.source_ip,
                       wpe.latitude,
                       wpe.longitude,
                       wpe.location_name,
                       wpe.location_source,
                       wpe.is_location_suspicious,
                       wpe.location_risk_reason,
                       wpe.is_valid,
                       wpe.validation_reason,
                       'web'::text AS source_type,
                       'Web Punch'::text AS device_name
                  FROM web_punch_events wpe
                 WHERE wpe.employee_id = $1
                UNION ALL
                SELECT ral.id::text AS id,
                       ral.event_ts AS punch_ts,
                       ral.direction::text AS direction,
                       NULL::text AS source_ip,
                       NULL::numeric AS latitude,
                       NULL::numeric AS longitude,
                       dr.device_name AS location_name,
                       'device'::text AS location_source,
                       false AS is_location_suspicious,
                       NULL::text AS location_risk_reason,
                       true AS is_valid,
                       'device_card'::text AS validation_reason,
                       'device'::text AS source_type,
                       coalesce(dr.device_name, 'Card Reader') AS device_name
                  FROM raw_attendance_logs ral
                  LEFT JOIN device_registry dr ON dr.id = ral.device_id
                 WHERE ral.employee_id = $1
                   AND ral.direction IN ('in', 'out')
          ) punches
         ORDER BY punch_ts DESC
         LIMIT 12
        """,
        actor.employee_id,
    )
    today_rows = await db.fetch(
        """
        SELECT punch_ts, direction
          FROM (
                SELECT wpe.punch_ts,
                       wpe.direction::text AS direction
                  FROM web_punch_events wpe
                 WHERE wpe.employee_id = $1
                   AND wpe.is_valid = true
                   AND (wpe.punch_ts AT TIME ZONE 'Asia/Tbilisi')::date = $2
                   AND wpe.direction IN ('in', 'out')
                UNION ALL
                SELECT ral.event_ts AS punch_ts,
                       ral.direction::text AS direction
                  FROM raw_attendance_logs ral
                 WHERE ral.employee_id = $1
                   AND (ral.event_ts AT TIME ZONE 'Asia/Tbilisi')::date = $2
                   AND ral.direction IN ('in', 'out')
          ) punches
         ORDER BY punch_ts ASC
        """,
        actor.employee_id,
        today,
    )
    return {
        'config': {
            'allowed_web_punch_ips': (config['allowed_web_punch_ips'] if config else []) or [],
            'geofence_latitude': float(config['geofence_latitude']) if config and config['geofence_latitude'] is not None else None,
            'geofence_longitude': float(config['geofence_longitude']) if config and config['geofence_longitude'] is not None else None,
            'geofence_radius_meters': int(config['geofence_radius_meters']) if config and config['geofence_radius_meters'] is not None else None,
        },
        'status_summary': _summarize_web_punch_rows([dict(row) for row in today_rows]),
        'recent_punches': [
            {
                'id': str(row['id']),
                'punch_ts': row['punch_ts'].isoformat(),
                'direction': row['direction'],
                'source_ip': row['source_ip'],
                'latitude': float(row['latitude']) if row['latitude'] is not None else None,
                'longitude': float(row['longitude']) if row['longitude'] is not None else None,
                'location_name': row['location_name'],
                'location_source': row['location_source'],
                'is_location_suspicious': bool(row['is_location_suspicious']),
                'location_risk_reason': row['location_risk_reason'],
                'is_valid': row['is_valid'],
                'validation_reason': row['validation_reason'],
                'source_type': row['source_type'],
                'device_name': row['device_name'],
            }
            for row in recent_rows
        ],
    }


@UX_ROUTER.get('/attendance-overrides')
async def attendance_overrides(request: Request) -> list[dict[str, object]]:
    actor = await require_actor(request)
    if not actor.has('attendance.review'):
        raise HTTPException(status_code=403, detail='დასწრების კორექციის რიგისთვის საჭიროა attendance.review უფლება')
    db = get_db_from_request(request)
    rows = await db.fetch(
        """
        SELECT arf.id,
               arf.employee_id,
               e.employee_number,
               e.first_name,
               e.last_name,
               arf.session_id,
               arf.work_date,
               arf.flag_type,
               arf.severity,
               arf.details,
               aws.check_in_ts,
               aws.check_out_ts,
               aws.review_status::text AS review_status
          FROM attendance_review_flags arf
          JOIN employees e ON e.id = arf.employee_id
          LEFT JOIN attendance_work_sessions aws ON aws.id = arf.session_id
         WHERE e.legal_entity_id = $1
           AND arf.resolved_at IS NULL
         ORDER BY arf.raised_at DESC
         LIMIT 60
        """,
        actor.legal_entity_id,
    )
    return [
        {
            **dict(row),
            'id': str(row['id']),
            'employee_id': str(row['employee_id']),
            'session_id': str(row['session_id']) if row['session_id'] else None,
            'check_in_ts': row['check_in_ts'].isoformat() if row['check_in_ts'] else None,
            'check_out_ts': row['check_out_ts'].isoformat() if row['check_out_ts'] else None,
        }
        for row in rows
    ]


@UX_ROUTER.get('/vacancies')
async def vacancies_overview(request: Request) -> dict[str, object]:
    actor = await require_actor(request)
    if not actor.has('recruitment.read') and not actor.has('recruitment.manage'):
        raise HTTPException(status_code=403, detail='ვაკანსიების სამართავად საჭიროა recruitment.read უფლება')
    db = get_db_from_request(request)
    rows = await db.fetch(
        """
        SELECT jp.id,
               jp.posting_code,
               jp.title_en,
               jp.title_ka,
               jp.description,
               jp.public_description,
               jp.employment_type,
               jp.status::text AS status,
               jp.open_positions,
               jp.location_text,
               jp.public_slug,
               jp.external_form_url,
               jp.is_public,
               jp.application_form_schema,
               jp.salary_min,
               jp.salary_max,
               jp.closes_at,
               coalesce(d.name_ka, d.name_en) AS department_name,
               coalesce(jr.title_ka, jr.title_en) AS job_role_name,
               count(ca.id) AS application_count
          FROM job_postings jp
          LEFT JOIN departments d ON d.id = jp.department_id
          LEFT JOIN job_roles jr ON jr.id = jp.job_role_id
          LEFT JOIN candidate_applications ca ON ca.job_posting_id = jp.id
         WHERE jp.legal_entity_id = $1
         GROUP BY jp.id, d.name_ka, d.name_en, jr.title_ka, jr.title_en
         ORDER BY jp.created_at DESC
        """,
        actor.legal_entity_id,
    )
    departments = await db.fetch(
        'SELECT id, name_en, name_ka FROM departments WHERE legal_entity_id = $1 AND is_active = true ORDER BY name_en',
        actor.legal_entity_id,
    )
    job_roles = await db.fetch(
        'SELECT id, title_en, title_ka FROM job_roles WHERE legal_entity_id = $1 ORDER BY title_en',
        actor.legal_entity_id,
    )
    company_slug = await db.fetchval(
        """
        SELECT coalesce(td.subdomain, lower(regexp_replace(coalesce(le.trade_name, le.legal_name), '[^a-zA-Z0-9]+', '-', 'g')))
          FROM legal_entities le
          LEFT JOIN tenant_domains td ON td.legal_entity_id = le.id AND td.is_primary = true AND td.is_active = true
         WHERE le.id = $1
         LIMIT 1
        """,
        actor.legal_entity_id,
    )
    return {
        'items': [
            {
                'id': str(row['id']),
                'posting_code': row['posting_code'],
                'title_en': row['title_en'],
                'title_ka': row['title_ka'],
                'description': row['description'],
                'public_description': row['public_description'],
                'employment_type': row['employment_type'],
                'status': row['status'],
                'open_positions': int(row['open_positions']),
                'location_text': row['location_text'],
                'public_slug': row['public_slug'],
                'external_form_url': row['external_form_url'],
                'is_public': row['is_public'],
                'application_form_schema': row['application_form_schema'] or [],
                'salary_min': _to_float(row['salary_min']),
                'salary_max': _to_float(row['salary_max']),
                'closes_at': row['closes_at'].isoformat() if row['closes_at'] else None,
                'department_name': row['department_name'],
                'job_role_name': row['job_role_name'],
                'application_count': int(row['application_count'] or 0),
                'public_url': (
                    f'/careers/{company_slug}#{row["public_slug"]}'
                    if row['public_slug'] and company_slug
                    else (f'/public/vacancies/{row["public_slug"]}' if row['public_slug'] else None)
                ),
            }
            for row in rows
        ],
        'departments': [dict(row) for row in departments],
        'job_roles': [dict(row) for row in job_roles],
    }


@UX_ROUTER.get('/warehouse')
async def warehouse_view(request: Request) -> dict[str, object]:
    actor = await require_actor(request)
    if not actor.has('assets.read_all') and not actor.has('assets.manage'):
        raise HTTPException(status_code=403, detail='საწყობის ხედისთვის საჭიროა assets.read_all უფლება')
    db = get_db_from_request(request)
    categories = await db.fetch(
        """
        SELECT id, code, name_en, name_ka
          FROM asset_categories
         WHERE legal_entity_id = $1
         ORDER BY name_en
        """,
        actor.legal_entity_id,
    )
    employees = await db.fetch(
        """
        SELECT id, employee_number, first_name || ' ' || last_name AS full_name
         FROM employees
         WHERE legal_entity_id = $1
           AND employment_status = 'active'
           AND deleted_at IS NULL
         ORDER BY first_name, last_name
        """,
        actor.legal_entity_id,
    )
    items = await db.fetch(
        """
        SELECT ii.id,
               ii.asset_tag,
               ii.asset_name,
               ii.brand,
               ii.model,
               ii.serial_number,
               ii.current_condition::text AS current_condition,
               ii.current_status::text AS current_status,
               ii.purchase_date,
               ii.purchase_cost,
               ii.currency_code,
               ii.notes,
               coalesce(ac.name_ka, ac.name_en) AS category_name,
               coalesce(e.first_name || ' ' || e.last_name, NULL) AS assigned_employee_name,
               aa.id AS active_assignment_id
          FROM inventory_items ii
          LEFT JOIN asset_categories ac ON ac.id = ii.category_id
          LEFT JOIN LATERAL (
              SELECT aa.id, aa.employee_id
                FROM asset_assignments aa
               WHERE aa.item_id = ii.id
                 AND aa.returned_at IS NULL
               ORDER BY aa.assigned_at DESC
               LIMIT 1
          ) aa ON true
          LEFT JOIN employees e ON e.id = aa.employee_id
         WHERE ii.legal_entity_id = $1
         ORDER BY ii.asset_name, ii.asset_tag
        """,
        actor.legal_entity_id,
    )
    return {
        'categories': [dict(row) for row in categories],
        'employees': [dict(row) for row in employees],
        'items': [
            {
                **dict(row),
                'id': str(row['id']),
                'active_assignment_id': str(row['active_assignment_id']) if row['active_assignment_id'] else None,
                'purchase_date': row['purchase_date'].isoformat() if row['purchase_date'] else None,
                'purchase_cost': _to_float(row['purchase_cost']),
            }
            for row in items
        ],
    }


@UX_ROUTER.get('/performance-hub')
async def performance_hub(request: Request) -> dict[str, object]:
    actor = await require_actor(request)
    if not actor.has('employee.manage') and 'MANAGER' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='ეფექტიანობის ჰაბისთვის საჭიროა მენეჯერის ან HR-ის წვდომა')
    db = get_db_from_request(request)
    cycle_rows = await db.fetch(
        """
        SELECT id, code, title, year, quarter, start_date, end_date
          FROM okr_cycles
         WHERE legal_entity_id = $1
         ORDER BY year DESC, quarter DESC
         LIMIT 6
        """,
        actor.legal_entity_id,
    )
    objective_rows = await db.fetch(
        """
        SELECT oo.id,
               oo.title,
               oo.scope::text AS scope,
               oo.weight,
               coalesce(d.name_ka, d.name_en) AS department_name,
               coalesce(e.first_name || ' ' || e.last_name, NULL) AS employee_name,
               coalesce(owner.first_name || ' ' || owner.last_name, NULL) AS owner_name,
               oc.title AS cycle_title,
               count(okr.id) AS key_result_count,
               round(avg(
                   least(
                       greatest(
                           CASE
                               WHEN okr.target_value = okr.start_value THEN 100
                               ELSE ((okr.current_value - okr.start_value) / NULLIF((okr.target_value - okr.start_value), 0)) * 100
                           END,
                           0
                       ),
                       100
                   )
               )::numeric, 2) AS progress_percent
          FROM okr_objectives oo
          JOIN okr_cycles oc ON oc.id = oo.cycle_id
          LEFT JOIN departments d ON d.id = oo.department_id
          LEFT JOIN employees e ON e.id = oo.employee_id
          LEFT JOIN employees owner ON owner.id = oo.owner_employee_id
          LEFT JOIN okr_key_results okr ON okr.objective_id = oo.id
         WHERE oc.legal_entity_id = $1
         GROUP BY oo.id, d.name_ka, d.name_en, e.first_name, e.last_name, owner.first_name, owner.last_name, oc.title
         ORDER BY oc.title DESC, oo.created_at DESC
         LIMIT 40
        """,
        actor.legal_entity_id,
    )
    employee_rows = await db.fetch(
        """
        SELECT id, first_name, last_name, employee_number
          FROM employees
         WHERE legal_entity_id = $1
           AND employment_status = 'active'
         ORDER BY first_name, last_name
        """,
        actor.legal_entity_id,
    )
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    heatmap = []
    for employee in employee_rows:
        shifts = await _fetch_resolved_shifts(db, employee['id'], week_start, week_end)
        planned_minutes = sum(shift.planned_minutes for shift in shifts.values())
        objective_count = await db.fetchval(
            """
            SELECT count(*)
              FROM okr_objectives oo
              JOIN okr_cycles oc ON oc.id = oo.cycle_id
             WHERE oc.legal_entity_id = $1
               AND (oo.employee_id = $2 OR oo.owner_employee_id = $2)
            """,
            actor.legal_entity_id,
            employee['id'],
        ) or 0
        utilization = min((planned_minutes / 2400) * 100 + int(objective_count) * 8, 140)
        heatmap.append(
            {
                'employee_id': str(employee['id']),
                'employee_name': f"{employee['first_name']} {employee['last_name']}",
                'employee_number': employee['employee_number'],
                'planned_hours': round(planned_minutes / 60, 2),
                'objective_count': int(objective_count),
                'utilization_score': round(utilization, 1),
                'risk_band': 'high' if utilization >= 100 else ('medium' if utilization >= 75 else 'balanced'),
            }
        )
    return {
        'cycles': [
            {**dict(row), 'id': str(row['id']), 'start_date': row['start_date'].isoformat(), 'end_date': row['end_date'].isoformat()}
            for row in cycle_rows
        ],
        'objectives': [
            {
                **dict(row),
                'id': str(row['id']),
                'weight': _to_float(row['weight']),
                'progress_percent': _to_float(row['progress_percent']),
                'key_result_count': int(row['key_result_count'] or 0),
            }
            for row in objective_rows
        ],
        'heatmap': heatmap,
        'employees': [
            {'id': str(row['id']), 'employee_number': row['employee_number'], 'full_name': f"{row['first_name']} {row['last_name']}"}
            for row in employee_rows
        ],
    }


@UX_ROUTER.get('/payroll-hub')
async def payroll_hub(
    request: Request,
    year: int | None = None,
    month: int | None = None,
    department_id: UUID | None = None,
) -> dict[str, object]:
    actor = await require_actor(request)
    try:
        ensure_can_export_payroll(actor)
    except Exception as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    db = get_db_from_request(request)
    ui_policy = await _entity_ui_policy_flags(db, actor.legal_entity_id)
    if not ui_policy['payroll_dashboard_enabled']:
        raise HTTPException(status_code=403, detail='Payroll dashboard is disabled in system settings')
    target_year = year or date.today().year
    target_month = month or date.today().month
    if department_id is not None:
        department_entity_id = await db.fetchval('SELECT legal_entity_id FROM departments WHERE id = $1', department_id)
        if department_entity_id is None:
            raise HTTPException(status_code=404, detail='Department not found')
        if department_entity_id != actor.legal_entity_id:
            raise HTTPException(status_code=403, detail='Department belongs to another legal entity')
    departments = await db.fetch(
        """
        SELECT id, code, name_en, name_ka
          FROM departments
         WHERE legal_entity_id = $1
           AND is_active = true
         ORDER BY name_en
        """,
        actor.legal_entity_id,
    )
    rows = await db.fetch(
        """
        SELECT mts.id,
               mts.year,
               mts.month,
               mts.status::text AS status,
               mts.base_salary,
               mts.gross_pay,
               mts.net_pay,
               mts.total_minutes,
               mts.overtime_minutes,
               e.id AS employee_id,
               e.employee_number,
               e.first_name,
               e.last_name,
               e.department_id,
               d.name_en AS department_name,
               ec.salary_type,
               ppr.id AS payment_id,
               ppr.paid_at,
               ppr.payment_method,
               ppr.payment_reference,
               ppr.payslip_file_name
          FROM monthly_timesheets mts
          JOIN employees e ON e.id = mts.employee_id
          LEFT JOIN departments d ON d.id = e.department_id
          LEFT JOIN LATERAL (
              SELECT salary_type
                FROM employee_compensation
               WHERE employee_id = e.id
               ORDER BY effective_from DESC
               LIMIT 1
          ) ec ON true
          LEFT JOIN payroll_payment_records ppr ON ppr.timesheet_id = mts.id
         WHERE mts.year = $1
           AND mts.month = $2
           AND e.legal_entity_id = $3
           AND ($4::uuid IS NULL OR e.department_id = $4)
         ORDER BY e.employee_number
        """,
        target_year,
        target_month,
        actor.legal_entity_id,
        department_id,
    )
    return {
        'year': target_year,
        'month': target_month,
        'selected_department_id': str(department_id) if department_id else None,
        'departments': [
            {
                'id': str(row['id']),
                'code': row['code'],
                'name_en': row['name_en'],
                'name_ka': row['name_ka'],
            }
            for row in departments
        ],
        'permissions': {
            'can_generate_draft': True,
            'can_export': True,
        },
        'items': [
            {
                'id': str(row['id']),
                'employee_id': str(row['employee_id']),
                'employee_number': row['employee_number'],
                'employee_name': f"{row['first_name']} {row['last_name']}",
                'department_id': str(row['department_id']) if row['department_id'] else None,
                'department_name': row['department_name'],
                'salary_type': row['salary_type'] or 'monthly_fixed',
                'status': row['status'],
                'base_salary': _to_float(row['base_salary']),
                'gross_pay': _to_float(row['gross_pay']),
                'net_pay': _to_float(row['net_pay']),
                'worked_hours': round(int(row['total_minutes'] or 0) / 60, 2),
                'overtime_hours': round(int(row['overtime_minutes'] or 0) / 60, 2),
                'payment_id': str(row['payment_id']) if row['payment_id'] else None,
                'paid_at': row['paid_at'].isoformat() if row['paid_at'] else None,
                'payment_method': row['payment_method'],
                'payment_reference': row['payment_reference'],
                'payslip_file_name': row['payslip_file_name'],
                'payslip_url': f'/payroll/timesheets/{row["id"]}/payslip.pdf' if row['payment_id'] else None,
            }
            for row in rows
        ],
    }


@UX_ROUTER.get('/device-registry')
async def device_registry_view(request: Request) -> dict[str, object]:
    actor = await require_actor(request)
    if not actor.has('device.manage'):
        raise HTTPException(status_code=403, detail='მოწყობილობების რეესტრისთვის საჭიროა device.manage უფლება')
    db = get_db_from_request(request)
    request_tenant_legal_entity_id = get_request_tenant_legal_entity_id(request)
    if 'ADMIN' in actor.role_codes and request_tenant_legal_entity_id is None:
        tenant_rows = await db.fetch(
            """
            SELECT id, trade_name
              FROM legal_entities
             ORDER BY trade_name
            """
        )
        rows = await db.fetch(
            """
            SELECT dr.id,
                   dr.legal_entity_id,
                   le.trade_name AS tenant_name,
                   dr.brand::text AS brand,
                   dr.transport::text AS transport,
                   dr.device_type,
                   dr.device_name,
                   dr.model,
                   dr.serial_number,
                   dr.host,
                   dr.port,
                   dr.api_base_url,
                   dr.username,
                   dr.password_ciphertext,
                   dr.device_timezone,
                   dr.is_active,
                   dr.poll_interval_seconds,
                   dr.metadata,
                   dr.last_seen_at
              FROM device_registry dr
              JOIN legal_entities le ON le.id = dr.legal_entity_id
             ORDER BY le.trade_name, dr.device_name
            """
        )
    else:
        scoped_legal_entity_id = request_tenant_legal_entity_id or actor.legal_entity_id
        tenant_rows = await db.fetch(
            """
            SELECT id, trade_name
              FROM legal_entities
             WHERE id = $1
            """,
            scoped_legal_entity_id,
        )
        rows = await db.fetch(
            """
            SELECT dr.id,
                   dr.legal_entity_id,
                   le.trade_name AS tenant_name,
                   dr.brand::text AS brand,
                   dr.transport::text AS transport,
                   dr.device_type,
                   dr.device_name,
                   dr.model,
                   dr.serial_number,
                   dr.host,
                   dr.port,
                   dr.api_base_url,
                   dr.username,
                   dr.password_ciphertext,
                   dr.device_timezone,
                   dr.is_active,
                   dr.poll_interval_seconds,
                   dr.metadata,
                   dr.last_seen_at
              FROM device_registry dr
              JOIN legal_entities le ON le.id = dr.legal_entity_id
             WHERE dr.legal_entity_id = $1
             ORDER BY dr.device_name
            """,
            scoped_legal_entity_id,
        )
    return {
        'tenants': [{'id': str(row['id']), 'trade_name': row['trade_name']} for row in tenant_rows],
        'items': [
            {
                **dict(row),
                'id': str(row['id']),
                'legal_entity_id': str(row['legal_entity_id']),
                'password_ciphertext': None,
                'last_seen_at': row['last_seen_at'].isoformat() if row['last_seen_at'] else None,
            }
            for row in rows
        ]
    }


@UX_ROUTER.get('/org-chart')
async def org_chart_view(request: Request) -> dict[str, object]:
    actor = await require_actor(request)
    db = get_db_from_request(request)
    rows = await db.fetch(
        """
        SELECT e.id,
               e.employee_number,
               e.first_name,
               e.last_name,
               coalesce(e.line_manager_id, e.manager_employee_id) AS manager_id,
               coalesce(m.first_name || ' ' || m.last_name, '') AS manager_name,
               coalesce(d.name_ka, d.name_en) AS department_name,
               coalesce(jr.title_ka, jr.title_en) AS role_title
          FROM employees e
         LEFT JOIN employees m ON m.id = coalesce(e.line_manager_id, e.manager_employee_id)
         LEFT JOIN departments d ON d.id = e.department_id
         LEFT JOIN job_roles jr ON jr.id = e.job_role_id
         WHERE e.legal_entity_id = $1
           AND e.deleted_at IS NULL
           AND e.employment_status IN ('active', 'suspended')
         ORDER BY manager_name, e.first_name, e.last_name
        """,
        actor.legal_entity_id,
    )
    return {
        'nodes': [
            {
                'id': str(row['id']),
                'employee_number': row['employee_number'],
                'full_name': f"{row['first_name']} {row['last_name']}",
                'manager_id': str(row['manager_id']) if row['manager_id'] else None,
                'manager_name': row['manager_name'] or None,
                'department_name': row['department_name'],
                'role_title': row['role_title'],
            }
            for row in rows
        ]
    }


@UX_ROUTER.get('/system-config')
async def system_config_view(request: Request) -> dict[str, object]:
    actor = await require_actor(request)
    ensure_permission(actor, 'settings.manage')
    db = get_db_from_request(request)
    legal_entity = await db.fetchrow(
        'SELECT id, legal_name, trade_name, tax_id, timezone, currency_code FROM legal_entities WHERE id = $1',
        actor.legal_entity_id,
    )
    config = await db.fetchrow(
        """
        SELECT esc.logo_url, esc.logo_text, esc.primary_color, esc.standalone_chat_url,
               esc.linkedin_url, esc.facebook_url, esc.instagram_url,
               esc.allowed_web_punch_ips, esc.geofence_latitude, esc.geofence_longitude, esc.geofence_radius_meters,
               esc.gps_only_check_in, esc.company_dashboard_enabled, esc.payroll_dashboard_enabled, esc.dashboard_widget_visibility,
               eos.late_arrival_threshold_minutes, eos.require_asset_clearance_for_final_payroll, eos.default_onboarding_course_id
          FROM entity_system_config esc
          FULL OUTER JOIN entity_operation_settings eos ON eos.legal_entity_id = esc.legal_entity_id
         WHERE coalesce(esc.legal_entity_id, eos.legal_entity_id) = $1
        """,
        actor.legal_entity_id,
    )
    request_tenant_legal_entity_id = get_request_tenant_legal_entity_id(request)
    pay_policies = await db.fetch(
        """
        SELECT id, code, name, income_tax_rate, employee_pension_rate
          FROM pay_policies
         WHERE legal_entity_id = $1
         ORDER BY code
        """,
        actor.legal_entity_id,
    )
    access_roles = await db.fetch(
        'SELECT id, code, name_en, name_ka FROM access_roles ORDER BY code'
    )
    employees = await db.fetch(
        """
        SELECT e.id,
               e.employee_number,
               e.first_name,
               e.last_name,
               array_remove(array_agg(DISTINCT ar.code::text), NULL) AS role_codes
          FROM employees e
          LEFT JOIN employee_access_roles ear ON ear.employee_id = e.id
          LEFT JOIN access_roles ar ON ar.id = ear.access_role_id
         WHERE e.legal_entity_id = $1
         GROUP BY e.id
         ORDER BY e.employee_number
        """,
        actor.legal_entity_id,
    )
    departments = await db.fetch(
        """
        SELECT id, coalesce(name_ka, name_en) AS name
          FROM departments
         WHERE legal_entity_id = $1
           AND is_active = true
         ORDER BY coalesce(name_ka, name_en)
        """,
        actor.legal_entity_id,
    )
    leave_policy = await _leave_policy_settings(db, actor.legal_entity_id)
    schedule_manager_rows = await db.fetch(
        """
        SELECT department_id, employee_id
          FROM department_schedule_managers
         WHERE legal_entity_id = $1
         ORDER BY department_id, employee_id
        """,
        actor.legal_entity_id,
    )
    department_approver_rows = await db.fetch(
        """
        SELECT department_id, approver_employee_id
          FROM department_leave_approvers
         WHERE legal_entity_id = $1
         ORDER BY department_id
        """,
        actor.legal_entity_id,
    )
    mattermost = await _fetch_mattermost_config(db, actor.legal_entity_id)
    subscriptions = await db.fetchrow(
        """
        SELECT attendance_enabled, payroll_enabled, ats_enabled, chat_enabled,
               device_management_enabled, mobile_sync_enabled,
               assets_enabled, org_chart_enabled, performance_enabled
          FROM tenant_subscriptions
         WHERE legal_entity_id = $1
        """,
        actor.legal_entity_id,
    )
    domains = await db.fetch(
        """
        SELECT id, host, subdomain, is_primary, is_active
          FROM tenant_domains
         WHERE legal_entity_id = $1
         ORDER BY is_primary DESC, host
        """,
        actor.legal_entity_id,
    )
    employee_editor_rows = await db.fetch(
        """
        SELECT department_id, employee_id
          FROM department_employee_editors
         WHERE legal_entity_id = $1
         ORDER BY department_id, employee_id
        """,
        actor.legal_entity_id,
    )
    worksites = await db.fetch(
        """
        SELECT id, name, latitude, longitude, radius_meters, address_text, is_active
          FROM worksites
         WHERE legal_entity_id = $1
         ORDER BY is_active DESC, name
        """,
        actor.legal_entity_id,
    )
    middleware_api_keys = await db.fetch(
        """
        SELECT id, key_name, last_used_at, revoked_at, created_at
          FROM device_middleware_api_keys
         WHERE legal_entity_id = $1
         ORDER BY created_at DESC
        """,
        actor.legal_entity_id,
    )
    permission_catalog_rows = await db.fetch(
        """
        SELECT code, description
          FROM permissions
         ORDER BY code
        """
    )
    role_permission_rows = await db.fetch(
        """
        SELECT ar.code AS role_code, arp.permission_code
          FROM access_roles ar
          JOIN access_role_permissions arp ON arp.access_role_id = ar.id
         ORDER BY ar.code, arp.permission_code
        """
    )
    role_override_rows = await db.fetch(
        """
        SELECT ar.code AS role_code, tro.permission_code, tro.is_enabled
          FROM tenant_role_permission_overrides tro
          JOIN access_roles ar ON ar.id = tro.access_role_id
         WHERE tro.legal_entity_id = $1
         ORDER BY ar.code, tro.permission_code
        """,
        actor.legal_entity_id,
    )
    role_permissions: dict[str, set[str]] = {}
    for row in role_permission_rows:
        role_permissions.setdefault(row['role_code'], set()).add(row['permission_code'])
    for row in role_override_rows:
        permission_set = role_permissions.setdefault(row['role_code'], set())
        if row['is_enabled']:
            permission_set.add(row['permission_code'])
        else:
            permission_set.discard(row['permission_code'])
    tenants = []
    if 'ADMIN' in actor.role_codes:
        tenant_rows = await db.fetch(
            """
            SELECT le.id,
                   le.legal_name,
                   le.trade_name,
                   le.tax_id,
                   le.timezone,
                   le.currency_code,
                   td.host AS primary_host,
                   count(DISTINCT e.id) AS employee_count,
                   count(DISTINCT ai.id) AS login_count
              FROM legal_entities le
              LEFT JOIN tenant_domains td
                ON td.legal_entity_id = le.id
               AND td.is_primary = true
              LEFT JOIN employees e
                ON e.legal_entity_id = le.id
              LEFT JOIN auth_identities ai
                ON ai.employee_id = e.id
               AND ai.is_active = true
             GROUP BY le.id, td.host
             ORDER BY le.trade_name
            """
        )
        tenants = [
            {
                'id': str(row['id']),
                'legal_name': row['legal_name'],
                'trade_name': row['trade_name'],
                'tax_id': row['tax_id'],
                'timezone': row['timezone'],
                'currency_code': row['currency_code'],
                'primary_host': row['primary_host'],
                'employee_count': int(row['employee_count'] or 0),
                'login_count': int(row['login_count'] or 0),
            }
            for row in tenant_rows
        ]
    return {
        'legal_entity': dict(legal_entity) if legal_entity else None,
        'access_context': {
            'request_host': request.headers.get('x-forwarded-host') or request.headers.get('host') or None,
            'tenant_isolation_active': request_tenant_legal_entity_id is not None,
        },
        'tenants': tenants,
        'config': {
            'logo_url': config['logo_url'] if config else None,
            'logo_text': config['logo_text'] if config else None,
            'primary_color': config['primary_color'] if config and config['primary_color'] else '#1A2238',
            'standalone_chat_url': config['standalone_chat_url'] if config else None,
            'linkedin_url': config['linkedin_url'] if config else None,
            'facebook_url': config['facebook_url'] if config else None,
            'instagram_url': config['instagram_url'] if config else None,
            'allowed_web_punch_ips': (config['allowed_web_punch_ips'] if config else []) or [],
            'geofence_latitude': float(config['geofence_latitude']) if config and config['geofence_latitude'] is not None else None,
            'geofence_longitude': float(config['geofence_longitude']) if config and config['geofence_longitude'] is not None else None,
            'geofence_radius_meters': int(config['geofence_radius_meters']) if config and config['geofence_radius_meters'] is not None else None,
            'gps_only_check_in': bool(config['gps_only_check_in']) if config and config['gps_only_check_in'] is not None else False,
            'company_dashboard_enabled': bool(config['company_dashboard_enabled']) if config and config['company_dashboard_enabled'] is not None else True,
            'payroll_dashboard_enabled': bool(config['payroll_dashboard_enabled']) if config and config['payroll_dashboard_enabled'] is not None else True,
            'dashboard_widget_visibility': _normalize_dashboard_widget_visibility(
                config['dashboard_widget_visibility'] if config else None
            ),
            'late_arrival_threshold_minutes': int(config['late_arrival_threshold_minutes']) if config and config['late_arrival_threshold_minutes'] is not None else 15,
            'require_asset_clearance_for_final_payroll': bool(config['require_asset_clearance_for_final_payroll']) if config and config['require_asset_clearance_for_final_payroll'] is not None else True,
            'default_onboarding_course_id': str(config['default_onboarding_course_id']) if config and config['default_onboarding_course_id'] else None,
        },
        'pay_policies': [
            {
                **dict(row),
                'id': str(row['id']),
                'income_tax_rate': _to_float(row['income_tax_rate']),
                'employee_pension_rate': _to_float(row['employee_pension_rate']),
            }
            for row in pay_policies
        ],
        'roles': [dict(row) for row in access_roles],
        'permission_catalog': [dict(row) for row in permission_catalog_rows],
        'role_permissions': {
            role_code: sorted(permission_codes)
            for role_code, permission_codes in sorted(role_permissions.items())
        },
        'employees': [
            {
                'id': str(row['id']),
                'employee_number': row['employee_number'],
                'full_name': f"{row['first_name']} {row['last_name']}",
                'role_codes': row['role_codes'] or [],
            }
            for row in employees
        ],
        'departments': [
            {
                'id': str(row['id']),
                'name': row['name'],
            }
            for row in departments
        ],
        'policy_access': {
            'is_super_admin': bool({'ADMIN', 'TENANT_ADMIN'} & actor.role_codes),
            'is_platform_super_admin': 'ADMIN' in actor.role_codes,
            'can_manage_master_modules': 'ADMIN' in actor.role_codes,
        },
        'leave_policy': {
            'paid_leave_allowance_days': int(leave_policy['paid_leave_allowance_days']),
            'unpaid_leave_allowance_days': int(leave_policy['unpaid_leave_allowance_days']),
            'eligibility_months': int(leave_policy['eligibility_months']),
            'enable_birthday_off': bool(leave_policy['enable_birthday_off']),
            'enable_day_off': bool(leave_policy['enable_day_off']),
            'global_leave_approver_employee_id': str(leave_policy['global_leave_approver_employee_id']) if leave_policy['global_leave_approver_employee_id'] else None,
        },
        'schedule_manager_assignments': [
            {
                'department_id': str(row['department_id']),
                'employee_id': str(row['employee_id']),
            }
            for row in schedule_manager_rows
        ],
        'department_employee_editors': [
            {
                'department_id': str(row['department_id']),
                'employee_id': str(row['employee_id']),
            }
            for row in employee_editor_rows
        ],
        'department_leave_approvers': [
            {
                'department_id': str(row['department_id']),
                'approver_employee_id': str(row['approver_employee_id']) if row['approver_employee_id'] else None,
            }
            for row in department_approver_rows
        ],
        'mattermost': {
            'enabled': bool(mattermost.enabled),
            'server_base_url': mattermost.server_base_url,
            'default_team': mattermost.default_team,
            'hr_channel': mattermost.hr_channel,
            'general_channel': mattermost.general_channel,
            'it_channel': mattermost.it_channel,
        } if mattermost else None,
        'subscriptions': dict(subscriptions) if subscriptions else DEFAULT_FEATURE_FLAGS,
        'domains': [{**dict(row), 'id': str(row['id'])} for row in domains],
        'worksites': [
            {
                'id': str(row['id']),
                'name': row['name'],
                'latitude': float(row['latitude']),
                'longitude': float(row['longitude']),
                'radius_meters': int(row['radius_meters']),
                'address_text': row['address_text'],
                'is_active': bool(row['is_active']),
            }
            for row in worksites
        ],
        'middleware_api_keys': [
            {
                'id': str(row['id']),
                'key_name': row['key_name'],
                'last_used_at': row['last_used_at'].isoformat() if row['last_used_at'] else None,
                'revoked_at': row['revoked_at'].isoformat() if row['revoked_at'] else None,
                'created_at': row['created_at'].isoformat() if row['created_at'] else None,
            }
            for row in middleware_api_keys
        ],
        'smtp': {
            'configured': bool(settings.smtp_host),
            'host': settings.smtp_host or None,
            'port': settings.smtp_port,
            'username': settings.smtp_username or None,
            'from_email': settings.smtp_from_email or None,
            'use_tls': settings.smtp_use_tls,
            'managed_in': '.env and docker-compose.yml',
        },
        'edge_middleware': {
            'compose_file': 'deployment/docker-compose.tenant.yml',
            'public_base_url': settings.public_base_url,
            'device_workers_enabled': settings.enable_device_workers,
            'ops_workers_enabled': settings.enable_ops_workers,
        },
    }


@UX_ROUTER.get('/app', response_class=HTMLResponse)
async def frontend_shell() -> HTMLResponse:
    index_file = Path(__file__).resolve().parent.parent / 'static' / 'dashboard' / 'index.html'
    if not index_file.exists():
        raise HTTPException(status_code=404, detail='ფრონტენდის ბილდი არ არის აგებული')
    content = index_file.read_text(encoding='utf-8')
    response = HTMLResponse(content)
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

