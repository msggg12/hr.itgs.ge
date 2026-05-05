from __future__ import annotations

import asyncio
import base64
import csv
import hashlib
import io
import ipaddress
import json
import math
import re
import secrets
import string
import zipfile
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

try:  # pragma: no cover - exception classes available at runtime
    from asyncpg import PostgresError, UniqueViolationError
except ImportError:  # pragma: no cover - local tooling may not have asyncpg installed
    PostgresError = Exception  # type: ignore[assignment]
    UniqueViolationError = Exception  # type: ignore[assignment]

from .analytics import ANALYTICS_ROUTER, burnout_monitor_loop
from .api_support import get_db_from_request, require_actor
from .assets_lifecycle import ASSETS_ROUTER, ConditionEvidenceCreate, offboarding_monitor_loop
from .ats_onboarding import ATS_ROUTER, _generate_employee_number, analyze_candidate_application
from .auth import AUTH_ROUTER, hash_password
from .config import settings
from .db import Database, DatabaseUnavailable, apply_current_database_rls_context, set_database_rls_context
from .device_middleware import (
    ZK_ROUTER,
    add_employee_to_all_devices,
    build_driver,
    delete_employee_from_all_devices,
    device_ingestion_loop,
    fetch_employee_synced_devices,
    prepare_employee_device_profiles,
    queue_employee_upsert_for_device,
    sync_employee_device_assignments,
)
from .i18n_ka import KA_TRANSLATIONS
from .labor_engine import build_monthly_timesheet_from_db, payroll_export_rows, persist_monthly_timesheet
from .mail_engine import send_and_log_email
from .mattermost_integration import (
    MATTERMOST_ROUTER,
    celebration_monitor_loop,
    ensure_mattermost_teams_for_all_tenants,
    late_arrival_monitor_loop,
    send_leave_approval_request,
)
from .monitoring import MONITORING_ROUTER, metrics_middleware, node_heartbeat_loop
from .performance import PERFORMANCE_ROUTER
from .rbac import (
    AuthorizationError,
    apply_rls_context,
    can_edit_employee_profiles,
    can_export_employees,
    can_import_employees,
    can_view_employee_directory,
    can_view_employee_record,
    employee_directory_scope,
    ensure_can_export_payroll,
    ensure_can_view_attendance,
    ensure_permission,
)
from .runtime_setup import ensure_runtime_schema
from .tenant import DEFAULT_FEATURE_FLAGS, resolve_request_tenant
from .tenant_integrity import ensure_employee_reference_tenant
from .user_experience import UX_ROUTER
from .connect_suite import INTEGRATIONS_ROUTER

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / 'static'
UPLOADS_DIR = STATIC_DIR / 'uploads'
LEAVE_UPLOADS_DIR = UPLOADS_DIR / 'leave'
PROFILE_UPLOADS_DIR = UPLOADS_DIR / 'profile'
CANDIDATE_UPLOADS_DIR = UPLOADS_DIR / 'candidates'
GEORGIA_TZ = ZoneInfo('Asia/Tbilisi')


class EmployeeCreateRequest(BaseModel):
    legal_entity_id: UUID
    employee_number: str
    personal_number: str | None = None
    first_name: str
    last_name: str
    email: str | None = None
    mobile_phone: str | None = None
    department_id: UUID | None = None
    job_role_id: UUID | None = None
    manager_employee_id: UUID | None = None
    hire_date: date
    base_salary: Decimal = Field(ge=0)
    pay_policy_id: UUID
    salary_type: str = Field(default='monthly_fixed')
    hourly_rate_override: Decimal | None = Field(default=None, ge=0)
    is_pension_participant: bool = True
    access_role_codes: list[str] = Field(default_factory=lambda: ['EMPLOYEE'])
    default_device_user_id: str | None = None


class EmployeeInviteRequest(BaseModel):
    legal_entity_id: UUID
    email: str
    department_id: UUID | None = None
    job_role_id: UUID | None = None
    manager_employee_id: UUID | None = None
    base_salary: Decimal = Field(ge=0)
    pay_policy_id: UUID
    salary_type: str = Field(default='monthly_fixed')
    is_pension_participant: bool = True


class EmployeeDailyStatusRequest(BaseModel):
    status_date: date
    work_mode: str
    note: str | None = None


class SeparationRecordRequest(BaseModel):
    separation_date: date
    reason_category: str
    reason_details: str | None = None
    eligible_rehire: bool = True


class ChatAccountLinkRequest(BaseModel):
    mattermost_user_id: str | None = None
    mattermost_username: str | None = None


class EmployeeUpdateRequest(BaseModel):
    first_name: str
    last_name: str
    email: str | None = None
    mobile_phone: str | None = None
    department_id: UUID | None = None
    job_role_id: UUID | None = None
    manager_employee_id: UUID | None = None
    base_salary: Decimal | None = Field(default=None, ge=0)
    pay_policy_id: UUID | None = None
    salary_type: str | None = Field(default=None)
    hourly_rate_override: Decimal | None = Field(default=None, ge=0)
    is_pension_participant: bool = True
    default_device_user_id: str | None = None


class PayrollDraftGenerateRequest(BaseModel):
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)
    department_id: UUID | None = None


class DahuaWebhookRequest(BaseModel):
    payload: dict[str, Any] | None = None


class JobRoleCreateRequest(BaseModel):
    legal_entity_id: UUID
    title_ka: str
    title_en: str | None = None
    description: str | None = None
    is_managerial: bool = False


class DepartmentCreateRequest(BaseModel):
    legal_entity_id: UUID
    name_ka: str
    name_en: str | None = None


class EmployeeDeviceSyncRequest(BaseModel):
    device_ids: list[UUID] = Field(default_factory=list)




class EntityOperationSettingsUpsertRequest(BaseModel):
    late_arrival_threshold_minutes: int = Field(default=15, ge=1, le=240)
    require_asset_clearance_for_final_payroll: bool = True
    default_onboarding_course_id: UUID | None = None


class MattermostIntegrationUpsertRequest(BaseModel):
    enabled: bool = False
    server_base_url: str | None = None
    incoming_webhook_url: str | None = None
    hr_webhook_url: str | None = None
    general_webhook_url: str | None = None
    it_webhook_url: str | None = None
    bot_access_token: str | None = None
    command_token: str | None = None
    action_secret: str | None = None
    default_team: str | None = None
    hr_channel: str | None = None
    general_channel: str | None = None
    it_channel: str | None = None


class ShiftSegmentInput(BaseModel):
    day_index: int = Field(ge=1, le=366)
    start_time: str
    end_time: str
    break_minutes: int = Field(default=0, ge=0, le=720)
    label: str | None = None


class ShiftPatternUpsertRequest(BaseModel):
    code: str
    name: str
    pattern_type: str = Field(default='fixed_weekly')
    cycle_length_days: int = Field(default=7, ge=1, le=366)
    timezone: str = 'Asia/Tbilisi'
    standard_weekly_hours: Decimal = Field(default=Decimal('40.00'), gt=0)
    early_check_in_grace_minutes: int = Field(default=60, ge=0, le=720)
    late_check_out_grace_minutes: int = Field(default=240, ge=0, le=720)
    grace_period_minutes: int = Field(default=15, ge=0, le=240)
    segments: list[ShiftSegmentInput] = Field(default_factory=list)


class AttendanceOverrideRequest(BaseModel):
    session_id: UUID | None = None
    work_date: date
    corrected_check_in: datetime
    corrected_check_out: datetime | None = None
    resolution_note: str = Field(min_length=5)
    mark_review_status: str = Field(default='corrected')


class WebPunchRequest(BaseModel):
    direction: str = Field(default='auto')
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    gps_accuracy_meters: float | None = Field(default=None, ge=0, le=50000)


class VacancyFieldOption(BaseModel):
    label: str
    value: str


class VacancyFieldDefinition(BaseModel):
    key: str
    label: str
    field_type: str
    required: bool = True
    options: list[VacancyFieldOption] = Field(default_factory=list)


class VacancyUpsertRequest(BaseModel):
    posting_code: str
    title_en: str
    title_ka: str
    description: str
    public_description: str | None = None
    employment_type: str
    location_text: str | None = None
    status: str = Field(default='draft')
    open_positions: int = Field(default=1, ge=1)
    salary_min: Decimal | None = Field(default=None, ge=0)
    salary_max: Decimal | None = Field(default=None, ge=0)
    department_id: UUID | None = None
    job_role_id: UUID | None = None
    closes_at: datetime | None = None
    public_slug: str | None = None
    external_form_url: str | None = None
    is_public: bool = True
    application_form_schema: list[VacancyFieldDefinition] = Field(default_factory=list)


class PublicCandidateApplicationRequest(BaseModel):
    first_name: str
    last_name: str
    email: str | None = None
    phone: str | None = None
    city: str | None = None
    source: str = 'career_page'
    current_company: str | None = None
    current_position: str | None = None
    notes: str | None = None
    answers: dict[str, Any] = Field(default_factory=dict)


class InventoryItemUpsertRequest(BaseModel):
    category_id: UUID | None = None
    asset_tag: str
    asset_name: str
    brand: str | None = None
    model: str | None = None
    serial_number: str | None = None
    current_condition: str = Field(default='new')
    current_status: str = Field(default='in_stock')
    purchase_date: date | None = None
    purchase_cost: Decimal | None = Field(default=None, ge=0)
    currency_code: str = 'GEL'
    assigned_department_id: UUID | None = None
    notes: str | None = None


class InventoryAssignRequest(BaseModel):
    employee_id: UUID
    assigned_at: datetime
    expected_return_at: datetime | None = None
    condition_on_issue: str = Field(default='good')
    note: str | None = None
    employee_signature_name: str
    evidence: list[ConditionEvidenceCreate] = Field(default_factory=list)


class PayrollMarkPaidRequest(BaseModel):
    paid_at: datetime | None = None
    payment_method: str = 'bank_transfer'
    payment_reference: str | None = None
    note: str | None = None


class SystemConfigUpsertRequest(BaseModel):
    trade_name: str | None = None
    logo_url: str | None = None
    logo_text: str | None = None
    primary_color: str = '#1A2238'
    standalone_chat_url: str | None = None
    linkedin_url: str | None = None
    facebook_url: str | None = None
    instagram_url: str | None = None
    allowed_web_punch_ips: list[str] = Field(default_factory=list)
    geofence_latitude: float | None = Field(default=None, ge=-90, le=90)
    geofence_longitude: float | None = Field(default=None, ge=-180, le=180)
    geofence_radius_meters: int | None = Field(default=None, ge=10, le=50000)
    gps_only_check_in: bool = False
    company_dashboard_enabled: bool = True
    payroll_dashboard_enabled: bool = True
    dashboard_widget_visibility: dict[str, bool] = Field(default_factory=dict)
    income_tax_rate: Decimal | None = Field(default=None, ge=0, le=1)
    employee_pension_rate: Decimal | None = Field(default=None, ge=0, le=1)
    late_arrival_threshold_minutes: int = Field(default=15, ge=1, le=240)
    require_asset_clearance_for_final_payroll: bool = True
    default_onboarding_course_id: UUID | None = None


class WorksiteUpsertInput(BaseModel):
    id: UUID | None = None
    name: str = Field(min_length=1, max_length=255)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_meters: int = Field(default=150, ge=10, le=5000)
    address_text: str | None = None
    is_active: bool = True


class WorksitesBulkUpdateRequest(BaseModel):
    worksites: list[WorksiteUpsertInput] = Field(default_factory=list)


class MiddlewareApiKeyCreateRequest(BaseModel):
    key_name: str = Field(min_length=3, max_length=120)


class CardEnrollmentStartRequest(BaseModel):
    employee_id: UUID
    device_id: UUID


class CardEnrollmentReadRequest(BaseModel):
    enrollment_token: str = Field(min_length=16, max_length=255)
    card_id: str = Field(min_length=1, max_length=255)
    device_serial: str | None = None


class MiddlewareAttendanceLogInput(BaseModel):
    person_id: str = Field(min_length=1, max_length=255)
    event_ts: datetime
    direction: str | None = 'unknown'
    verify_mode: str | None = None
    external_log_id: str | None = None
    device_serial: str | None = None
    device_name: str | None = None
    raw_payload: dict[str, Any] | None = None


class MiddlewareAttendanceImportRequest(BaseModel):
    logs: list[MiddlewareAttendanceLogInput] = Field(default_factory=list)


class MiddlewareDeviceCommandFetchRequest(BaseModel):
    limit: int = Field(default=50, ge=1, le=200)


class MiddlewareDeviceCommandResultRequest(BaseModel):
    status: str
    error: str | None = None


class MiddlewareDevicePingReport(BaseModel):
    device_id: UUID
    reachable: bool = True
    rtt_ms: int | None = Field(default=None, ge=0, le=600_000)


class MiddlewareBridgeHeartbeatRequest(BaseModel):
    """When device_pings is non-empty, last_seen_at is updated only for reachable devices (per-IP probe from middleware)."""

    device_pings: list[MiddlewareDevicePingReport] = Field(default_factory=list)


class DepartmentManagerAssignmentInput(BaseModel):
    department_id: UUID
    employee_ids: list[UUID] = Field(default_factory=list)


class ScheduleManagerAssignmentsUpdateRequest(BaseModel):
    assignments: list[DepartmentManagerAssignmentInput] = Field(default_factory=list)


class EmployeeEditorAssignmentsUpdateRequest(BaseModel):
    assignments: list[DepartmentManagerAssignmentInput] = Field(default_factory=list)


class DepartmentApproverAssignmentInput(BaseModel):
    department_id: UUID
    approver_employee_id: UUID | None = None


class LeavePoliciesUpdateRequest(BaseModel):
    paid_leave_allowance_days: int = Field(default=24, ge=0, le=365)
    unpaid_leave_allowance_days: int = Field(default=15, ge=0, le=365)
    eligibility_months: int = Field(default=11, ge=0, le=24)
    enable_birthday_off: bool = False
    enable_day_off: bool = False
    global_leave_approver_employee_id: UUID | None = None
    department_approvers: list[DepartmentApproverAssignmentInput] = Field(default_factory=list)


class EmployeeRoleUpdateRequest(BaseModel):
    role_codes: list[str] = Field(default_factory=list)


class RolePermissionsUpdateRequest(BaseModel):
    permission_codes: list[str] = Field(default_factory=list)


class EmployeeAccessGrantRequest(BaseModel):
    username: str | None = None
    delivery_channel: str = Field(default='email')
    send_invite: bool = True


class TenantSubscriptionUpdateRequest(BaseModel):
    attendance_enabled: bool = True
    payroll_enabled: bool = True
    ats_enabled: bool = True
    chat_enabled: bool = True
    device_management_enabled: bool = True
    mobile_sync_enabled: bool = True
    assets_enabled: bool = True
    org_chart_enabled: bool = True
    performance_enabled: bool = True


class TenantDomainUpsertRequest(BaseModel):
    host: str
    subdomain: str | None = None
    is_primary: bool = False
    is_active: bool = True


class LegalEntityCreateRequest(BaseModel):
    legal_name: str
    trade_name: str
    tax_id: str
    host: str | None = None
    subdomain: str | None = None
    admin_username: str
    admin_email: str
    admin_password: str = Field(min_length=8)
    admin_first_name: str = 'Company'
    admin_last_name: str = 'Administrator'


class DeviceRegistryUpsertRequest(BaseModel):
    legal_entity_id: UUID
    brand: str
    transport: str
    device_type: str = Field(default='biometric_terminal')
    device_name: str
    model: str
    serial_number: str
    host: str
    port: int = Field(ge=1, le=65535)
    api_base_url: str | None = None
    username: str | None = None
    password_ciphertext: str | None = None
    device_timezone: str = 'Asia/Tbilisi'
    is_active: bool = True
    poll_interval_seconds: int = Field(default=60, ge=10, le=86400)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ManualAttendanceAdjustmentRequest(BaseModel):
    employee_id: UUID
    session_id: UUID | None = None
    work_date: date
    corrected_check_in: datetime
    corrected_check_out: datetime | None = None
    reason_comment: str = Field(min_length=5)


EMAIL_PATTERN = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
TENANT_ADMIN_PERMISSIONS = [
    'employee.directory.read',
    'employee.read_self',
    'employee.read_department',
    'employee.edit',
    'employee.invite',
    'employee.import',
    'employee.export',
    'employee.delete',
    'employee.manage',
    'attendance.read_self',
    'attendance.read_department',
    'attendance.read_all',
    'attendance.edit_logs',
    'attendance.geofence_override',
    'attendance.review',
    'leave.request',
    'leave.approve',
    'leave.view_balances',
    'payroll.view',
    'payroll.finalize',
    'payroll.bank_export',
    'payroll.export',
    'compensation.read_all',
    'compensation.edit',
    'device.manage',
    'assets.read_self',
    'assets.read_all',
    'assets.manage',
    'recruitment.read',
    'recruitment.create_vacancy',
    'recruitment.hire',
    'recruitment.manage',
    'settings.manage',
]

STANDARD_ACCESS_ROLE_PERMISSIONS: dict[str, dict[str, object]] = {
    'ADMIN': {
        'name_en': 'System Administrator',
        'name_ka': 'სისტემის ადმინისტრატორი',
        'description': 'Full administrative access to the HRMS',
        'permissions': TENANT_ADMIN_PERMISSIONS,
    },
    'HR': {
        'name_en': 'Human Resources',
        'name_ka': 'ადამიანური რესურსები',
        'description': 'Full HR access including invites, recruitment, leave approvals, and payroll visibility',
        'permissions': [
            'employee.directory.read',
            'employee.read_self',
            'employee.read_department',
            'employee.edit',
            'employee.invite',
            'employee.import',
            'employee.export',
            'employee.manage',
            'attendance.read_self',
            'attendance.read_all',
            'attendance.edit_logs',
            'attendance.review',
            'leave.request',
            'leave.approve',
            'leave.view_balances',
            'payroll.view',
            'payroll.export',
            'compensation.read_all',
            'compensation.edit',
            'recruitment.read',
            'recruitment.create_vacancy',
            'recruitment.hire',
            'recruitment.manage',
        ],
    },
    'MANAGER': {
        'name_en': 'Manager',
        'name_ka': 'მენეჯერი',
        'description': 'Team-level people, attendance, leave, and hiring access',
        'permissions': [
            'employee.read_self',
            'employee.read_department',
            'employee.edit',
            'employee.invite',
            'attendance.read_self',
            'attendance.read_department',
            'attendance.review',
            'leave.request',
            'leave.approve',
            'leave.view_balances',
            'recruitment.read',
            'recruitment.create_vacancy',
            'recruitment.hire',
            'recruitment.manage',
        ],
    },
    'ACCOUNTANT': {
        'name_en': 'Accountant',
        'name_ka': 'ბუღალტერი',
        'description': 'Payroll, compensation, and finance export access',
        'permissions': [
            'employee.read_self',
            'employee.directory.read',
            'attendance.read_self',
            'attendance.read_all',
            'leave.view_balances',
            'payroll.view',
            'payroll.finalize',
            'payroll.bank_export',
            'payroll.export',
            'compensation.read_all',
            'compensation.edit',
        ],
    },
    'EMPLOYEE': {
        'name_en': 'Employee',
        'name_ka': 'თანამშრომელი',
        'description': 'Company directory and own self-service access',
        'permissions': [
            'employee.directory.read',
            'employee.read_self',
            'attendance.read_self',
            'leave.request',
            'leave.view_balances',
            'assets.read_self',
        ],
    },
    'ESS_EMPLOYEE': {
        'name_en': 'ESS Employee',
        'name_ka': 'ESS თანამშრომელი',
        'description': 'Strict self-service access without the full employee directory',
        'permissions': [
            'employee.read_self',
            'attendance.read_self',
            'leave.request',
            'leave.view_balances',
            'assets.read_self',
        ],
    },
    'TEAM_LEAD': {
        'name_en': 'Team Lead',
        'name_ka': 'გუნდის ლიდი',
        'description': 'Can edit team profiles and attendance without salary access',
        'permissions': [
            'employee.read_self',
            'employee.read_department',
            'employee.edit',
            'employee.invite',
            'attendance.read_self',
            'attendance.read_department',
            'attendance.review',
            'leave.request',
            'leave.approve',
            'leave.view_balances',
        ],
    },
    'DEPARTMENT_HEAD': {
        'name_en': 'Department Head',
        'name_ka': 'დეპარტამენტის ხელმძღვანელი',
        'description': 'Can edit team profiles, approve leave, and view salary data for their department',
        'permissions': [
            'employee.read_self',
            'employee.read_department',
            'employee.edit',
            'employee.invite',
            'attendance.read_self',
            'attendance.read_department',
            'attendance.review',
            'leave.request',
            'leave.approve',
            'leave.view_balances',
            'compensation.read_all',
        ],
    },
    'TENANT_ADMIN': {
        'name_en': 'Tenant Administrator',
        'name_ka': 'კომპანიის ადმინისტრატორი',
        'description': 'Full tenant-level access without platform-wide cross-tenant override',
        'permissions': TENANT_ADMIN_PERMISSIONS,
    },
}

PERMISSION_DESCRIPTIONS: dict[str, str] = {
    'employee.directory.read': 'Read the company employee directory',
    'employee.read_self': 'Read own employee profile',
    'employee.read_department': 'Read employee profiles in managed departments',
    'employee.edit': 'Edit employee profiles in allowed scope',
    'employee.invite': 'Invite employees into the HRMS onboarding flow',
    'employee.import': 'Import employees in bulk',
    'employee.export': 'Export the employee directory',
    'employee.delete': 'Archive or soft-delete employee records',
    'employee.manage': 'Create and update employee records',
    'attendance.read_self': 'Read own attendance records',
    'attendance.read_department': 'Read attendance of direct department scope',
    'attendance.read_all': 'Read attendance across the legal entity',
    'attendance.edit_logs': 'Edit attendance logs and manual corrections',
    'attendance.geofence_override': 'Override geofence and location restrictions',
    'attendance.review': 'Review and adjust attendance records',
    'leave.request': 'Request personal leave',
    'leave.approve': 'Approve leave requests for allowed scope',
    'leave.view_balances': 'View leave balances and leave history',
    'payroll.view': 'View payroll drafts and payroll dashboards',
    'payroll.finalize': 'Finalize and lock payroll payments',
    'payroll.bank_export': 'Export payroll bank transfer files',
    'compensation.read_all': 'Read salary and compensation data',
    'compensation.edit': 'Edit salary and compensation profiles',
    'payroll.export': 'Export payroll data',
    'device.manage': 'Manage biometric and attendance devices',
    'assets.read_self': 'Read own assigned asset records',
    'assets.read_all': 'Read asset records across the legal entity',
    'assets.manage': 'Manage asset inventory and assignments',
    'recruitment.read': 'Read recruitment pipeline data',
    'recruitment.create_vacancy': 'Create and publish vacancies',
    'recruitment.hire': 'Convert candidates into hired employees',
    'recruitment.manage': 'Manage recruitment workflow and vacancies',
    'settings.manage': 'Manage company-wide settings and policies',
}


def _slugify(value: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-')
    return slug or 'vacancy'


def _slugify_company(value: str | None) -> str:
    return _slugify(value or 'company')


def _safe_vacancy_schema(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if isinstance(value, dict):
        value = value.get('fields') or value.get('schema') or []
    if not isinstance(value, list):
        return []
    fields: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        key = str(item.get('key') or '').strip()
        label = str(item.get('label') or '').strip()
        if not key or not label:
            continue
        field_type = str(item.get('field_type') or 'text').strip().lower()
        if field_type not in {'text', 'textarea', 'email', 'phone', 'number', 'date'}:
            field_type = 'text'
        fields.append({
            'key': key,
            'label': label,
            'field_type': field_type,
            'required': bool(item.get('required', True)),
            'options': item.get('options') if isinstance(item.get('options'), list) else [],
        })
    return fields


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _middleware_event_ts_utc(value: datetime, device_timezone: str | None) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc)
    try:
        local_tz = ZoneInfo((device_timezone or '').strip() or 'Asia/Tbilisi')
    except ZoneInfoNotFoundError:
        local_tz = GEORGIA_TZ
    return value.replace(tzinfo=local_tz).astimezone(timezone.utc)


def _numeric_identity_key(value: str) -> str | None:
    clean = value.strip()
    if not clean or not clean.isdigit():
        return None
    return clean.lstrip('0') or '0'


def _render_application_success_html(company_name: str, vacancy_title: str, careers_url: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Application submitted</title>
  <style>
    body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; font-family: 'Noto Sans Georgian', 'Segoe UI', sans-serif; background: #f8fafc; color: #0f172a; }}
    main {{ width: min(640px, calc(100vw - 32px)); border: 1px solid #dbe3ef; border-radius: 28px; background: white; padding: 32px; box-shadow: 0 24px 70px rgba(15,23,42,0.12); }}
    .eyebrow {{ margin: 0 0 10px; color: #2563eb; text-transform: uppercase; letter-spacing: .18em; font-size: .76rem; font-weight: 800; }}
    h1 {{ margin: 0; font-size: clamp(1.8rem, 4vw, 2.5rem); }}
    p {{ color: #475569; line-height: 1.7; }}
    a {{ display: inline-flex; margin-top: 14px; border-radius: 16px; background: #1d4ed8; color: white; padding: 13px 18px; text-decoration: none; font-weight: 800; }}
  </style>
</head>
<body>
  <main>
    <p class="eyebrow">{escape(company_name)}</p>
    <h1>Application submitted</h1>
    <p>Your application for <strong>{escape(vacancy_title)}</strong> was received. Our HR team will review the CV and contact you if the next step is needed.</p>
    <a href="{escape(careers_url)}">View all vacancies</a>
  </main>
</body>
</html>"""


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _validate_email(value: str | None) -> str | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None
    if not EMAIL_PATTERN.match(cleaned):
        raise HTTPException(status_code=422, detail='გთხოვთ, შეიყვანოთ სწორი ელ-ფოსტის ფორმატი')
    return cleaned.lower()


def _validate_personal_number(value: str | None) -> str | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None
    digits = re.sub(r'\D', '', cleaned)
    if len(digits) != 11:
        raise HTTPException(status_code=422, detail='პირადი ნომერი უნდა შედგებოდეს 11 ციფრისგან')
    return digits


def _validate_phone(value: str | None) -> str | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None
    digits = re.sub(r'\D', '', cleaned)
    if len(digits) < 9 or len(digits) > 15:
        raise HTTPException(status_code=422, detail='ტელეფონის ნომერი უნდა შეიცავდეს 9-დან 15 ციფრამდე')
    return cleaned


def _normalize_salary_type(value: str | None) -> str:
    normalized = (value or 'monthly_fixed').strip().lower()
    if normalized not in {'monthly_fixed', 'hourly'}:
        raise HTTPException(status_code=422, detail='Salary type must be monthly_fixed or hourly')
    return normalized


def _temporary_password(length: int = 14) -> str:
    alphabet = string.ascii_letters + string.digits + '!@#$%'
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def _find_nested_value(payload: Any, keys: set[str]) -> Any | None:
    normalized_keys = {key.lower() for key in keys}
    if isinstance(payload, dict):
        for key, value in payload.items():
            if str(key).lower() in normalized_keys and value not in (None, ''):
                return value
            nested = _find_nested_value(value, keys)
            if nested not in (None, ''):
                return nested
    elif isinstance(payload, list):
        for item in payload:
            nested = _find_nested_value(item, keys)
            if nested not in (None, ''):
                return nested
    return None


def _parse_dahua_event_ts(raw_value: Any) -> datetime:
    if raw_value in (None, ''):
        return datetime.now(timezone.utc)
    text = str(raw_value).strip()
    for fmt in (
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%dT%H:%M:%S.%f',
        '%Y-%m-%dT%H:%M:%SZ',
        '%Y-%m-%dT%H:%M:%S%z',
    ):
        try:
            parsed = datetime.strptime(text, fmt)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    return datetime.now(timezone.utc)


def _infer_dahua_direction(payload: Any) -> str:
    raw_direction = _find_nested_value(payload, {'Direction', 'direction', 'AttendanceType', 'attendanceType', 'EventType', 'eventType'})
    text = str(raw_direction or '').strip().lower()
    if text in {'in', 'checkin', 'check_in', 'entry', 'enter'}:
        return 'in'
    if text in {'out', 'checkout', 'check_out', 'exit', 'leave'}:
        return 'out'
    return 'in'


def _normalize_middleware_direction(value: str | None) -> str:
    text = str(value or '').strip().lower()
    if text in {'in', 'checkin', 'check_in', 'clock_in', 'entry', 'enter'}:
        return 'in'
    if text in {'out', 'checkout', 'check_out', 'clock_out', 'exit', 'leave'}:
        return 'out'
    return 'unknown'


async def _append_capture_log(record: dict[str, Any]) -> None:
    log_path = BASE_DIR / 'tmp' / 'dahua-webhook-capture.log'
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def _write() -> None:
        with log_path.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + '\n')

    await asyncio.to_thread(_write)


async def _ensure_access_role(
    conn: Any,
    *,
    code: str,
    name_en: str,
    name_ka: str,
    description: str,
    permission_codes: list[str],
) -> UUID:
    role_id = await conn.fetchval(
        """
        INSERT INTO access_roles (code, name_en, name_ka, description)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (code) DO UPDATE
           SET name_en = EXCLUDED.name_en,
               name_ka = EXCLUDED.name_ka,
               description = EXCLUDED.description,
               updated_at = now()
        RETURNING id
        """,
        code,
        name_en,
        name_ka,
        description,
    )
    await conn.execute(
        """
        DELETE FROM access_role_permissions
         WHERE access_role_id = $1
           AND NOT (permission_code = ANY($2::text[]))
        """,
        role_id,
        permission_codes,
    )
    await conn.execute(
        """
        INSERT INTO access_role_permissions (access_role_id, permission_code)
        SELECT $1, permission_code
          FROM unnest($2::text[]) AS permission_code
        ON CONFLICT DO NOTHING
        """,
        role_id,
        permission_codes,
    )
    return role_id


async def _ensure_permission_catalog(conn: Any, permission_codes: list[str]) -> None:
    for permission_code in permission_codes:
        await conn.execute(
            """
            INSERT INTO permissions (code, description)
            VALUES ($1, $2)
            ON CONFLICT (code) DO UPDATE
               SET description = EXCLUDED.description
            """,
            permission_code,
            PERMISSION_DESCRIPTIONS.get(permission_code, permission_code.replace('.', ' ').replace('_', ' ')),
        )


async def _ensure_standard_access_roles(db: Database) -> None:
    async with db.pool.acquire() as conn:
        permission_codes = sorted(
            {
                permission_code
                for config in STANDARD_ACCESS_ROLE_PERMISSIONS.values()
                for permission_code in config['permissions']
            }
        )
        await _ensure_permission_catalog(conn, permission_codes)
        for code, config in STANDARD_ACCESS_ROLE_PERMISSIONS.items():
            await _ensure_access_role(
                conn,
                code=code,
                name_en=str(config['name_en']),
                name_ka=str(config['name_ka']),
                description=str(config['description']),
                permission_codes=list(config['permissions']),
            )


def _invite_link(token: str) -> str:
    return f"{settings.public_base_url}/ux/app?invite_token={token}"


def _derive_name_parts_from_email(email: str) -> tuple[str, str]:
    local_part = email.split('@', 1)[0].strip()
    if not local_part:
        return 'Invited', 'Employee'
    segments = [segment for segment in re.split(r'[._-]+', local_part) if segment]
    if not segments:
        return 'Invited', 'Employee'
    first_name = segments[0].capitalize()
    last_name = segments[1].capitalize() if len(segments) > 1 else 'Employee'
    return first_name[:80], last_name[:80]


def _invite_email_html(*, employee_name: str, invite_link: str, department_name: str | None, job_role_title: str | None) -> str:
    details = []
    if department_name:
        details.append(f'Department: {department_name}')
    if job_role_title:
        details.append(f'Role: {job_role_title}')
    detail_html = ''.join(f'<li style="margin:0 0 8px;">{value}</li>' for value in details)
    return f"""
    <div style="margin:0;padding:32px;background:#edf2ff;font-family:'Segoe UI',Arial,sans-serif;color:#172033;">
      <div style="max-width:640px;margin:0 auto;background:rgba(255,255,255,0.98);border-radius:28px;overflow:hidden;box-shadow:0 24px 80px rgba(15,23,42,0.16);">
        <div style="padding:24px 32px;background:linear-gradient(135deg,#1f2f50 0%,#243a63 58%,#f7fafc 58%,#ffffff 100%);color:#ffffff;">
          <div style="font-size:11px;letter-spacing:0.28em;text-transform:uppercase;opacity:0.75;">ITGS HR</div>
          <h1 style="margin:18px 0 0;font-size:30px;line-height:1.15;font-weight:700;">Complete your registration</h1>
        </div>
        <div style="padding:32px;">
          <p style="margin:0 0 16px;font-size:15px;line-height:1.7;color:#334155;">Hello {employee_name},</p>
          <p style="margin:0 0 16px;font-size:15px;line-height:1.7;color:#334155;">You have been invited to join ITGS HR. Use the secure link below to finish your registration, set your password, and activate your employee self-service portal.</p>
          {f'<ul style="margin:0 0 20px 20px;padding:0;font-size:14px;line-height:1.6;color:#475569;">{detail_html}</ul>' if detail_html else ''}
          <a href="{invite_link}" style="display:inline-block;padding:14px 22px;border-radius:14px;background:linear-gradient(135deg,#2563eb,#1d4ed8);color:#ffffff;text-decoration:none;font-weight:700;">Complete Registration</a>
          <p style="margin:24px 0 0;font-size:13px;line-height:1.6;color:#64748b;">This invitation stays active for {settings.invite_ttl_minutes} minutes.</p>
        </div>
      </div>
    </div>
    """.strip()


def _safe_file_name(value: str) -> str:
    return re.sub(r'[^a-zA-Z0-9._-]+', '_', value).strip('_') or 'upload.bin'


async def _resolve_company_profile_by_slug(db: Database, company_slug: str) -> dict[str, Any] | None:
    row = await db.fetchrow(
        """
        SELECT le.id,
               le.trade_name,
               le.legal_name,
               esc.logo_url,
               esc.logo_text,
               esc.primary_color,
               esc.linkedin_url,
               esc.facebook_url,
               esc.instagram_url,
               coalesce(td.subdomain, lower(regexp_replace(coalesce(le.trade_name, le.legal_name), '[^a-zA-Z0-9]+', '-', 'g'))) AS company_slug
          FROM legal_entities le
          LEFT JOIN entity_system_config esc ON esc.legal_entity_id = le.id
          LEFT JOIN tenant_domains td ON td.legal_entity_id = le.id AND td.is_primary = true AND td.is_active = true
         WHERE lower(coalesce(td.subdomain, regexp_replace(coalesce(le.trade_name, le.legal_name), '[^a-zA-Z0-9]+', '-', 'g'))) = lower($1)
         LIMIT 1
        """,
        company_slug,
    )
    return dict(row) if row else None


def _render_careers_page_html(company: dict[str, Any], vacancies: list[dict[str, Any]]) -> str:
    brand_color = company.get('primary_color') or '#1d4ed8'
    company_name = company.get('trade_name') or company.get('legal_name') or 'Careers'
    logo_url = company.get('logo_url')
    logo_text = company.get('logo_text') or company_name[:2].upper()
    social_links = [
        ('LinkedIn', company.get('linkedin_url')),
        ('Facebook', company.get('facebook_url')),
        ('Instagram', company.get('instagram_url')),
    ]
    vacancy_cards: list[str] = []
    for vacancy in vacancies:
        title = escape(vacancy['title_ka'] or vacancy['title_en'] or vacancy['posting_code'])
        department = escape(vacancy['department_name'] or '-')
        location = escape(vacancy['location_text'] or 'Georgia')
        description = escape(vacancy['public_description'] or vacancy['description'] or '')
        apply_action = f"/public/vacancies/{escape(vacancy['public_slug'])}/apply"
        external_form = vacancy.get('external_form_url')
        custom_fields: list[str] = []
        for field in _safe_vacancy_schema(vacancy.get('application_form_schema')):
            required = ' required' if field['required'] else ''
            field_name = f"answer__{field['key']}"
            label = escape(field['label'])
            if field['field_type'] == 'textarea':
                custom_fields.append(f'<label><span>{label}</span><textarea name="{escape(field_name)}"{required}></textarea></label>')
            else:
                input_type = {'email': 'email', 'phone': 'tel', 'number': 'number', 'date': 'date'}.get(field['field_type'], 'text')
                custom_fields.append(f'<label><span>{label}</span><input name="{escape(field_name)}" type="{input_type}"{required} /></label>')
        custom_fields_html = f'<div class="custom-fields">{"".join(custom_fields)}</div>' if custom_fields else ''
        if external_form:
            apply_block = f'<a class="apply-link" href="{escape(external_form)}" target="_blank" rel="noreferrer">Apply via external form</a>'
        else:
            apply_block = f"""
            <form class="apply-form" action="{apply_action}" method="post" enctype="multipart/form-data">
              <div class="apply-grid">
                <input name="first_name" placeholder="First name" required />
                <input name="last_name" placeholder="Last name" required />
                <input name="email" type="email" placeholder="Email" />
                <input name="phone" placeholder="Phone" />
                <input name="city" placeholder="City" />
                <input name="current_position" placeholder="Current position" />
              </div>
              <textarea name="notes" placeholder="Tell us about your experience"></textarea>
              {custom_fields_html}
              <label class="file-field">
                <span>Upload CV (PDF / DOCX)</span>
                <input name="cv_file" type="file" accept=".pdf,.doc,.docx,.txt" />
              </label>
              <button type="submit">Apply now</button>
            </form>
            """
        vacancy_cards.append(
            f"""
            <section id="{escape(vacancy['public_slug'])}" class="vacancy-card">
              <div class="vacancy-head">
                <div>
                  <p class="posting-code">{escape(vacancy['posting_code'])}</p>
                  <h2>{title}</h2>
                </div>
                <span class="status-pill">{escape(vacancy['employment_type'] or 'full_time').replace('_', ' ')}</span>
              </div>
              <div class="meta-row">
                <span>{department}</span>
                <span>{location}</span>
              </div>
              <p class="description">{description.replace(chr(10), '<br />')}</p>
              {apply_block}
            </section>
            """
        )
    social_html = ''.join(
        f'<a href="{escape(url)}" target="_blank" rel="noreferrer">{label}</a>'
        for label, url in social_links
        if url
    )
    logo_html = f'<img src="{escape(logo_url)}" alt="{escape(company_name)} logo" class="logo-image" />' if logo_url else f'<div class="logo-fallback">{escape(logo_text)}</div>'
    vacancy_html = ''.join(vacancy_cards) or '<section class="vacancy-card"><h2>No open vacancies right now</h2><p class="description">Please check back later for new opportunities.</p></section>'
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(company_name)} Careers</title>
  <style>
    :root {{ color-scheme: light; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: 'Noto Sans Georgian', 'Segoe UI', sans-serif; background: linear-gradient(180deg, #eff4ff 0%, #f8fafc 55%, #eef2ff 100%); color: #111827; }}
    a {{ color: {brand_color}; text-decoration: none; }}
    .shell {{ max-width: 1180px; margin: 0 auto; padding: 32px 20px 64px; }}
    .hero {{ position: relative; overflow: hidden; border-radius: 32px; background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 48%, #eff6ff 48.3%, #ffffff 100%); padding: 32px; box-shadow: 0 24px 80px rgba(15, 23, 42, 0.14); }}
    .hero-grid {{ display: grid; gap: 24px; grid-template-columns: minmax(0, 0.9fr) minmax(280px, 0.7fr); align-items: center; }}
    .brand-row {{ display: flex; align-items: center; gap: 18px; }}
    .logo-image, .logo-fallback {{ width: 72px; height: 72px; border-radius: 22px; object-fit: cover; background: rgba(255,255,255,0.12); display: flex; align-items: center; justify-content: center; color: white; font-weight: 800; font-size: 1.15rem; border: 1px solid rgba(255,255,255,0.2); }}
    .eyebrow {{ margin: 0 0 8px; color: #93c5fd; text-transform: uppercase; letter-spacing: 0.28em; font-size: 0.72rem; }}
    .hero h1 {{ margin: 0; color: white; font-size: clamp(2rem, 4vw, 3.4rem); }}
    .hero p {{ margin: 12px 0 0; color: #dbeafe; max-width: 560px; line-height: 1.65; }}
    .socials {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }}
    .socials a {{ border-radius: 999px; background: rgba(255,255,255,0.12); color: white; padding: 10px 14px; border: 1px solid rgba(255,255,255,0.16); font-size: 0.9rem; }}
    .hero-panel {{ border-radius: 24px; background: rgba(255,255,255,0.84); padding: 20px; backdrop-filter: blur(12px); border: 1px solid rgba(148,163,184,0.18); }}
    .hero-panel h2 {{ margin: 0; font-size: 1.1rem; }}
    .hero-panel p {{ margin: 8px 0 0; color: #475569; }}
    .vacancy-list {{ display: grid; gap: 20px; margin-top: 28px; }}
    .vacancy-card {{ border-radius: 28px; background: rgba(255,255,255,0.96); border: 1px solid rgba(148,163,184,0.22); box-shadow: 0 18px 60px rgba(15, 23, 42, 0.08); padding: 24px; }}
    .vacancy-head {{ display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }}
    .vacancy-head h2 {{ margin: 6px 0 0; font-size: 1.5rem; }}
    .posting-code {{ margin: 0; color: #64748b; text-transform: uppercase; letter-spacing: 0.16em; font-size: 0.75rem; }}
    .status-pill {{ border-radius: 999px; padding: 8px 12px; background: #dbeafe; color: #1d4ed8; font-weight: 700; font-size: 0.8rem; text-transform: capitalize; }}
    .meta-row {{ display: flex; flex-wrap: wrap; gap: 12px; margin-top: 14px; color: #475569; font-size: 0.92rem; }}
    .description {{ margin-top: 16px; color: #334155; line-height: 1.75; }}
    .apply-form {{ margin-top: 18px; display: grid; gap: 14px; }}
    .apply-grid {{ display: grid; gap: 12px; grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    .custom-fields {{ display: grid; gap: 12px; grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    .custom-fields label {{ display: grid; gap: 7px; color: #475569; font-size: .92rem; font-weight: 700; }}
    .apply-form input, .apply-form textarea {{ width: 100%; border-radius: 16px; border: 1px solid #cbd5e1; padding: 12px 14px; font: inherit; background: #fff; }}
    .apply-form textarea {{ min-height: 110px; resize: vertical; }}
    .file-field {{ display: grid; gap: 8px; color: #475569; }}
    .apply-form button, .apply-link {{ display: inline-flex; justify-content: center; align-items: center; border: none; border-radius: 16px; padding: 13px 18px; background: linear-gradient(135deg, {brand_color}, #0f172a); color: white; font-weight: 700; cursor: pointer; }}
    @media (max-width: 860px) {{
      .hero-grid, .apply-grid, .custom-fields {{ grid-template-columns: 1fr; }}
      .hero {{ padding: 24px; }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    <section class="hero">
      <div class="hero-grid">
        <div>
          <div class="brand-row">
            {logo_html}
            <div>
              <p class="eyebrow">Careers</p>
              <h1>{escape(company_name)}</h1>
            </div>
          </div>
          <p>Explore our open roles, apply directly online, and upload your CV so our recruitment pipeline can score and process your application right away.</p>
          <div class="socials">{social_html}</div>
        </div>
        <div class="hero-panel">
          <h2>Open opportunities</h2>
          <p>{len(vacancies)} published role(s) are currently visible on this career page.</p>
        </div>
      </div>
    </section>
    <div class="vacancy-list">{vacancy_html}</div>
  </main>
</body>
</html>"""


async def _store_upload(upload: UploadFile, target_dir: Path, prefix: str) -> tuple[str, int]:
    target_dir.mkdir(parents=True, exist_ok=True)
    file_name = _safe_file_name(upload.filename or 'attachment.bin')
    unique_name = f'{prefix}_{secrets.token_hex(8)}_{file_name}'
    destination = target_dir / unique_name
    content = await upload.read()
    destination.write_bytes(content)
    return f"/static/uploads/{target_dir.name}/{unique_name}", len(content)


def _store_upload_content(file_name: str, content: bytes, target_dir: Path, prefix: str) -> tuple[str, int]:
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_file_name(file_name or 'attachment.bin')
    unique_name = f'{prefix}_{secrets.token_hex(8)}_{safe_name}'
    destination = target_dir / unique_name
    destination.write_bytes(content)
    return f"/static/uploads/{target_dir.name}/{unique_name}", len(content)


def _normalize_extracted_text(value: str) -> str:
    return re.sub(r'\s+', ' ', value).strip()


def _extract_cv_text(file_name: str, content_type: str | None, content: bytes) -> str:
    lower_name = (file_name or '').lower()
    lower_content_type = (content_type or '').lower()
    try:
        if lower_name.endswith('.docx') or 'wordprocessingml' in lower_content_type:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                xml = archive.read('word/document.xml').decode('utf-8', errors='ignore')
            return _normalize_extracted_text(re.sub(r'<[^>]+>', ' ', xml))
        if lower_name.endswith('.txt') or lower_content_type.startswith('text/'):
            return _normalize_extracted_text(content.decode('utf-8', errors='ignore'))
        decoded = content.decode('latin-1', errors='ignore')
        printable = re.sub(r'[^A-Za-z0-9@._+#\-/ ]+', ' ', decoded)
        return _normalize_extracted_text(printable)
    except Exception:
        return ''


def _role_code_seed(title_en: str | None, title_ka: str) -> str:
    base = _slugify((title_en or '').strip())
    if base == 'vacancy':
        return f'ROLE-{secrets.token_hex(3).upper()}'
    return base.upper()[:48]


async def _unique_job_role_code(conn: Any, legal_entity_id: UUID, title_en: str | None, title_ka: str) -> str:
    base = _role_code_seed(title_en, title_ka)
    candidate = base
    suffix = 1
    while await conn.fetchval('SELECT 1 FROM job_roles WHERE legal_entity_id = $1 AND code = $2', legal_entity_id, candidate):
        suffix_text = f'-{suffix}'
        candidate = f'{base[: max(1, 48 - len(suffix_text))]}{suffix_text}'
        suffix += 1
    return candidate


def _department_code_seed(name: str) -> str:
    base = _slugify(name).replace('-', '_').upper()
    if not base or base == 'VACANCY':
        return f'DEPT_{secrets.token_hex(3).upper()}'
    return base[:48]


async def _unique_department_code(conn: Any, legal_entity_id: UUID, name: str) -> str:
    base = _department_code_seed(name)
    candidate = base
    suffix = 1
    while await conn.fetchval('SELECT 1 FROM departments WHERE legal_entity_id = $1 AND code = $2', legal_entity_id, candidate):
        suffix_text = f'_{suffix}'
        candidate = f'{base[: max(1, 48 - len(suffix_text))]}{suffix_text}'
        suffix += 1
    return candidate


async def _ensure_department(conn: Any, legal_entity_id: UUID, name: str | None) -> UUID | None:
    cleaned = _clean_text(name)
    if cleaned is None:
        return None
    existing = await conn.fetchval(
        """
        SELECT id
          FROM departments
         WHERE legal_entity_id = $1
           AND (lower(name_en) = lower($2) OR lower(name_ka) = lower($2))
         LIMIT 1
        """,
        legal_entity_id,
        cleaned,
    )
    if existing is not None:
        return existing
    code = await _unique_department_code(conn, legal_entity_id, cleaned)
    return await conn.fetchval(
        """
        INSERT INTO departments (legal_entity_id, code, name_en, name_ka)
        VALUES ($1, $2, $3, $4)
        RETURNING id
        """,
        legal_entity_id,
        code,
        cleaned,
        cleaned,
    )


async def _ensure_job_role(conn: Any, legal_entity_id: UUID, title: str | None) -> UUID | None:
    cleaned = _clean_text(title)
    if cleaned is None:
        return None
    existing = await conn.fetchval(
        """
        SELECT id
          FROM job_roles
         WHERE legal_entity_id = $1
           AND (lower(title_en) = lower($2) OR lower(title_ka) = lower($2))
         LIMIT 1
        """,
        legal_entity_id,
        cleaned,
    )
    if existing is not None:
        return existing
    code = await _unique_job_role_code(conn, legal_entity_id, cleaned, cleaned)
    return await conn.fetchval(
        """
        INSERT INTO job_roles (legal_entity_id, code, title_en, title_ka, is_managerial)
        VALUES ($1, $2, $3, $4, false)
        RETURNING id
        """,
        legal_entity_id,
        code,
        cleaned,
        cleaned,
    )


def _normalize_import_header(value: str | None) -> str:
    return re.sub(r'[^a-z0-9]+', '', (value or '').strip().lower())


def _normalize_import_row(row: dict[str | None, str | None]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in row.items():
        clean_key = _normalize_import_header(key)
        if clean_key:
            normalized[clean_key] = (value or '').strip()
    return normalized


def _import_value(row: dict[str, str], *aliases: str) -> str | None:
    for alias in aliases:
        value = row.get(_normalize_import_header(alias), '').strip()
        if value:
            return value
    return None


def _split_import_name(row: dict[str, str], row_number: int) -> tuple[str, str]:
    first_name = _clean_text(_import_value(row, 'first_name', 'firstname', 'given_name', 'givenname'))
    last_name = _clean_text(_import_value(row, 'last_name', 'lastname', 'surname', 'family_name', 'familyname'))
    if first_name and last_name:
        return first_name, last_name

    full_name = _clean_text(_import_value(row, 'full_name', 'fullname', 'name', 'user_name', 'username'))
    if full_name is None:
        raise HTTPException(status_code=422, detail=f'იმპორტის სტრიქონი {row_number}: თანამშრომლის სახელი ვერ მოიძებნა')

    parts = full_name.split()
    if len(parts) == 1:
        return parts[0], parts[0]
    return parts[0], ' '.join(parts[1:])


def _parse_import_decimal(value: str | None, row_number: int, field_label: str) -> Decimal | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None
    normalized = cleaned.replace(' ', '').replace(',', '')
    try:
        return Decimal(normalized)
    except InvalidOperation as exc:
        raise HTTPException(status_code=422, detail=f'იმპორტის სტრიქონი {row_number}: ველი "{field_label}" არასწორია') from exc


def _decode_import_file(raw_content: bytes) -> str:
    for encoding in ('utf-8-sig', 'utf-16', 'utf-16-le', 'utf-16-be', 'cp1251', 'cp1252', 'latin-1'):
        try:
            return raw_content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise HTTPException(status_code=422, detail='ფაილის კოდირება ვერ განისაზღვრა, გთხოვთ CSV შეინახოთ UTF-8 ფორმატში')


def _parse_attendance_import_ts(row: dict[str, str], row_number: int) -> datetime:
    direct_value = _clean_text(
        _import_value(
            row,
            'event_time',
            'event time',
            'datetime',
            'date time',
            'punch time',
            'punch_time',
            'time',
            'create time',
            'createtime',
        )
    )
    date_value = _clean_text(_import_value(row, 'date', 'event date', 'work date'))
    time_value = _clean_text(_import_value(row, 'hour', 'clock time'))
    candidate_values = [value for value in [direct_value, f'{date_value} {time_value}' if date_value and time_value else None] if value]
    formats = (
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d %H:%M',
        '%Y/%m/%d %H:%M:%S',
        '%Y/%m/%d %H:%M',
        '%d.%m.%Y %H:%M:%S',
        '%d.%m.%Y %H:%M',
        '%d/%m/%Y %H:%M:%S',
        '%d/%m/%Y %H:%M',
        '%m/%d/%Y %H:%M:%S',
        '%m/%d/%Y %H:%M',
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%dT%H:%M:%S.%f',
        '%Y-%m-%dT%H:%M:%SZ',
        '%Y-%m-%dT%H:%M:%S%z',
    )
    for candidate in candidate_values:
        text = candidate.strip()
        for fmt in formats:
            try:
                parsed = datetime.strptime(text, fmt)
                if parsed.tzinfo is None:
                    return parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)
            except ValueError:
                continue
    raise HTTPException(status_code=422, detail=f'SmartPSS attendance import row {row_number}: event time could not be parsed')


def _infer_attendance_import_direction(row: dict[str, str]) -> str:
    raw_direction = _clean_text(
        _import_value(
            row,
            'direction',
            'attendance type',
            'attendancetype',
            'event type',
            'eventtype',
            'status',
            'inout',
            'io status',
            'check type',
            'opendoor way',
            'open method',
        )
    )
    text = (raw_direction or '').strip().lower()
    if text in {'in', 'checkin', 'check in', 'entry', 'enter', 'doorin', 'signin'}:
        return 'in'
    if text in {'out', 'checkout', 'check out', 'exit', 'leave', 'doorout', 'signout'}:
        return 'out'
    if 'out' in text or 'exit' in text:
        return 'out'
    return 'in'


def _parse_time(value: str) -> datetime:
    return datetime.strptime(value, '%H:%M')


def _validate_shift_pattern_payload(payload: ShiftPatternUpsertRequest) -> None:
    if payload.pattern_type not in {'fixed_weekly', 'cycle'}:
        raise HTTPException(status_code=400, detail='ცვლის ტიპი უნდა იყოს fixed_weekly ან cycle')
    if not payload.segments:
        raise HTTPException(status_code=400, detail='მიუთითეთ მინიმუმ ერთი ცვლის სეგმენტი')
    if len({segment.day_index for segment in payload.segments}) != len(payload.segments):
        raise HTTPException(status_code=400, detail='day_index მნიშვნელობები უნიკალური უნდა იყოს')
    if payload.pattern_type == 'fixed_weekly' and any(segment.day_index > 7 for segment in payload.segments):
        raise HTTPException(status_code=400, detail='fixed_weekly ტიპი მხოლოდ 1-დან 7-მდე დღეებს უჭერს მხარს')


def _ensure_can_manage_shift_templates(actor) -> None:
    if bool({'ADMIN', 'TENANT_ADMIN'} & actor.role_codes):
        return
    raise HTTPException(status_code=403, detail='ცვლის შაბლონების მართვა ხელმისაწვდომია მხოლოდ სუპერ ადმინისტრატორისთვის')


def _normalized_device_registry_payload(payload: DeviceRegistryUpsertRequest) -> dict[str, Any]:
    brand = payload.brand.strip().lower()
    transport = payload.transport.strip().lower()
    device_type = (_clean_text(payload.device_type) or 'biometric_terminal').strip().lower()
    allowed_transports = {
        'zk': {'adms', 'adms_push', 'sdk_bridge', 'raw_socket'},
        'dahua': {'http_cgi'},
        'suprema': {'biostar'},
    }
    allowed_device_types = {'biometric_terminal', 'rfid_card_reader', 'access_control_gate'}
    expected_transports = allowed_transports.get(brand)
    if expected_transports is None:
        raise HTTPException(status_code=422, detail='მოწყობილობის ბრენდი არ არის მხარდაჭერილი')
    if transport not in expected_transports:
        raise HTTPException(status_code=422, detail='არჩეული ბრენდისთვის ტრანსპორტის ტიპი არასწორია')
    if device_type not in allowed_device_types:
        raise HTTPException(status_code=422, detail='მოწყობილობის ტიპი უნდა იყოს biometric_terminal, rfid_card_reader ან access_control_gate')

    device_name = _clean_text(payload.device_name)
    if not device_name:
        raise HTTPException(status_code=422, detail='მიუთითეთ მოწყობილობის სახელი')

    host = _clean_text(payload.host)
    if not host:
        raise HTTPException(status_code=422, detail='მიუთითეთ მოწყობილობის IP ან host')

    api_base_url = _clean_text(payload.api_base_url)
    if api_base_url is None and transport in {'http_cgi', 'biostar'}:
        scheme = 'https' if payload.port == 443 else 'http'
        api_base_url = f'{scheme}://{host}:{payload.port}'

    return {
        'brand': brand,
        'transport': transport,
        'device_type': device_type,
        'device_name': device_name,
        'model': _clean_text(payload.model) or 'Unknown Model',
        'serial_number': _clean_text(payload.serial_number) or 'N/A',
        'host': host,
        'port': payload.port,
        'api_base_url': api_base_url,
        'username': _clean_text(payload.username),
        'password_ciphertext': _clean_text(payload.password_ciphertext),
        'device_timezone': _clean_text(payload.device_timezone) or 'Asia/Tbilisi',
        'is_active': payload.is_active,
        'poll_interval_seconds': payload.poll_interval_seconds,
        'metadata': payload.metadata,
    }


def _segment_payload(segment: ShiftSegmentInput) -> tuple[int, int, bool]:
    start_dt = _parse_time(segment.start_time)
    end_dt = _parse_time(segment.end_time)
    crosses_midnight = end_dt <= start_dt
    if crosses_midnight:
        end_dt += timedelta(days=1)
    planned_minutes = int((end_dt - start_dt).total_seconds() // 60)
    if planned_minutes <= 0:
        raise HTTPException(status_code=400, detail='ცვლის სეგმენტის ხანგრძლივობა დადებითი უნდა იყოს')
    if segment.break_minutes > planned_minutes:
        raise HTTPException(status_code=400, detail='შესვენება ცვლის ხანგრძლივობას არ უნდა აღემატებოდეს')
    return planned_minutes, planned_minutes >= 1440 or crosses_midnight, crosses_midnight


def _escape_pdf_text(value: str) -> str:
    return value.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')


def _build_simple_payslip_pdf(lines: list[str]) -> bytes:
    stream_rows = ['BT', '/F1 11 Tf']
    y = 790
    for line in lines:
        stream_rows.append(f"1 0 0 1 50 {y} Tm ({_escape_pdf_text(line)}) Tj")
        y -= 16
    stream_rows.append('ET')
    content_stream = '\n'.join(stream_rows).encode('utf-8')
    objects = [
        b'1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n',
        b'2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n',
        b'3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n',
        b'4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n',
        f'5 0 obj << /Length {len(content_stream)} >> stream\n'.encode('utf-8') + content_stream + b'\nendstream endobj\n',
    ]
    output = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for obj in objects:
        offsets.append(len(output))
        output.extend(obj)
    xref_start = len(output)
    output.extend(f'xref\n0 {len(offsets)}\n'.encode('utf-8'))
    output.extend(b'0000000000 65535 f \n')
    for offset in offsets[1:]:
        output.extend(f'{offset:010d} 00000 n \n'.encode('utf-8'))
    output.extend(
        f'trailer << /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF'.encode('utf-8')
    )
    return bytes(output)


def _build_simple_table_pdf(title: str, lines: list[str]) -> bytes:
    return _build_simple_payslip_pdf([title, ''] + lines)


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


def _db_error_message(exc: Exception) -> str:
    text = str(exc).lower()
    if 'email' in text:
        return 'ეს ელ-ფოსტა უკვე დაკავებულია'
    if 'personal_number' in text:
        return 'ეს პირადი ნომერი უკვე გამოიყენება'
    if 'employee_number' in text:
        return 'ეს თანამშრომლის ნომერი უკვე არსებობს'
    if 'serial_number' in text:
        return 'ეს სერიული ნომერი უკვე რეგისტრირებულია'
    if 'username' in text:
        return 'ეს მომხმარებლის სახელი უკვე დაკავებულია'
    if 'device_name' in text:
        return 'ამ სახელით მოწყობილობა უკვე არსებობს'
    return 'მონაცემების შენახვა ვერ მოხერხდა. გადაამოწმეთ შეყვანილი მნიშვნელობები.'


def _strip_ip_port(value: str) -> str:
    if value.startswith('['):
        end = value.find(']')
        if end != -1:
            return value[1:end]
    if value.count(':') == 1 and value.rsplit(':', 1)[1].isdigit():
        return value.rsplit(':', 1)[0]
    return value


def _normalize_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    address = ipaddress.ip_address(value)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def _client_ip(request: Request) -> str | None:
    for source in (
        request.headers.get('x-forwarded-for'),
        request.headers.get('x-real-ip'),
        request.client.host if request.client else None,
    ):
        if not source:
            continue
        candidate = source.split(',')[0].strip()
        candidate = _strip_ip_port(candidate)
        if not candidate:
            continue
        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            continue
    return None


def _request_host_ip(request: Request) -> str | None:
    host_header = request.headers.get('x-forwarded-host') or request.headers.get('host')
    if not host_header:
        return None
    candidate = host_header.split(',')[0].strip()
    candidate = _strip_ip_port(candidate)
    if not candidate:
        return None
    if candidate.lower() == 'localhost':
        return '127.0.0.1'
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def _is_local_bridge_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        (isinstance(address, ipaddress.IPv4Address) and (address.is_private or address.is_loopback))
        or (isinstance(address, ipaddress.IPv6Address) and (address.is_private or address.is_loopback))
    )


def _distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius * c


DEFAULT_DASHBOARD_WIDGET_VISIBILITY = {
    'summary_cards': True,
    'analytics': True,
    'live_feed': True,
    'action_center': True,
    'upcoming_schedule': True,
    'celebrations': True,
}


def _hash_secret_value(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _normalize_dashboard_widget_visibility(value: dict[str, Any] | None) -> dict[str, bool]:
    normalized = dict(DEFAULT_DASHBOARD_WIDGET_VISIBILITY)
    if not isinstance(value, dict):
        return normalized
    for key in normalized:
        if key in value:
            normalized[key] = bool(value[key])
    return normalized


async def _load_entity_ui_policy(db: Database, legal_entity_id: UUID) -> dict[str, Any]:
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
    return {
        'company_dashboard_enabled': bool(row['company_dashboard_enabled']) if row and row['company_dashboard_enabled'] is not None else True,
        'payroll_dashboard_enabled': bool(row['payroll_dashboard_enabled']) if row and row['payroll_dashboard_enabled'] is not None else True,
        'dashboard_widget_visibility': _normalize_dashboard_widget_visibility(row['dashboard_widget_visibility']) if row else dict(DEFAULT_DASHBOARD_WIDGET_VISIBILITY),
    }


async def _ensure_company_dashboard_enabled(db: Database, legal_entity_id: UUID) -> None:
    ui_policy = await _load_entity_ui_policy(db, legal_entity_id)
    if not ui_policy['company_dashboard_enabled']:
        raise HTTPException(status_code=403, detail='Company dashboard is disabled in system settings')


async def _ensure_payroll_dashboard_enabled(db: Database, legal_entity_id: UUID) -> None:
    ui_policy = await _load_entity_ui_policy(db, legal_entity_id)
    if not ui_policy['payroll_dashboard_enabled']:
        raise HTTPException(status_code=403, detail='Payroll dashboard is disabled in system settings')


async def _resolve_worksite_location(
    db: Database,
    *,
    legal_entity_id: UUID,
    latitude: float | None,
    longitude: float | None,
) -> dict[str, Any]:
    if latitude is None or longitude is None:
        return {
            'worksite_id': None,
            'location_name': None,
            'location_source': None,
            'is_location_suspicious': False,
            'location_risk_reason': None,
        }
    rows = await db.fetch(
        """
        SELECT id, name, latitude, longitude, radius_meters
          FROM worksites
         WHERE legal_entity_id = $1
           AND is_active = true
        """,
        legal_entity_id,
    )
    nearest: dict[str, Any] | None = None
    nearest_distance: float | None = None
    for row in rows:
        distance = _distance_meters(float(row['latitude']), float(row['longitude']), latitude, longitude)
        if nearest_distance is None or distance < nearest_distance:
            nearest_distance = distance
            nearest = dict(row)
            nearest['distance_meters'] = distance
    if nearest and nearest_distance is not None and nearest_distance <= int(nearest['radius_meters']):
        return {
            'worksite_id': nearest['id'],
            'location_name': nearest['name'],
            'location_source': 'worksite_match',
            'is_location_suspicious': False,
            'location_risk_reason': None,
        }
    return {
        'worksite_id': nearest['id'] if nearest else None,
        'location_name': f'Unknown ({latitude:.5f}, {longitude:.5f})',
        'location_source': 'gps_coordinates',
        'is_location_suspicious': True,
        'location_risk_reason': 'Coordinates are outside configured worksites',
    }


async def _validate_web_punch(request: Request, db: Database, legal_entity_id: UUID, latitude: float | None, longitude: float | None) -> tuple[bool, str]:
    config = await db.fetchrow(
        """
        SELECT allowed_web_punch_ips, geofence_latitude, geofence_longitude, geofence_radius_meters
          FROM entity_system_config
         WHERE legal_entity_id = $1
        """,
        legal_entity_id,
    )
    if config is None:
        return False, 'ვებ დაფიქსირება ამ კომპანიისთვის ჯერ არ არის კონფიგურირებული'
    allowed_ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for item in (config['allowed_web_punch_ips'] or []):
        if not item:
            continue
        try:
            allowed_ips.append(_normalize_ip(str(item)))
        except ValueError:
            continue
    client_ip = _client_ip(request)
    if allowed_ips:
        if client_ip is None:
            return False, 'მომხმარებლის IP მისამართის განსაზღვრა ვერ მოხერხდა'
        try:
            normalized_client_ip = _normalize_ip(client_ip)
        except ValueError:
            return False, 'მომხმარებლის IP მისამართის განსაზღვრა ვერ მოხერხდა'
        if normalized_client_ip not in allowed_ips:
            request_host_ip = _request_host_ip(request)
            if request_host_ip is not None:
                try:
                    normalized_request_host_ip = _normalize_ip(request_host_ip)
                except ValueError:
                    normalized_request_host_ip = None
                if normalized_request_host_ip is not None and normalized_request_host_ip in allowed_ips and _is_local_bridge_ip(_normalize_ip(client_ip)):
                    return True, f'საოფისე IP დადასტურდა: {client_ip}'
            return False, 'თქვენ არ იმყოფებით ნებადართულ საოფისე ქსელში'
        return True, f'საოფისე IP დადასტურდა: {client_ip}'
    if config['geofence_latitude'] is not None and config['geofence_longitude'] is not None and config['geofence_radius_meters'] is not None:
        if latitude is None or longitude is None:
            return False, 'ლოკაციით დაფიქსირებისთვის საჭიროა GPS კოორდინატები'
        distance = _distance_meters(
            float(config['geofence_latitude']),
            float(config['geofence_longitude']),
            latitude,
            longitude,
        )
        if distance > int(config['geofence_radius_meters']):
            return False, 'თქვენ არ იმყოფებით ოფისის ტერიტორიაზე'
        return True, f'ოფისის გეოზონაში ხართ ({int(distance)}მ)'
    return False, 'ვებ დაფიქსირებისთვის არც IP სიაა და არც გეოზონა მითითებული'


async def _validate_web_punch_v2(
    request: Request,
    db: Database,
    legal_entity_id: UUID,
    latitude: float | None,
    longitude: float | None,
    gps_accuracy_meters: float | None,
) -> tuple[bool, str, dict[str, Any]]:
    config = await db.fetchrow(
        """
        SELECT allowed_web_punch_ips, geofence_latitude, geofence_longitude, geofence_radius_meters, gps_only_check_in
          FROM entity_system_config
         WHERE legal_entity_id = $1
        """,
        legal_entity_id,
    )
    location_details = await _resolve_worksite_location(
        db,
        legal_entity_id=legal_entity_id,
        latitude=latitude,
        longitude=longitude,
    )
    if config is None:
        return False, 'Web punch is not configured for this company yet', location_details
    if config['gps_only_check_in'] and (latitude is None or longitude is None):
        location_details['is_location_suspicious'] = True
        location_details['location_risk_reason'] = 'GPS coordinates are required by company policy'
        return False, 'GPS-only check-in is enabled for this company', location_details
    if gps_accuracy_meters is not None and gps_accuracy_meters > 250:
        location_details['is_location_suspicious'] = True
        location_details['location_risk_reason'] = 'GPS accuracy is too weak for a trusted punch'
    allowed_ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for item in (config['allowed_web_punch_ips'] or []):
        if not item:
            continue
        try:
            allowed_ips.append(_normalize_ip(str(item)))
        except ValueError:
            continue
    client_ip = _client_ip(request)
    if allowed_ips:
        if client_ip is None:
            return False, 'Client IP could not be determined', location_details
        try:
            normalized_client_ip = _normalize_ip(client_ip)
        except ValueError:
            return False, 'Client IP could not be normalized', location_details
        if normalized_client_ip not in allowed_ips:
            request_host_ip = _request_host_ip(request)
            if request_host_ip is not None:
                try:
                    normalized_request_host_ip = _normalize_ip(request_host_ip)
                except ValueError:
                    normalized_request_host_ip = None
                if normalized_request_host_ip is not None and normalized_request_host_ip in allowed_ips and _is_local_bridge_ip(_normalize_ip(client_ip)):
                    return True, f'Office IP validated: {client_ip}', location_details
            return False, 'You are not inside an allowed office network', location_details
        return True, f'Office IP validated: {client_ip}', location_details
    if config['geofence_latitude'] is not None and config['geofence_longitude'] is not None and config['geofence_radius_meters'] is not None:
        if latitude is None or longitude is None:
            return False, 'GPS coordinates are required for location-based punch validation', location_details
        distance = _distance_meters(
            float(config['geofence_latitude']),
            float(config['geofence_longitude']),
            latitude,
            longitude,
        )
        if distance > int(config['geofence_radius_meters']):
            location_details['is_location_suspicious'] = True
            location_details['location_risk_reason'] = 'Outside the configured geofence radius'
            return False, 'You are outside the configured office geofence', location_details
        return True, f'Inside office geofence ({int(distance)}m)', location_details
    if location_details.get('is_location_suspicious'):
        return False, str(location_details.get('location_risk_reason') or 'Suspicious location detected'), location_details
    return False, 'Neither office IPs nor geofence rules are configured for web punch validation', location_details


@asynccontextmanager
async def lifespan(app: FastAPI):
    admin_db = Database(settings.tenant_database_url or settings.database_url)
    await admin_db.connect()
    try:
        await ensure_runtime_schema(admin_db)
        await _ensure_standard_access_roles(admin_db)
        try:
            await ensure_mattermost_teams_for_all_tenants(admin_db)
        except Exception:
            pass
    finally:
        await admin_db.close()

    db = Database(settings.tenant_database_url or settings.database_url, runtime_role=settings.database_runtime_role)
    await db.connect()
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    LEAVE_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    CANDIDATE_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    app.state.db = db
    tasks: list[asyncio.Task[Any]] = []
    if settings.enable_device_workers:
        tasks.append(
            asyncio.create_task(
                device_ingestion_loop(db, settings.device_ingestion_interval_seconds),
                name='device-ingestion-loop',
            )
        )
    if settings.enable_ops_workers:
        tasks.extend(
            [
                asyncio.create_task(late_arrival_monitor_loop(db, settings.late_arrival_scan_interval_seconds), name='late-arrival-loop'),
                asyncio.create_task(celebration_monitor_loop(db, settings.celebration_scan_interval_seconds), name='celebration-loop'),
                asyncio.create_task(offboarding_monitor_loop(db, settings.offboarding_scan_interval_seconds), name='offboarding-loop'),
                asyncio.create_task(burnout_monitor_loop(db, settings.burnout_scan_interval_seconds), name='burnout-loop'),
            ]
        )
    if settings.enable_node_heartbeat:
        tasks.append(
            asyncio.create_task(
                node_heartbeat_loop(db, settings.monitoring_heartbeat_interval_seconds),
                name='node-heartbeat-loop',
            )
        )
    app.state.background_tasks = tasks
    try:
        yield
    finally:
        for task in app.state.background_tasks:
            task.cancel()
        for task in app.state.background_tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        await db.close()


app = FastAPI(title='ITGS HR', version='2.0.0', lifespan=lifespan)
app.middleware('http')(metrics_middleware)


@app.middleware('http')
async def tenant_context_middleware(request: Request, call_next):
    set_database_rls_context(legal_entity_id=None)
    db = getattr(request.app.state, 'db', None)
    tenant = None
    if db is not None:
        tenant = await resolve_request_tenant(db, request)
    request.state.tenant = tenant
    request.state.tenant_legal_entity_id = tenant['legal_entity_id'] if tenant and tenant.get('isolation_enabled', True) else None
    request.state.feature_flags = tenant['feature_flags'] if tenant else DEFAULT_FEATURE_FLAGS
    if request.state.tenant_legal_entity_id:
        set_database_rls_context(legal_entity_id=request.state.tenant_legal_entity_id)
    try:
        return await call_next(request)
    finally:
        set_database_rls_context(legal_entity_id=None)


if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['*'],
    )
if STATIC_DIR.exists():
    app.mount('/static', StaticFiles(directory=str(STATIC_DIR)), name='static')

app.include_router(AUTH_ROUTER)
app.include_router(ZK_ROUTER)
app.include_router(MATTERMOST_ROUTER)
app.include_router(ATS_ROUTER)
app.include_router(ASSETS_ROUTER)
app.include_router(PERFORMANCE_ROUTER)
app.include_router(ANALYTICS_ROUTER)
app.include_router(UX_ROUTER)
app.include_router(INTEGRATIONS_ROUTER)
app.include_router(MONITORING_ROUTER)




@app.exception_handler(AuthorizationError)
async def authorization_error_handler(request: Request, exc: AuthorizationError) -> JSONResponse:
    return JSONResponse(status_code=403, content={'detail': str(exc)})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    first_error = exc.errors()[0] if exc.errors() else {'msg': 'არასწორი მონაცემებია შეყვანილი'}
    return JSONResponse(status_code=422, content={'detail': str(first_error.get('msg') or 'არასწორი მონაცემებია შეყვანილი')})


@app.exception_handler(UniqueViolationError)
async def unique_violation_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=409, content={'detail': _db_error_message(exc)})


@app.exception_handler(PostgresError)
async def postgres_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={'detail': _db_error_message(exc)})


@app.exception_handler(DatabaseUnavailable)
async def database_unavailable_handler(request: Request, exc: DatabaseUnavailable) -> JSONResponse:
    return JSONResponse(status_code=503, content={'detail': 'ბაზასთან კავშირი დროებით მიუწვდომელია'})


@app.get('/', response_model=None)
async def root() -> Response:
    dashboard_index = STATIC_DIR / 'dashboard' / 'index.html'
    if dashboard_index.exists():
        return FileResponse(dashboard_index)
    return JSONResponse({
        'app': 'ITGS HR',
        'version': '2.0.0',
        'features': [
            'Attendance and payroll for Georgia',
            'Mattermost chat-ops approvals',
            'ATS with onboarding automation',
            'Asset lifecycle and offboarding',
            'OKR and 360 feedback',
            'Burnout and turnover analytics',
            'Multi-company / multi-server monitoring',
        ],
    })


@app.get('/api/info')
async def api_info() -> dict[str, object]:
    return {
        'app': 'ITGS HR',
        'version': '2.0.0',
        'features': [
            'Attendance and payroll for Georgia',
            'Mattermost chat-ops approvals',
            'ATS with onboarding automation',
            'Asset lifecycle and offboarding',
            'OKR and 360 feedback',
            'Burnout and turnover analytics',
            'Multi-company / multi-server monitoring',
        ],
    }


@app.get('/i18n/ka')
async def georgian_translations() -> dict[str, str]:
    return KA_TRANSLATIONS


@app.get('/employees')
async def employee_grid(
    request: Request,
    search: str | None = None,
    department_id: UUID | None = None,
    status_filter: str | None = None,
) -> list[dict[str, object]]:
    actor = await require_actor(request)
    ensure_permission(actor, 'employee.manage')
    db = get_db_from_request(request)
    rows = await db.fetch(
        """
        SELECT e.id,
               e.employee_number,
               e.first_name,
               e.last_name,
               e.email,
               e.mobile_phone,
               e.hire_date,
               e.employment_status::text AS employment_status,
               d.name_en AS department_name,
               jr.title_en AS job_title
          FROM employees e
          LEFT JOIN departments d ON d.id = e.department_id
          LEFT JOIN job_roles jr ON jr.id = e.job_role_id
         WHERE e.legal_entity_id = $1
           AND ($2::text IS NULL OR e.first_name ILIKE $2 OR e.last_name ILIKE $2 OR e.employee_number ILIKE $2 OR e.email::text ILIKE $2)
           AND ($3::uuid IS NULL OR e.department_id = $3)
           AND ($4::text IS NULL OR e.employment_status::text = $4)
         ORDER BY e.employee_number
         LIMIT 250
        """,
        actor.legal_entity_id,
        f'%{search.strip()}%' if search else None,
        department_id,
        status_filter,
    )
    return [dict(row) for row in rows]


@app.get('/employees/{employee_id}')
async def employee_detail(request: Request, employee_id: UUID) -> dict[str, object]:
    actor = await require_actor(request)
    db = get_db_from_request(request)
    row = await db.fetchrow(
        """
        SELECT e.id,
               e.legal_entity_id,
               e.employee_number,
               e.personal_number,
               e.first_name,
               e.last_name,
               e.email,
               e.mobile_phone,
               e.hire_date,
               e.termination_date,
               e.employment_status::text AS employment_status,
               e.default_device_user_id,
               d.id AS department_id,
               d.name_en AS department_name,
               jr.id AS job_role_id,
               jr.title_en AS job_title,
               m.id AS manager_employee_id,
               m.first_name || ' ' || m.last_name AS manager_name,
               p.file_url AS profile_photo_url,
               ec.policy_id AS pay_policy_id,
               ec.salary_type,
               ec.base_salary,
               ec.hourly_rate_override,
               ec.is_pension_participant
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
              SELECT policy_id, salary_type, base_salary, hourly_rate_override, is_pension_participant
                FROM employee_compensation
               WHERE employee_id = e.id
               ORDER BY effective_from DESC
               LIMIT 1
          ) ec ON true
         WHERE e.id = $1
           AND e.deleted_at IS NULL
        """,
        employee_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail='თანამშრომელი ვერ მოიძებნა')
    if row['legal_entity_id'] != actor.legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='თანამშრომელი სხვა იურიდიულ ერთეულს ეკუთვნის')
    if not can_view_employee_record(actor, employee_id, row['department_id']):
        raise HTTPException(status_code=403, detail='ამ თანამშრომლის ნახვის უფლება არ გაქვთ')
    payload = dict(row)
    payload['id'] = str(payload['id'])
    payload['legal_entity_id'] = str(payload['legal_entity_id'])
    payload['department_id'] = str(payload['department_id']) if payload['department_id'] else None
    payload['job_role_id'] = str(payload['job_role_id']) if payload['job_role_id'] else None
    payload['manager_employee_id'] = str(payload['manager_employee_id']) if payload['manager_employee_id'] else None
    can_view_salary = actor.has('compensation.read_all') or actor.has('employee.manage')
    payload['pay_policy_id'] = str(payload['pay_policy_id']) if can_view_salary and payload['pay_policy_id'] else None
    payload['salary_type'] = payload['salary_type'] if can_view_salary and payload['salary_type'] else None
    payload['base_salary'] = str(payload['base_salary']) if can_view_salary and payload['base_salary'] is not None else None
    payload['hourly_rate_override'] = str(payload['hourly_rate_override']) if can_view_salary and payload['hourly_rate_override'] is not None else None
    if actor.has('device.manage'):
        payload['synced_devices'] = await fetch_employee_synced_devices(db, employee_id)
    else:
        payload['synced_devices'] = []
    payload['permissions'] = {
        'can_edit': can_edit_employee_profiles(actor, row['department_id']),
        'can_view_salary': can_view_salary,
    }
    return payload


@app.post('/departments', status_code=status.HTTP_201_CREATED)
async def create_department(request: Request, payload: DepartmentCreateRequest) -> dict[str, str]:
    actor = await require_actor(request)
    ensure_permission(actor, 'employee.manage')
    if payload.legal_entity_id != actor.legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='Cross-tenant department creation is not allowed')
    db = get_db_from_request(request)
    name_ka = _clean_text(payload.name_ka)
    name_en = _clean_text(payload.name_en) or name_ka
    if not name_ka:
        raise HTTPException(status_code=422, detail='Department name is required')
    existing = await db.fetchrow(
        """
        SELECT id, name_en, name_ka, code
          FROM departments
         WHERE legal_entity_id = $1
           AND (
                lower(coalesce(name_ka, '')) = lower($2)
                OR lower(coalesce(name_en, '')) = lower($3)
           )
         LIMIT 1
        """,
        payload.legal_entity_id,
        name_ka,
        name_en,
    )
    if existing is not None:
        return {
            'id': str(existing['id']),
            'name_en': existing['name_en'] or name_en,
            'name_ka': existing['name_ka'] or name_ka,
            'code': existing['code'],
        }
    code = await _unique_department_code(db, payload.legal_entity_id, name_en or name_ka)
    department_id = await db.fetchval(
        """
        INSERT INTO departments (legal_entity_id, code, name_en, name_ka)
        VALUES ($1, $2, $3, $4)
        RETURNING id
        """,
        payload.legal_entity_id,
        code,
        name_en or name_ka,
        name_ka,
    )
    return {
        'id': str(department_id),
        'name_en': name_en or name_ka,
        'name_ka': name_ka,
        'code': code,
    }


@app.post('/job-roles', status_code=status.HTTP_201_CREATED)
async def create_job_role(request: Request, payload: JobRoleCreateRequest) -> dict[str, str]:
    actor = await require_actor(request)
    ensure_permission(actor, 'employee.manage')
    if payload.legal_entity_id != actor.legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='სხვა იურიდიული ერთეულის პოზიციის შექმნა აკრძალულია')

    db = get_db_from_request(request)
    title_ka = _clean_text(payload.title_ka)
    title_en = _clean_text(payload.title_en) or title_ka
    description = _clean_text(payload.description)
    if title_ka is None:
        raise HTTPException(status_code=422, detail='პოზიციის ქართული დასახელება სავალდებულოა')

    tx = await db.transaction()
    try:
        existing = await tx.connection.fetchrow(
            """
            SELECT id, title_en, title_ka
              FROM job_roles
             WHERE legal_entity_id = $1
               AND (
                    lower(title_ka) = lower($2)
                    OR ($3::text IS NOT NULL AND lower(title_en) = lower($3))
               )
             LIMIT 1
            """,
            payload.legal_entity_id,
            title_ka,
            title_en,
        )
        if existing is not None:
            await tx.commit()
            return {
                'id': str(existing['id']),
                'title_ka': existing['title_ka'],
                'title_en': existing['title_en'],
            }

        code = await _unique_job_role_code(tx.connection, payload.legal_entity_id, title_en, title_ka)
        role_id = await tx.connection.fetchval(
            """
            INSERT INTO job_roles (legal_entity_id, code, title_en, title_ka, description, is_managerial)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            payload.legal_entity_id,
            code,
            title_en,
            title_ka,
            description,
            payload.is_managerial,
        )
        await tx.commit()
    except Exception:
        await tx.rollback()
        raise

    return {'id': str(role_id), 'title_ka': title_ka, 'title_en': title_en or title_ka}


@app.post('/employees/import')
async def import_employees(request: Request, file: UploadFile = File(...), legal_entity_id: UUID | None = Form(default=None)) -> dict[str, int]:
    actor = await require_actor(request)
    if not can_import_employees(actor):
        raise HTTPException(status_code=403, detail='Employee import requires employee.import permission')

    target_legal_entity_id = legal_entity_id or actor.legal_entity_id
    if target_legal_entity_id != actor.legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='სხვა იურიდიული ერთეულისთვის თანამშრომლების იმპორტი აკრძალულია')

    file_name = (file.filename or '').lower()
    content_type = (file.content_type or '').lower()
    if not file_name.endswith('.csv') and 'csv' not in content_type and content_type not in {'text/plain', 'application/vnd.ms-excel'}:
        raise HTTPException(status_code=422, detail='SmartPSS იმპორტისთვის ატვირთეთ CSV ფაილი')

    raw_content = await file.read()
    if not raw_content:
        raise HTTPException(status_code=422, detail='იმპორტის ფაილი ცარიელია')

    decoded = _decode_import_file(raw_content)
    sniff_buffer = decoded[:4096]
    try:
        dialect = csv.Sniffer().sniff(sniff_buffer, delimiters=',;\t|')
    except csv.Error:
        dialect = csv.excel

    reader = csv.DictReader(io.StringIO(decoded), dialect=dialect)
    if not reader.fieldnames:
        raise HTTPException(status_code=422, detail='CSV სათაურები ვერ მოიძებნა')

    rows = list(reader)
    if not rows:
        raise HTTPException(status_code=422, detail='იმპორტის CSV ცარიელია')

    db = get_db_from_request(request)
    tx = await db.transaction()
    try:
        pay_policy_id = await tx.connection.fetchval(
            """
            SELECT id
              FROM pay_policies
             WHERE legal_entity_id = $1
             ORDER BY code
             LIMIT 1
            """,
            target_legal_entity_id,
        )
        if pay_policy_id is None:
            raise HTTPException(status_code=422, detail='იურიდიული ერთეულისთვის pay policy ვერ მოიძებნა')

        employee_role_id = await tx.connection.fetchval("SELECT id FROM access_roles WHERE code = 'EMPLOYEE'")
        if employee_role_id is None:
            raise HTTPException(status_code=500, detail='EMPLOYEE role ვერ მოიძებნა')

        created_count = 0
        updated_count = 0
        skipped_count = 0
        imported_refs: dict[str, UUID] = {}
        pending_managers: list[tuple[UUID, str]] = []

        for row_number, source_row in enumerate(rows, start=2):
            row = _normalize_import_row(source_row)
            if not any(value.strip() for value in row.values()):
                skipped_count += 1
                continue

            employee_number = _clean_text(
                _import_value(
                    row,
                    'employee_number',
                    'employee_no',
                    'employee_code',
                    'person_no',
                    'personnel_no',
                    'user_id',
                    'userid',
                    'person_id',
                )
            ) or f'IMP-{row_number:04d}'
            first_name, last_name = _split_import_name(row, row_number)
            email = _validate_email(_import_value(row, 'email', 'mail', 'email_address'))
            mobile_phone = _validate_phone(_import_value(row, 'mobile_phone', 'mobile', 'phone', 'telephone'))
            personal_number = _validate_personal_number(_import_value(row, 'personal_number', 'personalno', 'id_number', 'national_id'))
            department_id = await _ensure_department(tx.connection, target_legal_entity_id, _import_value(row, 'department', 'department_name', 'dept', 'group_name'))
            job_role_id = await _ensure_job_role(tx.connection, target_legal_entity_id, _import_value(row, 'job_title', 'position', 'job_role', 'role', 'title'))
            default_device_user_id = _clean_text(_import_value(row, 'device_user_id', 'deviceuserid', 'user_id', 'userid')) or employee_number
            manager_ref = _clean_text(_import_value(row, 'manager_number', 'manager_employee_number', 'manager_email', 'manager_name', 'reportsto', 'line_manager'))
            salary_amount = _parse_import_decimal(_import_value(row, 'base_salary', 'salary', 'monthly_salary'), row_number, 'salary')
            hourly_rate_override = _parse_import_decimal(_import_value(row, 'hourly_rate', 'hourly_rate_override'), row_number, 'hourly_rate')

            existing = await tx.connection.fetchrow(
                """
                SELECT e.id,
                       ec.policy_id,
                       ec.base_salary,
                       ec.hourly_rate_override,
                       ec.is_pension_participant
                  FROM employees e
                  LEFT JOIN LATERAL (
                      SELECT policy_id, base_salary, hourly_rate_override, is_pension_participant
                        FROM employee_compensation
                       WHERE employee_id = e.id
                       ORDER BY effective_from DESC
                       LIMIT 1
                  ) ec ON true
                 WHERE e.legal_entity_id = $1
                   AND (
                        e.employee_number = $2
                        OR ($3::text IS NOT NULL AND lower(e.email) = lower($3))
                   )
                 ORDER BY CASE WHEN e.employee_number = $2 THEN 0 ELSE 1 END
                 LIMIT 1
                """,
                target_legal_entity_id,
                employee_number,
                email,
            )

            if existing is None:
                employee_id = await tx.connection.fetchval(
                    """
                    INSERT INTO employees (
                        legal_entity_id, employee_number, personal_number, first_name, last_name,
                        email, mobile_phone, department_id, job_role_id, manager_employee_id,
                        hire_date, default_device_user_id
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NULL, current_date, $10)
                    RETURNING id
                    """,
                    target_legal_entity_id,
                    employee_number,
                    personal_number,
                    first_name,
                    last_name,
                    email,
                    mobile_phone,
                    department_id,
                    job_role_id,
                    default_device_user_id,
                )
                await tx.connection.execute(
                    """
                    INSERT INTO employee_compensation (
                        employee_id, policy_id, effective_from, salary_type, base_salary, hourly_rate_override, is_pension_participant
                    ) VALUES ($1, $2, current_date, 'monthly_fixed', $3, $4, true)
                    """,
                    employee_id,
                    pay_policy_id,
                    salary_amount if salary_amount is not None else Decimal('0'),
                    hourly_rate_override,
                )
                await tx.connection.execute(
                    """
                    INSERT INTO employee_access_roles (employee_id, access_role_id, assigned_by_employee_id)
                    VALUES ($1, $2, $3)
                    ON CONFLICT DO NOTHING
                    """,
                    employee_id,
                    employee_role_id,
                    actor.employee_id,
                )
                created_count += 1
            else:
                employee_id = existing['id']
                await tx.connection.execute(
                    """
                    UPDATE employees
                       SET personal_number = coalesce($2, personal_number),
                           first_name = $3,
                           last_name = $4,
                           email = coalesce($5, email),
                           mobile_phone = coalesce($6, mobile_phone),
                           department_id = coalesce($7, department_id),
                           job_role_id = coalesce($8, job_role_id),
                           default_device_user_id = coalesce($9, default_device_user_id),
                           updated_at = now()
                     WHERE id = $1
                    """,
                    employee_id,
                    personal_number,
                    first_name,
                    last_name,
                    email,
                    mobile_phone,
                    department_id,
                    job_role_id,
                    default_device_user_id,
                )

                next_policy_id = existing['policy_id'] or pay_policy_id
                next_base_salary = salary_amount if salary_amount is not None else (existing['base_salary'] if existing['base_salary'] is not None else Decimal('0'))
                next_hourly_rate = hourly_rate_override if hourly_rate_override is not None else existing['hourly_rate_override']
                next_pension = bool(existing['is_pension_participant']) if existing['is_pension_participant'] is not None else True
                await tx.connection.execute(
                    """
                    UPDATE employee_compensation
                       SET policy_id = $2,
                            salary_type = 'monthly_fixed',
                            base_salary = $3,
                            hourly_rate_override = $4,
                            is_pension_participant = $5,
                            updated_at = now()
                     WHERE employee_id = $1
                       AND effective_to IS NULL
                       AND effective_from = current_date
                         AND (
                              policy_id <> $2
                              OR salary_type <> 'monthly_fixed'
                              OR base_salary <> $3
                              OR coalesce(hourly_rate_override, 0) <> coalesce($4::numeric, 0)
                            OR is_pension_participant <> $5
                       )
                    """,
                    employee_id,
                    next_policy_id,
                    next_base_salary,
                    next_hourly_rate,
                    next_pension,
                )
                await tx.connection.execute(
                    """
                    UPDATE employee_compensation
                       SET effective_to = current_date - interval '1 day',
                           updated_at = now()
                     WHERE employee_id = $1
                       AND effective_to IS NULL
                       AND effective_from < current_date
                       AND (
                            policy_id <> $2
                            OR base_salary <> $3
                            OR coalesce(hourly_rate_override, 0) <> coalesce($4::numeric, 0)
                            OR is_pension_participant <> $5
                       )
                    """,
                    employee_id,
                    next_policy_id,
                    next_base_salary,
                    next_hourly_rate,
                    next_pension,
                )
                await tx.connection.execute(
                    """
                    INSERT INTO employee_compensation (
                        employee_id, policy_id, effective_from, salary_type, base_salary, hourly_rate_override, is_pension_participant
                    )
                    SELECT $1, $2, current_date, 'monthly_fixed', $3, $4, $5
                     WHERE NOT EXISTS (
                          SELECT 1
                            FROM employee_compensation
                           WHERE employee_id = $1
                             AND effective_to IS NULL
                             AND policy_id = $2
                             AND salary_type = 'monthly_fixed'
                             AND base_salary = $3
                             AND coalesce(hourly_rate_override, 0) = coalesce($4::numeric, 0)
                           AND is_pension_participant = $5
                     )
                    """,
                    employee_id,
                    next_policy_id,
                    next_base_salary,
                    next_hourly_rate,
                    next_pension,
                )
                updated_count += 1

            imported_refs[employee_number.lower()] = employee_id
            imported_refs[f'{first_name} {last_name}'.strip().lower()] = employee_id
            if email:
                imported_refs[email.lower()] = employee_id
            if manager_ref:
                pending_managers.append((employee_id, manager_ref))

        for employee_id, manager_ref in pending_managers:
            lookup = manager_ref.lower()
            manager_id = imported_refs.get(lookup)
            if manager_id is None:
                manager_id = await tx.connection.fetchval(
                    """
                    SELECT id
                      FROM employees
                     WHERE legal_entity_id = $1
                       AND (
                            employee_number = $2
                            OR lower(coalesce(email, '')) = lower($2)
                            OR lower(trim(first_name || ' ' || last_name)) = lower($2)
                       )
                     LIMIT 1
                    """,
                    target_legal_entity_id,
                    manager_ref,
                )
            if manager_id is None or manager_id == employee_id:
                continue
            await tx.connection.execute(
                'UPDATE employees SET manager_employee_id = $2, line_manager_id = $2, updated_at = now() WHERE id = $1',
                employee_id,
                manager_id,
            )

        await tx.commit()
    except Exception:
        await tx.rollback()
        raise

    return {
        'created_count': created_count,
        'updated_count': updated_count,
        'skipped_count': skipped_count,
    }


@app.post('/attendance/import-smartpss')
async def import_smartpss_attendance(request: Request, file: UploadFile = File(...)) -> dict[str, int]:
    actor = await require_actor(request)
    if not (actor.has('attendance.review') or actor.has('device.manage') or 'ADMIN' in actor.role_codes):
        raise HTTPException(status_code=403, detail='Attendance import requires attendance.review or device.manage permission')

    file_name = (file.filename or '').lower()
    content_type = (file.content_type or '').lower()
    if not file_name.endswith('.csv') and 'csv' not in content_type and content_type not in {'text/plain', 'application/vnd.ms-excel'}:
        raise HTTPException(status_code=422, detail='SmartPSS attendance import requires a CSV file')

    raw_content = await file.read()
    if not raw_content:
        raise HTTPException(status_code=422, detail='Attendance import file is empty')

    decoded = _decode_import_file(raw_content)
    sniff_buffer = decoded[:4096]
    try:
        dialect = csv.Sniffer().sniff(sniff_buffer, delimiters=',;\t|')
    except csv.Error:
        dialect = csv.excel

    reader = csv.DictReader(io.StringIO(decoded), dialect=dialect)
    if not reader.fieldnames:
        raise HTTPException(status_code=422, detail='CSV headers could not be detected')

    rows = list(reader)
    if not rows:
        raise HTTPException(status_code=422, detail='Attendance CSV is empty')

    db = get_db_from_request(request)
    default_device_id = await db.fetchval(
        """
        SELECT id
          FROM device_registry
         WHERE legal_entity_id = $1
           AND is_active = true
         ORDER BY CASE WHEN lower(brand::text) = 'dahua' THEN 0 ELSE 1 END, last_seen_at DESC NULLS LAST, created_at
         LIMIT 1
        """,
        actor.legal_entity_id,
    )

    imported_count = 0
    duplicate_count = 0
    unmatched_count = 0
    skipped_count = 0

    async with db.acquire() as conn:
        async with conn.transaction():
            await apply_current_database_rls_context(conn)
            for row_number, source_row in enumerate(rows, start=2):
                row = _normalize_import_row(source_row)
                if not any(value.strip() for value in row.values()):
                    skipped_count += 1
                    continue

                device_user_id = _clean_text(
                    _import_value(
                        row,
                        'person id',
                        'personid',
                        'user id',
                        'userid',
                        'employee number',
                        'employee_number',
                        'employee code',
                        'person no',
                        'person_no',
                        'card no',
                        'cardno',
                    )
                )
                if device_user_id is None:
                    skipped_count += 1
                    continue

                employee_row = await conn.fetchrow(
                    """
                    SELECT id
                      FROM employees
                     WHERE legal_entity_id = $1
                       AND deleted_at IS NULL
                       AND (
                            default_device_user_id = $2
                            OR employee_number = $2
                            OR personal_number = $2
                       )
                     LIMIT 1
                    """,
                    actor.legal_entity_id,
                    device_user_id,
                )
                if employee_row is None:
                    unmatched_count += 1
                    continue

                device_serial = _clean_text(
                    _import_value(
                        row,
                        'serial number',
                        'serialnumber',
                        'serial no',
                        'serialno',
                        'device serial',
                        'deviceserial',
                        'device id',
                        'deviceid',
                    )
                )
                device_id = default_device_id
                if device_serial is not None:
                    matched_device = await conn.fetchval(
                        """
                        SELECT id
                          FROM device_registry
                         WHERE legal_entity_id = $1
                           AND (
                                serial_number = $2
                                OR device_name = $2
                           )
                         ORDER BY is_active DESC, last_seen_at DESC NULLS LAST, created_at
                         LIMIT 1
                        """,
                        actor.legal_entity_id,
                        device_serial,
                    )
                    if matched_device is not None:
                        device_id = matched_device
                if device_id is None:
                    unmatched_count += 1
                    continue

                event_ts = _parse_attendance_import_ts(row, row_number)
                direction = _infer_attendance_import_direction(row)
                verify_mode = _clean_text(_import_value(row, 'verify mode', 'verifymode', 'open method', 'openmethod', 'method'))
                external_log_id = _clean_text(_import_value(row, 'record no', 'recordno', 'rec no', 'recno', 'transaction id', 'transactionid', 'event id', 'eventid'))
                inserted = await conn.fetchval(
                    """
                    INSERT INTO raw_attendance_logs (
                        device_id,
                        employee_id,
                        device_user_id,
                        event_ts,
                        direction,
                        verify_mode,
                        external_log_id,
                        raw_payload
                    )
                    VALUES ($1, $2, $3, $4, $5::attendance_direction, $6, $7, $8::jsonb)
                    ON CONFLICT (device_id, device_user_id, event_ts) DO NOTHING
                    RETURNING id
                    """,
                    device_id,
                    employee_row['id'],
                    device_user_id,
                    event_ts,
                    direction,
                    verify_mode,
                    external_log_id,
                    json.dumps({
                        'source': 'smartpss_csv_import',
                        'file_name': file.filename,
                        'row_number': row_number,
                        'row': row,
                    }, ensure_ascii=False),
                )
                if inserted is None:
                    duplicate_count += 1
                else:
                    await _apply_attendance_event_to_work_session(
                        conn,
                        employee_row['id'],
                        direction,
                        event_ts,
                        int(inserted),
                    )
                    await conn.execute(
                        'UPDATE raw_attendance_logs SET processed_at = now() WHERE id = $1',
                        int(inserted),
                    )
                    imported_count += 1

    await _append_capture_log(
        {
            'captured_at': datetime.utcnow().isoformat() + 'Z',
            'source': 'app.smartpss_import',
            'file_name': file.filename,
            'imported_count': imported_count,
            'duplicate_count': duplicate_count,
            'unmatched_count': unmatched_count,
            'skipped_count': skipped_count,
        }
    )

    return {
        'imported_count': imported_count,
        'duplicate_count': duplicate_count,
        'unmatched_count': unmatched_count,
        'skipped_count': skipped_count,
    }


@app.get('/employee-tools/import-template.csv')
@app.get('/employees/import-template.csv')
async def employee_import_template_csv(request: Request) -> Response:
    actor = await require_actor(request)
    if not can_import_employees(actor):
        raise HTTPException(status_code=403, detail='Employee import requires employee.import permission')
    headers = [
        'employee_number',
        'first_name',
        'last_name',
        'email',
        'mobile_phone',
        'personal_number',
        'department_name',
        'job_title',
        'manager_number',
        'base_salary',
        'hourly_rate',
        'device_user_id',
    ]
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    response = Response(content=buffer.getvalue(), media_type='text/csv')
    response.headers['Content-Disposition'] = 'attachment; filename=employee_import_template.csv'
    return response


@app.get('/employee-tools/import-template.xlsx')
@app.get('/employees/import-template.xlsx')
async def employee_import_template_xlsx(request: Request) -> Response:
    actor = await require_actor(request)
    if not can_import_employees(actor):
        raise HTTPException(status_code=403, detail='Employee import requires employee.import permission')
    headers = [
        'employee_number',
        'first_name',
        'last_name',
        'email',
        'mobile_phone',
        'personal_number',
        'department_name',
        'job_title',
        'manager_number',
        'base_salary',
        'hourly_rate',
        'device_user_id',
    ]
    rows: list[list[str]] = []
    workbook = _build_minimal_xlsx('Employees Import', headers, rows)
    response = Response(content=workbook, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response.headers['Content-Disposition'] = 'attachment; filename=employee_import_template.xlsx'
    return response


@app.get('/employee-tools/export')
@app.get('/employees/export')
async def export_employees(
    request: Request,
    format: str = 'csv',
    search: str | None = None,
    status_filter: str | None = None,
    department_id: UUID | None = None,
    email_contains: str | None = None,
    phone_contains: str | None = None,
    salary_min: Decimal | None = None,
    salary_max: Decimal | None = None,
    sort_by: str = 'employee_number',
    sort_direction: str = 'asc',
) -> Response:
    actor = await require_actor(request)
    if not can_export_employees(actor):
        raise HTTPException(status_code=403, detail='Employee export requires employee.export permission')

    db = get_db_from_request(request)
    view_salary = actor.has('compensation.read_all') or actor.has('employee.manage')
    directory_scope = employee_directory_scope(actor)
    managed_department_ids = list(actor.managed_department_ids)
    sortable_columns = {
        'employee_number': 'e.employee_number',
        'full_name': "e.first_name || ' ' || e.last_name",
        'department_name': 'd.name_en',
        'job_title': 'jr.title_en',
        'employment_status': 'e.employment_status::text',
        'hire_date': 'e.hire_date',
    }
    order_by = sortable_columns.get(sort_by, 'e.employee_number')
    direction = 'DESC' if sort_direction == 'desc' else 'ASC'
    q = f'%{search.strip()}%' if search else None
    em = f'%{email_contains.strip()}%' if email_contains else None
    ph = f'%{phone_contains.strip()}%' if phone_contains else None
    rows = await db.fetch(
        f"""
        SELECT e.employee_number,
               e.first_name,
               e.last_name,
               e.email,
               e.mobile_phone,
               e.hire_date,
               e.employment_status::text AS employment_status,
               d.name_en AS department_name,
               jr.title_en AS job_title,
               m.first_name || ' ' || m.last_name AS manager_name,
               coalesce(ec.base_salary, 0) AS base_salary,
               EXISTS (
                   SELECT 1
                     FROM auth_identities ai
                    WHERE ai.employee_id = e.id
                      AND ai.is_active = true
               ) AS has_login_access
          FROM employees e
          LEFT JOIN departments d ON d.id = e.department_id
          LEFT JOIN job_roles jr ON jr.id = e.job_role_id
          LEFT JOIN employees m ON m.id = coalesce(e.line_manager_id, e.manager_employee_id)
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
           AND ($10::numeric IS NULL OR $11::boolean = false OR coalesce(ec.base_salary, 0) >= $10)
           AND ($12::numeric IS NULL OR $11::boolean = false OR coalesce(ec.base_salary, 0) <= $12)
         ORDER BY {order_by} {direction}, e.employee_number ASC
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
        salary_min,
        view_salary,
        salary_max,
    )
    headers = ['Employee Number', 'First Name', 'Last Name', 'Email', 'Phone', 'Department', 'Job Title', 'Manager', 'Status', 'Hire Date', 'Login Access']
    if view_salary:
        headers.append('Base Salary')
    data_rows = []
    for row in rows:
        values = [
            row['employee_number'],
            row['first_name'],
            row['last_name'],
            row['email'] or '',
            row['mobile_phone'] or '',
            row['department_name'] or '',
            row['job_title'] or '',
            row['manager_name'] or '',
            row['employment_status'],
            row['hire_date'].isoformat() if row['hire_date'] else '',
            'Yes' if row['has_login_access'] else 'No',
        ]
        if view_salary:
            values.append(str(row['base_salary'] or 0))
        data_rows.append([str(value) for value in values])

    if format.lower() == 'xlsx':
        workbook = _build_minimal_xlsx('Employees', headers, data_rows)
        response = Response(content=workbook, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response.headers['Content-Disposition'] = 'attachment; filename=employees_export.xlsx'
        return response

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    writer.writerows(data_rows)
    response = Response(content=buffer.getvalue(), media_type='text/csv')
    response.headers['Content-Disposition'] = 'attachment; filename=employees_export.csv'
    return response


@app.post('/employees', status_code=status.HTTP_201_CREATED)
async def create_employee(request: Request, payload: EmployeeCreateRequest) -> dict[str, str]:
    actor = await require_actor(request)
    ensure_permission(actor, 'employee.manage')
    if payload.legal_entity_id != actor.legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='სხვა იურიდიული ერთეულისთვის თანამშრომლის შექმნა აკრძალულია')
    db = get_db_from_request(request)
    email = _validate_email(payload.email)
    personal_number = _validate_personal_number(payload.personal_number)
    mobile_phone = _validate_phone(payload.mobile_phone)
    salary_type = _normalize_salary_type(payload.salary_type)
    tx = await db.transaction()
    try:
        await apply_rls_context(tx.connection, actor)
        await ensure_employee_reference_tenant(
            tx.connection,
            payload.legal_entity_id,
            department_id=payload.department_id,
            job_role_id=payload.job_role_id,
            manager_employee_id=payload.manager_employee_id,
            pay_policy_id=payload.pay_policy_id,
        )
        employee_id = await tx.connection.fetchval(
            """
            INSERT INTO employees (
                legal_entity_id, employee_number, personal_number, first_name, last_name,
                email, mobile_phone, department_id, job_role_id, manager_employee_id,
                hire_date, default_device_user_id
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            RETURNING id
            """,
            payload.legal_entity_id,
            payload.employee_number,
            personal_number,
            payload.first_name,
            payload.last_name,
            email,
            mobile_phone,
            payload.department_id,
            payload.job_role_id,
            payload.manager_employee_id,
            payload.hire_date,
            payload.default_device_user_id,
        )
        await tx.connection.execute(
            'UPDATE employees SET line_manager_id = $2 WHERE id = $1',
            employee_id,
            payload.manager_employee_id,
        )
        await tx.connection.execute(
            """
            INSERT INTO employee_compensation (
                employee_id, policy_id, effective_from, salary_type, base_salary, hourly_rate_override, is_pension_participant
            ) VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            employee_id,
            payload.pay_policy_id,
            payload.hire_date,
            salary_type,
            payload.base_salary,
            payload.hourly_rate_override,
            payload.is_pension_participant,
        )
        roles = await tx.connection.fetch('SELECT id FROM access_roles WHERE code = ANY($1::citext[])', payload.access_role_codes)
        if len(roles) != len(set(code.upper() for code in payload.access_role_codes)):
            raise HTTPException(status_code=400, detail='ერთი ან რამდენიმე role კოდი არასწორია')
        await tx.connection.executemany(
            """
            INSERT INTO employee_access_roles (employee_id, access_role_id, assigned_by_employee_id)
            VALUES ($1, $2, $3)
            ON CONFLICT DO NOTHING
            """,
            [(employee_id, role['id'], actor.employee_id) for role in roles],
        )
        await tx.commit()
    except Exception:
        await tx.rollback()
        raise

    await add_employee_to_all_devices(db, employee_id)
    return {'employee_id': str(employee_id)}


@app.post('/employees/invite', status_code=status.HTTP_201_CREATED)
async def invite_employee(request: Request, payload: EmployeeInviteRequest) -> dict[str, str]:
    actor = await require_actor(request)
    ensure_permission(actor, 'employee.manage')
    if payload.legal_entity_id != actor.legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='Inviting employees for another legal entity is not allowed')
    db = get_db_from_request(request)
    email = _validate_email(payload.email)
    if not email:
        raise HTTPException(status_code=422, detail='Email is required')
    salary_type = _normalize_salary_type(payload.salary_type)
    normalized_username = email.lower()
    existing_identity = await db.fetchval('SELECT employee_id FROM auth_identities WHERE username = $1 LIMIT 1', normalized_username)
    if existing_identity is not None:
        raise HTTPException(status_code=409, detail='This email already has login access')

    tx = await db.transaction()
    try:
        await apply_rls_context(tx.connection, actor)
        await ensure_employee_reference_tenant(
            tx.connection,
            payload.legal_entity_id,
            department_id=payload.department_id,
            job_role_id=payload.job_role_id,
            manager_employee_id=payload.manager_employee_id,
            pay_policy_id=payload.pay_policy_id,
        )
        employee_number = await _generate_employee_number(tx.connection, payload.legal_entity_id)
        first_name, last_name = _derive_name_parts_from_email(email)
        employee_id = await tx.connection.fetchval(
            """
            INSERT INTO employees (
                legal_entity_id, employee_number, personal_number, first_name, last_name,
                email, mobile_phone, department_id, job_role_id, manager_employee_id,
                line_manager_id, hire_date, employment_status, default_device_user_id
            )
            VALUES ($1, $2, NULL, $3, $4, $5, NULL, $6, $7, $8, $8, current_date, 'draft', $2)
            RETURNING id
            """,
            payload.legal_entity_id,
            employee_number,
            first_name,
            last_name,
            email,
            payload.department_id,
            payload.job_role_id,
            payload.manager_employee_id,
        )
        await tx.connection.execute(
            """
            INSERT INTO employee_compensation (
                employee_id, policy_id, effective_from, salary_type, base_salary, hourly_rate_override, is_pension_participant
            ) VALUES ($1, $2, current_date, $3, $4, NULL, $5)
            """,
            employee_id,
            payload.pay_policy_id,
            salary_type,
            payload.base_salary,
            payload.is_pension_participant,
        )
        await tx.connection.execute(
            """
            INSERT INTO auth_identities (employee_id, username, password_hash, is_active, updated_at)
            VALUES ($1, $2, $3, false, now())
            ON CONFLICT (username) DO UPDATE
               SET employee_id = EXCLUDED.employee_id,
                   password_hash = EXCLUDED.password_hash,
                   is_active = false,
                   updated_at = now()
            """,
            employee_id,
            normalized_username,
            hash_password(secrets.token_urlsafe(24)),
        )
        role_id = await tx.connection.fetchval(
            "SELECT id FROM access_roles WHERE code = 'ESS_EMPLOYEE' LIMIT 1"
        )
        if role_id is None:
            raise HTTPException(status_code=500, detail='ESS employee role is not configured')
        await tx.connection.execute(
            """
            INSERT INTO employee_access_roles (employee_id, access_role_id, assigned_by_employee_id)
            VALUES ($1, $2, $3)
            ON CONFLICT DO NOTHING
            """,
            employee_id,
            role_id,
            actor.employee_id,
        )
        invite_token = secrets.token_urlsafe(32)
        await tx.connection.execute(
            """
            INSERT INTO auth_invites (
                employee_id, legal_entity_id, username, invite_token, temp_password_hash,
                recipient_email, sent_via, expires_at, created_by_employee_id, updated_at
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, 'email',
                now() + make_interval(mins => $7), $8, now()
            )
            """,
            employee_id,
            payload.legal_entity_id,
            normalized_username,
            invite_token,
            hash_password(secrets.token_urlsafe(24)),
            email,
            settings.invite_ttl_minutes,
            actor.employee_id,
        )
        await tx.commit()
    except Exception:
        await tx.rollback()
        raise

    department_name = await db.fetchval(
        'SELECT coalesce(name_ka, name_en) FROM departments WHERE id = $1',
        payload.department_id,
    )
    job_role_title = await db.fetchval(
        'SELECT coalesce(title_ka, title_en) FROM job_roles WHERE id = $1',
        payload.job_role_id,
    )
    invite_link = _invite_link(invite_token)
    invite_email_status = 'not_configured'
    invite_email_error: str | None = None
    if settings.smtp_host:
        try:
            await send_and_log_email(
                db,
                legal_entity_id=payload.legal_entity_id,
                event_type='employee_invite',
                event_key=str(employee_id),
                to_email=email,
                subject='Complete your HRMS registration',
                body_text=(
                    f"Hello {first_name} {last_name},\n\n"
                    f"You have been invited to join HRMS.\n"
                    f"Complete your registration here: {invite_link}\n\n"
                    f"The invitation remains valid for {settings.invite_ttl_minutes} minutes."
                ),
                body_html=_invite_email_html(
                    employee_name=f'{first_name} {last_name}',
                    invite_link=invite_link,
                    department_name=department_name,
                    job_role_title=job_role_title,
                ),
                extra_payload={'employee_id': str(employee_id), 'username': normalized_username},
            )
            invite_email_status = 'sent'
        except Exception as exc:
            invite_email_status = 'failed'
            invite_email_error = str(exc)
    return {
        'employee_id': str(employee_id),
        'username': normalized_username,
        'invite_link': invite_link,
        'invite_email_status': invite_email_status,
        'invite_email_error': invite_email_error,
    }


@app.post('/api/v1/invites', status_code=status.HTTP_201_CREATED)
async def invite_employee_api_v1_alias(request: Request, payload: EmployeeInviteRequest) -> dict[str, str]:
    """Stable public alias for POST /employees/invite (same behaviour and auth)."""
    return await invite_employee(request, payload)


@app.put('/employees/{employee_id}')
async def update_employee(request: Request, employee_id: UUID, payload: EmployeeUpdateRequest) -> dict[str, str]:
    actor = await require_actor(request)
    db = get_db_from_request(request)
    email = _validate_email(payload.email)
    mobile_phone = _validate_phone(payload.mobile_phone)
    can_manage_compensation = actor.has('compensation.read_all') or actor.has('employee.manage')
    tx = await db.transaction()
    try:
        await apply_rls_context(tx.connection, actor)
        employee_row = await tx.connection.fetchrow(
            """
                SELECT e.legal_entity_id,
                       e.department_id,
                       ec.policy_id,
                       ec.salary_type,
                       ec.base_salary,
                       ec.hourly_rate_override,
                       ec.is_pension_participant
                FROM employees e
            LEFT JOIN LATERAL (
                SELECT policy_id, salary_type, base_salary, hourly_rate_override, is_pension_participant
                  FROM employee_compensation
                 WHERE employee_id = e.id
                 ORDER BY effective_from DESC
                 LIMIT 1
          ) ec ON true
             WHERE e.id = $1
               AND e.deleted_at IS NULL
            """,
            employee_id,
        )
        if employee_row is None:
            raise HTTPException(status_code=404, detail='თანამშრომელი ვერ მოიძებნა')
        if employee_row['legal_entity_id'] != actor.legal_entity_id and 'ADMIN' not in actor.role_codes:
            raise HTTPException(status_code=403, detail='თანამშრომელი სხვა იურიდიულ ერთეულს ეკუთვნის')
        if not can_edit_employee_profiles(actor, employee_row['department_id']):
            raise HTTPException(status_code=403, detail='You are not allowed to edit this employee profile')
        next_pay_policy_id = payload.pay_policy_id if can_manage_compensation else employee_row['policy_id']
        next_salary_type = _normalize_salary_type(payload.salary_type if can_manage_compensation and payload.salary_type else employee_row['salary_type'])
        next_base_salary = payload.base_salary if can_manage_compensation else employee_row['base_salary']
        next_hourly_rate = payload.hourly_rate_override if can_manage_compensation else employee_row['hourly_rate_override']
        next_pension = payload.is_pension_participant if can_manage_compensation else employee_row['is_pension_participant']
        if next_pay_policy_id is None or next_base_salary is None:
            raise HTTPException(status_code=422, detail='Compensation updates require pay policy and base salary')
        await ensure_employee_reference_tenant(
            tx.connection,
            employee_row['legal_entity_id'],
            department_id=payload.department_id,
            job_role_id=payload.job_role_id,
            manager_employee_id=payload.manager_employee_id,
            pay_policy_id=next_pay_policy_id,
        )
        await tx.connection.execute(
            """
            UPDATE employees
               SET first_name = $2,
                   last_name = $3,
                   email = $4,
                   mobile_phone = $5,
                   department_id = $6,
                   job_role_id = $7,
                   manager_employee_id = $8,
                   default_device_user_id = $9,
                   updated_at = now()
             WHERE id = $1
            """,
            employee_id,
            payload.first_name,
            payload.last_name,
            email,
            mobile_phone,
            payload.department_id,
            payload.job_role_id,
            payload.manager_employee_id,
            payload.default_device_user_id,
        )
        await tx.connection.execute(
            'UPDATE employees SET line_manager_id = $2, updated_at = now() WHERE id = $1',
            employee_id,
            payload.manager_employee_id,
        )
        await tx.connection.execute(
            """
            UPDATE employee_compensation
               SET policy_id = $2,
                   salary_type = $3,
                   base_salary = $4,
                   hourly_rate_override = $5,
                   is_pension_participant = $6,
                   updated_at = now()
             WHERE employee_id = $1
               AND effective_to IS NULL
               AND effective_from = current_date
               AND (
                    policy_id <> $2
                     OR salary_type <> $3
                     OR base_salary <> $4
                     OR coalesce(hourly_rate_override, 0) <> coalesce($5::numeric, 0)
                     OR is_pension_participant <> $6
                )
            """,
            employee_id,
            next_pay_policy_id,
            next_salary_type,
            next_base_salary,
            next_hourly_rate,
            next_pension,
        )
        await tx.connection.execute(
            """
            UPDATE employee_compensation
               SET effective_to = current_date - interval '1 day',
                    updated_at = now()
              WHERE employee_id = $1
                AND effective_to IS NULL
                AND effective_from < current_date
                AND (
                    policy_id <> $2
                    OR salary_type <> $3
                    OR base_salary <> $4
                    OR coalesce(hourly_rate_override, 0) <> coalesce($5::numeric, 0)
                    OR is_pension_participant <> $6
                )
            """,
            employee_id,
            next_pay_policy_id,
            next_salary_type,
            next_base_salary,
            next_hourly_rate,
            next_pension,
        )
        await tx.connection.execute(
            """
            INSERT INTO employee_compensation (
                employee_id, policy_id, effective_from, salary_type, base_salary, hourly_rate_override, is_pension_participant
            )
            SELECT $1, $2, current_date, $3, $4, $5, $6
             WHERE NOT EXISTS (
                  SELECT 1
                    FROM employee_compensation
                   WHERE employee_id = $1
                     AND effective_to IS NULL
                     AND policy_id = $2
                     AND salary_type = $3
                     AND base_salary = $4
                     AND coalesce(hourly_rate_override, 0) = coalesce($5::numeric, 0)
                     AND is_pension_participant = $6
            )
            """,
            employee_id,
            next_pay_policy_id,
            next_salary_type,
            next_base_salary,
            next_hourly_rate,
            next_pension,
        )
        await tx.commit()
    except Exception:
        await tx.rollback()
        raise
    return {'status': 'updated'}


@app.post('/employees/{employee_id}/profile-photo')
async def upload_employee_profile_photo(request: Request, employee_id: UUID, photo: UploadFile = File(...)) -> dict[str, str]:
    actor = await require_actor(request)
    ensure_permission(actor, 'employee.manage')
    db = get_db_from_request(request)
    employee_row = await db.fetchrow('SELECT legal_entity_id FROM employees WHERE id = $1', employee_id)
    if employee_row is None:
        raise HTTPException(status_code=404, detail='თანამშრომელი ვერ მოიძებნა')
    if employee_row['legal_entity_id'] != actor.legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='თანამშრომელი სხვა იურიდიულ ერთეულს ეკუთვნის')

    content_type = (photo.content_type or '').lower()
    file_name = (photo.filename or '').lower()
    if content_type not in {'image/jpeg', 'image/jpg'} and not file_name.endswith(('.jpg', '.jpeg')):
        raise HTTPException(status_code=422, detail='Dahua-სთვის პროფილის ფოტო უნდა იყოს JPG ან JPEG ფორმატში')

    file_url, file_size = await _store_upload(photo, PROFILE_UPLOADS_DIR, f'employee_{employee_id}')
    await db.execute(
        """
        INSERT INTO employee_file_uploads (
            employee_id, legal_entity_id, file_category, file_name, file_url,
            content_type, file_size, created_by_employee_id
        )
        VALUES ($1, $2, 'profile_photo', $3, $4, $5, $6, $7)
        """,
        employee_id,
        employee_row['legal_entity_id'],
        _safe_file_name(photo.filename or 'profile.jpg'),
        file_url,
        photo.content_type,
        file_size,
        actor.employee_id,
    )
    return {'photo_url': file_url}


@app.post('/employees/{employee_id}/device-sync')
async def sync_employee_to_devices(request: Request, employee_id: UUID, payload: EmployeeDeviceSyncRequest | None = None) -> dict[str, object]:
    actor = await require_actor(request)
    ensure_permission(actor, 'device.manage')
    db = get_db_from_request(request)
    legal_entity_id = await db.fetchval(
        'SELECT legal_entity_id FROM employees WHERE id = $1 AND deleted_at IS NULL',
        employee_id,
    )
    if legal_entity_id is None:
        raise HTTPException(status_code=404, detail='თანამშრომელი ვერ მოიძებნა')
    if legal_entity_id != actor.legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='თანამშრომელი სხვა იურიდიულ ერთეულს ეკუთვნის')
    desired_device_ids = payload.device_ids if payload is not None else []
    try:
        result = await sync_employee_device_assignments(db, employee_id, desired_device_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await _log_audit_event(
        db,
        actor_employee_id=actor.employee_id,
        legal_entity_id=actor.legal_entity_id,
        action_code='employee.hardware_sync.updated',
        target_employee_id=employee_id,
        details=result,
    )
    return {
        'status': 'queued',
        'added_device_count': len(result.get('added_device_ids', [])),
        'removed_device_count': len(result.get('removed_device_ids', [])),
        'current_device_ids': result.get('current_device_ids', [str(item) for item in desired_device_ids]),
        'requested_device_count': int(result.get('requested', 0)),
        'queued_upsert_count': int(result.get('queued_upserts', 0)),
        'queued_delete_count': int(result.get('queued_deletes', 0)),
    }


@app.delete('/employees/{employee_id}/device-access', status_code=status.HTTP_204_NO_CONTENT)
async def revoke_device_access(request: Request, employee_id: UUID) -> Response:
    actor = await require_actor(request)
    ensure_permission(actor, 'employee.manage')
    db = get_db_from_request(request)
    await delete_employee_from_all_devices(db, employee_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post('/employees/{employee_id}/daily-status')
async def set_daily_status(request: Request, employee_id: UUID, payload: EmployeeDailyStatusRequest) -> dict[str, str]:
    actor = await require_actor(request)
    if employee_id != actor.employee_id:
        ensure_permission(actor, 'employee.manage')
    db = get_db_from_request(request)
    await db.execute(
        """
        INSERT INTO employee_status_calendar (employee_id, status_date, work_mode, note, created_by_employee_id)
        VALUES ($1, $2, $3::work_mode, $4, $5)
        ON CONFLICT (employee_id, status_date) DO UPDATE
           SET work_mode = EXCLUDED.work_mode,
               note = EXCLUDED.note,
               created_by_employee_id = EXCLUDED.created_by_employee_id,
               updated_at = now()
        """,
        employee_id,
        payload.status_date,
        payload.work_mode,
        payload.note,
        actor.employee_id,
    )
    return {'status': 'saved'}


@app.post('/employees/{employee_id}/chat-account')
async def link_chat_account(request: Request, employee_id: UUID, payload: ChatAccountLinkRequest) -> dict[str, str]:
    actor = await require_actor(request)
    if employee_id != actor.employee_id:
        ensure_permission(actor, 'employee.manage')
    db = get_db_from_request(request)
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
        payload.mattermost_user_id,
        payload.mattermost_username,
    )
    return {'status': 'linked'}


@app.post('/employees/{employee_id}/grant-access')
async def grant_employee_access(
    request: Request,
    employee_id: UUID,
    payload: EmployeeAccessGrantRequest | None = None,
) -> dict[str, str]:
    actor = await require_actor(request)
    ensure_permission(actor, 'employee.manage')
    db = get_db_from_request(request)
    employee = await db.fetchrow(
        """
        SELECT e.id,
               e.legal_entity_id,
               e.employee_number,
               e.first_name,
               e.last_name,
               e.email,
               coalesce(eca.mattermost_username, '') AS mattermost_username
         FROM employees e
         LEFT JOIN employee_chat_accounts eca ON eca.employee_id = e.id
         WHERE e.id = $1
           AND e.deleted_at IS NULL
        """,
        employee_id,
    )
    if employee is None:
        raise HTTPException(status_code=404, detail='თანამშრომელი ვერ მოიძებნა')
    if employee['legal_entity_id'] != actor.legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='სხვა იურიდიული ერთეულის თანამშრომელზე წვდომის გაცემა აკრძალულია')

    preferred_username = _clean_text(payload.username if payload else None)
    default_username = (
        preferred_username
        or _clean_text(employee['email'])
        or str(employee['employee_number']).strip().lower()
    )
    if not default_username:
        raise HTTPException(status_code=400, detail='მომხმარებლის სახელი ვერ განისაზღვრა')
    existing_identity = await db.fetchrow(
        'SELECT employee_id FROM auth_identities WHERE username = $1 LIMIT 1',
        default_username,
    )
    if existing_identity is not None and existing_identity['employee_id'] != employee_id:
        raise HTTPException(status_code=409, detail='ეს მომხმარებლის სახელი უკვე დაკავებულია')

    invite_token = secrets.token_urlsafe(32)
    temporary_password = _temporary_password()
    tx = await db.transaction()
    try:
        await tx.connection.execute(
            'DELETE FROM auth_identities WHERE employee_id = $1 AND username <> $2',
            employee_id,
            default_username,
        )
        await tx.connection.execute(
            """
            INSERT INTO auth_identities (employee_id, username, password_hash, is_active, updated_at)
            VALUES ($1, $2, $3, true, now())
            ON CONFLICT (username) DO UPDATE
               SET employee_id = EXCLUDED.employee_id,
                   password_hash = EXCLUDED.password_hash,
                   is_active = true,
                   updated_at = now()
            """,
            employee_id,
            default_username,
            hash_password(temporary_password),
        )
        await tx.connection.execute(
            """
            INSERT INTO auth_invites (
                employee_id, legal_entity_id, username, invite_token, temp_password_hash,
                recipient_email, sent_via, expires_at, created_by_employee_id, updated_at
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7,
                now() + make_interval(mins => $8), $9, now()
            )
            """,
            employee_id,
            employee['legal_entity_id'],
            default_username,
            invite_token,
            hash_password(temporary_password),
            _clean_text(employee['email']),
            (payload.delivery_channel if payload else 'email'),
            settings.invite_ttl_minutes,
            actor.employee_id,
        )
        await tx.commit()
    except Exception:
        await tx.rollback()
        raise

    invite_link = _invite_link(invite_token)
    recipient_email = _clean_text(employee['email'])
    if (payload.send_invite if payload else True) and recipient_email and settings.smtp_host:
        await send_and_log_email(
            db,
            legal_entity_id=employee['legal_entity_id'],
            event_type='employee_access_grant',
            event_key=str(employee_id),
            to_email=recipient_email,
            subject='HRMS სისტემაში წვდომა',
            body_text=(
                f"{employee['first_name']} {employee['last_name']},\n\n"
                f"თქვენთვის შეიქმნა ESS წვდომა.\n"
                f"მომხმარებელი: {default_username}\n"
                f"დროებითი პაროლი: {temporary_password}\n"
                f"ინვაიტის ბმული: {invite_link}\n\n"
                f"ბმული ვალიდურია {settings.invite_ttl_minutes} წუთის განმავლობაში."
            ),
            extra_payload={'employee_id': str(employee_id)},
        )
    return {
        'status': 'granted',
        'username': default_username,
        'temporary_password': temporary_password,
        'invite_link': invite_link,
    }


@app.post('/devices/registry', status_code=status.HTTP_201_CREATED)
async def create_device_registry_item(request: Request, payload: DeviceRegistryUpsertRequest) -> dict[str, str]:
    actor = await require_actor(request)
    ensure_permission(actor, 'device.manage')
    tenant_legal_entity_id = getattr(request.state, 'tenant_legal_entity_id', None)
    if tenant_legal_entity_id and str(payload.legal_entity_id) != str(tenant_legal_entity_id):
        raise HTTPException(status_code=403, detail='ამ დომენიდან სხვა კომპანიის მოწყობილობის მიბმა აკრძალულია')
    if payload.legal_entity_id != actor.legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='სხვა იურიდიული ერთეულისთვის მოწყობილობის რეგისტრაცია აკრძალულია')
    db = get_db_from_request(request)
    normalized = _normalized_device_registry_payload(payload)
    device_id = await db.fetchval(
        """
        INSERT INTO device_registry (
            legal_entity_id, brand, transport, device_type, device_name, model, serial_number,
            host, port, api_base_url, username, password_ciphertext, device_timezone,
            is_active, poll_interval_seconds, metadata
        )
        VALUES ($1, $2::device_brand, $3::device_transport, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16::jsonb)
        RETURNING id
        """,
        payload.legal_entity_id,
        normalized['brand'],
        normalized['transport'],
        normalized['device_type'],
        normalized['device_name'],
        normalized['model'],
        normalized['serial_number'],
        normalized['host'],
        normalized['port'],
        normalized['api_base_url'],
        normalized['username'],
        normalized['password_ciphertext'],
        normalized['device_timezone'],
        normalized['is_active'],
        normalized['poll_interval_seconds'],
        json.dumps(normalized['metadata']),
    )
    return {'device_id': str(device_id)}


@app.put('/devices/registry/{device_id}')
async def update_device_registry_item(request: Request, device_id: UUID, payload: DeviceRegistryUpsertRequest) -> dict[str, str]:
    actor = await require_actor(request)
    ensure_permission(actor, 'device.manage')
    db = get_db_from_request(request)
    current_entity_id = await db.fetchval('SELECT legal_entity_id FROM device_registry WHERE id = $1', device_id)
    if current_entity_id is None:
        raise HTTPException(status_code=404, detail='მოწყობილობა ვერ მოიძებნა')
    tenant_legal_entity_id = getattr(request.state, 'tenant_legal_entity_id', None)
    if tenant_legal_entity_id and (str(current_entity_id) != str(tenant_legal_entity_id) or str(payload.legal_entity_id) != str(tenant_legal_entity_id)):
        raise HTTPException(status_code=403, detail='ამ დომენიდან სხვა კომპანიის მოწყობილობის რედაქტირება აკრძალულია')
    if current_entity_id != actor.legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='სხვა იურიდიული ერთეულის მოწყობილობის განახლება აკრძალულია')
    normalized = _normalized_device_registry_payload(payload)
    await db.execute(
        """
        UPDATE device_registry
           SET legal_entity_id = $2,
               brand = $3::device_brand,
               transport = $4::device_transport,
               device_type = $5,
               device_name = $6,
               model = $7,
               serial_number = $8,
               host = $9,
               port = $10,
               api_base_url = $11,
               username = $12,
               password_ciphertext = coalesce($13, password_ciphertext),
                device_timezone = $14,
               is_active = $15,
               poll_interval_seconds = $16,
               metadata = $17::jsonb,
               updated_at = now()
         WHERE id = $1
        """,
        device_id,
        payload.legal_entity_id,
        normalized['brand'],
        normalized['transport'],
        normalized['device_type'],
        normalized['device_name'],
        normalized['model'],
        normalized['serial_number'],
        normalized['host'],
        normalized['port'],
        normalized['api_base_url'],
        normalized['username'],
        normalized['password_ciphertext'],
        normalized['device_timezone'],
        normalized['is_active'],
        normalized['poll_interval_seconds'],
        json.dumps(normalized['metadata']),
    )
    return {'status': 'updated'}




@app.put('/entities/{legal_entity_id}/settings')
async def upsert_entity_settings(request: Request, legal_entity_id: UUID, payload: EntityOperationSettingsUpsertRequest) -> dict[str, str]:
    actor = await require_actor(request)
    _ensure_settings_access(actor)
    _ensure_route_tenant(actor, legal_entity_id)
    db = get_db_from_request(request)
    await db.execute(
        """
        INSERT INTO entity_operation_settings (
            legal_entity_id, late_arrival_threshold_minutes,
            require_asset_clearance_for_final_payroll, default_onboarding_course_id
        ) VALUES ($1, $2, $3, $4)
        ON CONFLICT (legal_entity_id) DO UPDATE
           SET late_arrival_threshold_minutes = EXCLUDED.late_arrival_threshold_minutes,
               require_asset_clearance_for_final_payroll = EXCLUDED.require_asset_clearance_for_final_payroll,
               default_onboarding_course_id = EXCLUDED.default_onboarding_course_id,
               updated_at = now()
        """,
        legal_entity_id,
        payload.late_arrival_threshold_minutes,
        payload.require_asset_clearance_for_final_payroll,
        payload.default_onboarding_course_id,
    )
    return {'status': 'saved'}


@app.put('/integrations/mattermost/{legal_entity_id}')
async def upsert_mattermost_integration(request: Request, legal_entity_id: UUID, payload: MattermostIntegrationUpsertRequest) -> dict[str, str]:
    actor = await require_actor(request)
    _ensure_settings_access(actor)
    _ensure_route_tenant(actor, legal_entity_id)
    db = get_db_from_request(request)
    await db.execute(
        """
        INSERT INTO mattermost_integrations (
            legal_entity_id, enabled, server_base_url, incoming_webhook_url, hr_webhook_url,
            general_webhook_url, it_webhook_url, bot_access_token, command_token,
            action_secret, default_team, hr_channel, general_channel, it_channel
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
        ON CONFLICT (legal_entity_id) DO UPDATE
           SET enabled = EXCLUDED.enabled,
               server_base_url = EXCLUDED.server_base_url,
               incoming_webhook_url = EXCLUDED.incoming_webhook_url,
               hr_webhook_url = EXCLUDED.hr_webhook_url,
               general_webhook_url = EXCLUDED.general_webhook_url,
               it_webhook_url = EXCLUDED.it_webhook_url,
               bot_access_token = EXCLUDED.bot_access_token,
               command_token = EXCLUDED.command_token,
               action_secret = EXCLUDED.action_secret,
               default_team = EXCLUDED.default_team,
               hr_channel = EXCLUDED.hr_channel,
               general_channel = EXCLUDED.general_channel,
               it_channel = EXCLUDED.it_channel,
               updated_at = now()
        """,
        legal_entity_id,
        payload.enabled,
        payload.server_base_url,
        payload.incoming_webhook_url,
        payload.hr_webhook_url,
        payload.general_webhook_url,
        payload.it_webhook_url,
        payload.bot_access_token,
        payload.command_token,
        payload.action_secret,
        payload.default_team,
        payload.hr_channel,
        payload.general_channel,
        payload.it_channel,
    )
    return {'status': 'configured'}


@app.post('/shifts/patterns', status_code=status.HTTP_201_CREATED)
async def create_shift_pattern(request: Request, payload: ShiftPatternUpsertRequest) -> dict[str, str]:
    actor = await require_actor(request)
    _ensure_can_manage_shift_templates(actor)
    _validate_shift_pattern_payload(payload)
    db = get_db_from_request(request)
    tx = await db.transaction()
    try:
        pattern_id = await tx.connection.fetchval(
            """
            INSERT INTO shift_patterns (
                legal_entity_id, code, name, pattern_type, cycle_length_days, timezone,
                standard_weekly_hours, early_check_in_grace_minutes, late_check_out_grace_minutes, grace_period_minutes
            )
            VALUES ($1, $2, $3, $4::shift_pattern_type, $5, $6, $7, $8, $9, $10)
            RETURNING id
            """,
            actor.legal_entity_id,
            payload.code,
            payload.name,
            payload.pattern_type,
            payload.cycle_length_days,
            payload.timezone,
            payload.standard_weekly_hours,
            payload.early_check_in_grace_minutes,
            payload.late_check_out_grace_minutes,
            payload.grace_period_minutes,
        )
        segment_rows = []
        for segment in payload.segments:
            planned_minutes, _, crosses_midnight = _segment_payload(segment)
            segment_rows.append(
                (
                    pattern_id,
                    segment.day_index,
                    segment.start_time,
                    planned_minutes,
                    segment.break_minutes,
                    crosses_midnight,
                    segment.label,
                )
            )
        await tx.connection.executemany(
            """
            INSERT INTO shift_pattern_segments (
                shift_pattern_id, day_index, start_time, planned_minutes, break_minutes, crosses_midnight, label
            )
            VALUES ($1, $2, $3::time, $4, $5, $6, $7)
            """,
            segment_rows,
        )
        await tx.commit()
    except Exception:
        await tx.rollback()
        raise
    return {'pattern_id': str(pattern_id)}


@app.put('/shifts/patterns/{pattern_id}')
async def update_shift_pattern(request: Request, pattern_id: UUID, payload: ShiftPatternUpsertRequest) -> dict[str, str]:
    actor = await require_actor(request)
    _ensure_can_manage_shift_templates(actor)
    _validate_shift_pattern_payload(payload)
    db = get_db_from_request(request)
    legal_entity_id = await db.fetchval('SELECT legal_entity_id FROM shift_patterns WHERE id = $1', pattern_id)
    if legal_entity_id is None:
        raise HTTPException(status_code=404, detail='ცვლის შაბლონი ვერ მოიძებნა')
    if legal_entity_id != actor.legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='სხვა იურიდიულ ერთეულზე ცვლის განახლება აკრძალულია')
    tx = await db.transaction()
    try:
        await tx.connection.execute(
            """
            UPDATE shift_patterns
               SET code = $2,
                   name = $3,
                   pattern_type = $4::shift_pattern_type,
                   cycle_length_days = $5,
                   timezone = $6,
                   standard_weekly_hours = $7,
                   early_check_in_grace_minutes = $8,
                   late_check_out_grace_minutes = $9,
                   grace_period_minutes = $10,
                   updated_at = now()
             WHERE id = $1
            """,
            pattern_id,
            payload.code,
            payload.name,
            payload.pattern_type,
            payload.cycle_length_days,
            payload.timezone,
            payload.standard_weekly_hours,
            payload.early_check_in_grace_minutes,
            payload.late_check_out_grace_minutes,
            payload.grace_period_minutes,
        )
        await tx.connection.execute('DELETE FROM shift_pattern_segments WHERE shift_pattern_id = $1', pattern_id)
        segment_rows = []
        for segment in payload.segments:
            planned_minutes, _, crosses_midnight = _segment_payload(segment)
            segment_rows.append(
                (
                    pattern_id,
                    segment.day_index,
                    segment.start_time,
                    planned_minutes,
                    segment.break_minutes,
                    crosses_midnight,
                    segment.label,
                )
            )
        await tx.connection.executemany(
            """
            INSERT INTO shift_pattern_segments (
                shift_pattern_id, day_index, start_time, planned_minutes, break_minutes, crosses_midnight, label
            )
            VALUES ($1, $2, $3::time, $4, $5, $6, $7)
            """,
            segment_rows,
        )
        await tx.commit()
    except Exception:
        await tx.rollback()
        raise
    return {'status': 'updated'}


@app.post('/attendance/web-punch', status_code=status.HTTP_201_CREATED)
async def submit_web_punch(request: Request, payload: WebPunchRequest) -> dict[str, object]:
    actor = await require_actor(request)
    db = get_db_from_request(request)
    direction = payload.direction
    if direction == 'auto':
        last = await db.fetchrow(
            """
            SELECT direction
              FROM (
                    SELECT ral.event_ts AS punch_ts,
                           ral.direction::text AS direction
                      FROM raw_attendance_logs ral
                     WHERE ral.employee_id = $1
                       AND (ral.event_ts AT TIME ZONE 'Asia/Tbilisi')::date = (timezone('Asia/Tbilisi', now()))::date
                       AND ral.direction IN ('in', 'out')
                    UNION ALL
                    SELECT wpe.punch_ts,
                           wpe.direction::text AS direction
                      FROM web_punch_events wpe
                     WHERE wpe.employee_id = $1
                       AND wpe.is_valid = true
                       AND (wpe.punch_ts AT TIME ZONE 'Asia/Tbilisi')::date = (timezone('Asia/Tbilisi', now()))::date
                       AND wpe.direction IN ('in', 'out')
              ) punches
             ORDER BY punch_ts DESC
             LIMIT 1
            """,
            actor.employee_id,
        )
        if last is None or (last['direction'] or '') in {'out', 'unknown'}:
            direction = 'in'
        else:
            direction = 'out'
    elif direction not in {'in', 'out', 'unknown'}:
        raise HTTPException(status_code=400, detail='მიმართულება უნდა იყოს auto, in, out ან unknown')
    is_valid, reason, location_details = await _validate_web_punch_v2(
        request,
        db,
        actor.legal_entity_id,
        payload.latitude,
        payload.longitude,
        payload.gps_accuracy_meters,
    )
    punch_row = await db.fetchrow(
        """
        INSERT INTO web_punch_events (
            employee_id, legal_entity_id, direction, source_ip, latitude, longitude,
            worksite_id, location_name, location_source, gps_accuracy_meters,
            is_location_suspicious, location_risk_reason, is_valid, validation_reason
        ) VALUES ($1, $2, $3::attendance_direction, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
        RETURNING id, punch_ts
        """,
        actor.employee_id,
        actor.legal_entity_id,
        direction,
        _client_ip(request),
        payload.latitude,
        payload.longitude,
        location_details.get('worksite_id'),
        location_details.get('location_name'),
        location_details.get('location_source'),
        payload.gps_accuracy_meters,
        bool(location_details.get('is_location_suspicious')),
        location_details.get('location_risk_reason'),
        is_valid,
        reason,
    )
    if not is_valid:
        raise HTTPException(status_code=403, detail=reason)
    await _apply_attendance_event_to_work_session(db, actor.employee_id, direction, punch_row['punch_ts'], None)
    return {
        'punch_id': str(punch_row['id']),
        'status': 'recorded',
        'validation_reason': reason,
        'direction': direction,
        'location_name': location_details.get('location_name'),
        'is_location_suspicious': bool(location_details.get('is_location_suspicious')),
    }


async def _infer_next_attendance_direction(db_or_conn: Any, employee_id: UUID, event_ts: datetime) -> str:
    if event_ts.tzinfo is None:
        event_ts = event_ts.replace(tzinfo=timezone.utc)
    else:
        event_ts = event_ts.astimezone(timezone.utc)
    last = await db_or_conn.fetchrow(
        """
        SELECT direction
          FROM (
                SELECT ral.event_ts AS punch_ts,
                       ral.direction::text AS direction
                  FROM raw_attendance_logs ral
                 WHERE ral.employee_id = $1
                   AND ral.event_ts < $2
                   AND (ral.event_ts AT TIME ZONE 'Asia/Tbilisi')::date = ($2::timestamptz AT TIME ZONE 'Asia/Tbilisi')::date
                   AND ral.direction IN ('in', 'out')
                UNION ALL
                SELECT wpe.punch_ts,
                       wpe.direction::text AS direction
                  FROM web_punch_events wpe
                 WHERE wpe.employee_id = $1
                   AND wpe.is_valid = true
                   AND wpe.punch_ts < $2
                   AND (wpe.punch_ts AT TIME ZONE 'Asia/Tbilisi')::date = ($2::timestamptz AT TIME ZONE 'Asia/Tbilisi')::date
                   AND wpe.direction IN ('in', 'out')
          ) punches
         ORDER BY punch_ts DESC
         LIMIT 1
        """,
        employee_id,
        event_ts,
    )
    if last is not None and last['direction'] == 'in':
        return 'out'
    return 'in'


async def _apply_attendance_event_to_work_session(
    db_or_conn: Any,
    employee_id: UUID,
    direction: str,
    event_ts: datetime,
    source_log_id: int | None,
) -> None:
    if direction not in {'in', 'out'}:
        return
    if event_ts.tzinfo is None:
        event_ts = event_ts.replace(tzinfo=timezone.utc)
    else:
        event_ts = event_ts.astimezone(timezone.utc)

    if source_log_id is not None:
        existing_session_id = await db_or_conn.fetchval(
            """
            SELECT id
              FROM attendance_work_sessions
             WHERE source_log_in_id = $1
                OR source_log_out_id = $1
             LIMIT 1
            """,
            source_log_id,
        )
        if existing_session_id is not None:
            return

    work_date = await db_or_conn.fetchval(
        "SELECT ($1::timestamptz AT TIME ZONE 'Asia/Tbilisi')::date",
        event_ts,
    )
    if direction == 'in':
        open_session = await db_or_conn.fetchrow(
            """
            SELECT id, check_in_ts
              FROM attendance_work_sessions
             WHERE employee_id = $1
               AND work_date = $2
               AND check_out_ts IS NULL
             ORDER BY check_in_ts DESC
             LIMIT 1
            """,
            employee_id,
            work_date,
        )
        if open_session is not None:
            await db_or_conn.execute(
                """
                UPDATE attendance_work_sessions
                   SET check_in_ts = LEAST(check_in_ts, $2),
                       source_log_in_id = coalesce(source_log_in_id, $3),
                       incomplete_reason = NULL,
                       updated_at = now()
                 WHERE id = $1
                """,
                open_session['id'],
                event_ts,
                source_log_id,
            )
            return
        await db_or_conn.execute(
            """
            INSERT INTO attendance_work_sessions (
                employee_id, work_date, check_in_ts, source_log_in_id,
                total_minutes, overtime_minutes, review_status, manager_review_required
            )
            VALUES ($1, $2, $3, $4, 0, 0, 'open'::review_status, false)
            """,
            employee_id,
            work_date,
            event_ts,
            source_log_id,
        )
        return

    open_session = await db_or_conn.fetchrow(
        """
        SELECT id
          FROM attendance_work_sessions
         WHERE employee_id = $1
           AND check_out_ts IS NULL
           AND check_in_ts <= $2
           AND work_date BETWEEN ($3::date - interval '1 day')::date AND $3::date
         ORDER BY check_in_ts DESC
         LIMIT 1
        """,
        employee_id,
        event_ts,
        work_date,
    )
    if open_session is not None:
        await db_or_conn.execute(
            """
            UPDATE attendance_work_sessions
               SET check_out_ts = $2,
                   source_log_out_id = coalesce(source_log_out_id, $3),
                   total_minutes = greatest(floor(extract(epoch from ($2 - check_in_ts)) / 60)::int, 0),
                   overtime_minutes = greatest(floor(extract(epoch from ($2 - check_in_ts)) / 60)::int - 480, 0),
                   incomplete_reason = NULL,
                   manager_review_required = false,
                   updated_at = now()
             WHERE id = $1
            """,
            open_session['id'],
            event_ts,
            source_log_id,
        )
        return

    await db_or_conn.execute(
        """
        INSERT INTO attendance_work_sessions (
            employee_id, work_date, check_in_ts, check_out_ts,
            source_log_out_id, total_minutes, overtime_minutes,
            review_status, incomplete_reason, manager_review_required
        )
        VALUES ($1, $2, $3, $3, $4, 0, 0, 'open'::review_status, 'orphan_check_out', true)
        """,
        employee_id,
        work_date,
        event_ts,
        source_log_id,
    )


@app.post('/api/v1/attendance/dahua-webhook')
async def dahua_attendance_webhook(request: Request) -> dict[str, object]:
    db = get_db_from_request(request)
    raw_bytes = await request.body()
    body_text = raw_bytes.decode('utf-8', errors='replace')
    parsed_payload: Any
    try:
        parsed_payload = json.loads(body_text) if body_text.strip() else {}
    except json.JSONDecodeError:
        parsed_payload = {'raw_body': body_text}

    user_id = _find_nested_value(parsed_payload, {'UserID', 'user_id', 'PersonID', 'person_id', 'CardNo', 'Card', 'card_number'})
    event_time_value = _find_nested_value(parsed_payload, {'Time', 'CreateTime', 'EventTime', 'UTC', 'PunchTime'})
    dahua_hardware_direction_hint = _infer_dahua_direction(parsed_payload)
    device_serial = _find_nested_value(parsed_payload, {'SerialNumber', 'SerialNo', 'DeviceSerial', 'DeviceID'})
    event_ts = _parse_dahua_event_ts(event_time_value)
    device_id = None
    employee_id = None
    attendance_log_id = None
    employee_legal_entity_id = None

    if device_serial not in (None, ''):
        device_id = await db.fetchval(
            """
            SELECT id
              FROM device_registry
             WHERE serial_number = $1
             LIMIT 1
            """,
            str(device_serial),
        )

    if user_id not in (None, ''):
        employee_row = await db.fetchrow(
            """
            SELECT e.id, e.legal_entity_id
              FROM employee_device_identities edi
              JOIN employees e ON e.id = edi.employee_id
              JOIN device_registry dr ON dr.id = edi.device_id
             WHERE edi.is_active = true
               AND e.deleted_at IS NULL
               AND ($2::uuid IS NULL OR edi.device_id = $2)
               AND (
                    edi.device_user_id = $1
                    OR edi.card_number = $1
                    OR edi.pin_code = $1
               )
             ORDER BY CASE
                    WHEN edi.device_user_id = $1 THEN 0
                    WHEN edi.card_number = $1 THEN 1
                    ELSE 2
               END
             LIMIT 1
            """,
            str(user_id),
            device_id,
        )
        if employee_row is None:
            employee_row = await db.fetchrow(
                """
                SELECT id, legal_entity_id
                  FROM employees
                 WHERE default_device_user_id = $1
                   AND deleted_at IS NULL
                 LIMIT 1
                """,
                str(user_id),
            )
        if employee_row is not None:
            employee_id = employee_row['id']
            employee_legal_entity_id = employee_row['legal_entity_id']
    if device_id is None and employee_legal_entity_id is not None:
        device_id = await db.fetchval(
            """
            SELECT id
              FROM device_registry
             WHERE legal_entity_id = $1
               AND is_active = true
             ORDER BY CASE WHEN lower(brand::text) = 'dahua' THEN 0 ELSE 1 END, last_seen_at DESC NULLS LAST, created_at
             LIMIT 1
            """,
            employee_legal_entity_id,
        )

    if user_id not in (None, '') and employee_id is not None and device_id is not None:
        if employee_id is not None:
            direction = await _infer_next_attendance_direction(db, employee_id, event_ts)
            logged_payload = dict(parsed_payload) if isinstance(parsed_payload, dict) else {'payload': parsed_payload}
            logged_payload['dahua_hardware_direction_hint'] = dahua_hardware_direction_hint
            attendance_log_id = await db.fetchval(
                """
                INSERT INTO raw_attendance_logs (
                    device_id, employee_id, device_user_id, event_ts, direction, verify_mode, external_log_id, raw_payload
                )
                VALUES ($1, $2, $3, $4, $5::attendance_direction, $6, $7, $8::jsonb)
                ON CONFLICT (device_id, device_user_id, event_ts) DO NOTHING
                RETURNING id
                """,
                device_id,
                employee_id,
                str(user_id),
                event_ts,
                direction,
                _find_nested_value(parsed_payload, {'OpenMethod', 'VerifyMode', 'Method'}),
                _find_nested_value(parsed_payload, {'RecNo', 'EventID', 'TransactionID'}),
                json.dumps(logged_payload, ensure_ascii=False),
            )
            if attendance_log_id is not None:
                await _apply_attendance_event_to_work_session(
                    db,
                    employee_id,
                    direction,
                    event_ts,
                    int(attendance_log_id),
                )
                await db.execute(
                    'UPDATE raw_attendance_logs SET processed_at = now() WHERE id = $1',
                    int(attendance_log_id),
                )

    await _append_capture_log(
        {
            'captured_at': datetime.utcnow().isoformat() + 'Z',
            'source': 'app.dahua_webhook',
            'headers': {key: value for key, value in request.headers.items()},
            'body_text': body_text,
            'parsed_payload': parsed_payload,
            'matched_user_id': str(user_id) if user_id not in (None, '') else None,
            'matched_employee_id': str(employee_id) if employee_id else None,
            'attendance_log_id': int(attendance_log_id) if attendance_log_id is not None else None,
        }
    )

    return {
        'status': 'accepted',
        'matched_user_id': str(user_id) if user_id not in (None, '') else None,
        'matched_employee_id': str(employee_id) if employee_id else None,
        'attendance_log_id': int(attendance_log_id) if attendance_log_id is not None else None,
    }


@app.post('/attendance/review-flags/{flag_id}/resolve')
async def resolve_attendance_flag(request: Request, flag_id: UUID, payload: AttendanceOverrideRequest) -> dict[str, str]:
    actor = await require_actor(request)
    ensure_permission(actor, 'attendance.review')
    if payload.corrected_check_out is not None and payload.corrected_check_out < payload.corrected_check_in:
        raise HTTPException(status_code=400, detail='გამოსვლის დრო შემოსვლის დროზე ადრე ვერ იქნება')
    db = get_db_from_request(request)
    flag = await db.fetchrow(
        """
        SELECT arf.id, arf.employee_id, arf.session_id, arf.work_date, e.department_id
          FROM attendance_review_flags arf
          JOIN employees e ON e.id = arf.employee_id
         WHERE arf.id = $1
        """,
        flag_id,
    )
    if flag is None:
        raise HTTPException(status_code=404, detail='დასწრების შესასწორებელი ჩანაწერი ვერ მოიძებნა')
    ensure_can_view_attendance(actor, flag['employee_id'], flag['department_id'])
    total_minutes = 0
    overtime_minutes = 0
    if payload.corrected_check_out is not None:
        total_minutes = int((payload.corrected_check_out - payload.corrected_check_in).total_seconds() // 60)
        overtime_minutes = max(total_minutes - 480, 0)
    tx = await db.transaction()
    try:
        session_id = payload.session_id or flag['session_id']
        if session_id is None:
            session_id = await tx.connection.fetchval(
                """
                INSERT INTO attendance_work_sessions (
                    employee_id, work_date, check_in_ts, check_out_ts, total_minutes, overtime_minutes, review_status, manager_review_required
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7::review_status, false)
                RETURNING id
                """,
                flag['employee_id'],
                payload.work_date,
                payload.corrected_check_in,
                payload.corrected_check_out,
                total_minutes,
                overtime_minutes,
                payload.mark_review_status,
            )
        else:
            await tx.connection.execute(
                """
                UPDATE attendance_work_sessions
                   SET check_in_ts = $2,
                       check_out_ts = $3,
                       total_minutes = $4,
                       overtime_minutes = $5,
                       review_status = $6::review_status,
                       manager_review_required = false,
                       incomplete_reason = NULL,
                       updated_at = now()
                 WHERE id = $1
                """,
                session_id,
                payload.corrected_check_in,
                payload.corrected_check_out,
                total_minutes,
                overtime_minutes,
                payload.mark_review_status,
            )
        await tx.connection.execute(
            """
            UPDATE attendance_review_flags
               SET session_id = $2,
                   resolved_at = now(),
                   resolved_by_employee_id = $3,
                   resolution_note = $4
             WHERE id = $1
            """,
            flag_id,
            session_id,
            actor.employee_id,
            payload.resolution_note,
        )
        await tx.connection.execute(
            """
            INSERT INTO attendance_manual_adjustments (
                employee_id, legal_entity_id, session_id, work_date,
                corrected_check_in, corrected_check_out, reason_comment, created_by_employee_id
            )
            SELECT $1, e.legal_entity_id, $2, $3, $4, $5, $6, $7
              FROM employees e
             WHERE e.id = $1
            """,
            flag['employee_id'],
            session_id,
            payload.work_date,
            payload.corrected_check_in,
            payload.corrected_check_out,
            payload.resolution_note,
            actor.employee_id,
        )
        await tx.commit()
    except Exception:
        await tx.rollback()
        raise
    return {'status': 'resolved'}


@app.post('/attendance/manual-adjustments', status_code=status.HTTP_201_CREATED)
async def create_manual_attendance_adjustment(
    request: Request,
    payload: ManualAttendanceAdjustmentRequest,
) -> dict[str, str]:
    actor = await require_actor(request)
    ensure_permission(actor, 'attendance.review')
    if payload.corrected_check_out is not None and payload.corrected_check_out < payload.corrected_check_in:
        raise HTTPException(status_code=400, detail='გასვლის დრო შემოსვლის დროზე ადრე ვერ იქნება')
    db = get_db_from_request(request)
    employee = await db.fetchrow(
        'SELECT legal_entity_id, department_id FROM employees WHERE id = $1',
        payload.employee_id,
    )
    if employee is None:
        raise HTTPException(status_code=404, detail='თანამშრომელი ვერ მოიძებნა')
    ensure_can_view_attendance(actor, payload.employee_id, employee['department_id'])
    total_minutes = 0
    overtime_minutes = 0
    if payload.corrected_check_out is not None:
        total_minutes = int((payload.corrected_check_out - payload.corrected_check_in).total_seconds() // 60)
        overtime_minutes = max(total_minutes - 480, 0)
    tx = await db.transaction()
    try:
        session_id = payload.session_id
        if session_id:
            await tx.connection.execute(
                """
                UPDATE attendance_work_sessions
                   SET check_in_ts = $2,
                       check_out_ts = $3,
                       total_minutes = $4,
                       overtime_minutes = $5,
                       review_status = 'corrected'::review_status,
                       manager_review_required = false,
                       incomplete_reason = $6,
                       updated_at = now()
                 WHERE id = $1
                """,
                session_id,
                payload.corrected_check_in,
                payload.corrected_check_out,
                total_minutes,
                overtime_minutes,
                payload.reason_comment,
            )
        else:
            session_id = await tx.connection.fetchval(
                """
                INSERT INTO attendance_work_sessions (
                    employee_id, work_date, check_in_ts, check_out_ts,
                    total_minutes, overtime_minutes, review_status, incomplete_reason, manager_review_required
                )
                VALUES ($1, $2, $3, $4, $5, $6, 'corrected'::review_status, $7, false)
                RETURNING id
                """,
                payload.employee_id,
                payload.work_date,
                payload.corrected_check_in,
                payload.corrected_check_out,
                total_minutes,
                overtime_minutes,
                payload.reason_comment,
            )
        adjustment_id = await tx.connection.fetchval(
            """
            INSERT INTO attendance_manual_adjustments (
                employee_id, legal_entity_id, session_id, work_date,
                corrected_check_in, corrected_check_out, reason_comment, created_by_employee_id
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id
            """,
            payload.employee_id,
            employee['legal_entity_id'],
            session_id,
            payload.work_date,
            payload.corrected_check_in,
            payload.corrected_check_out,
            payload.reason_comment,
            actor.employee_id,
        )
        await tx.commit()
    except Exception:
        await tx.rollback()
        raise
    return {'adjustment_id': str(adjustment_id), 'status': 'saved'}


@app.post('/vacancies', status_code=status.HTTP_201_CREATED)
async def create_vacancy(request: Request, payload: VacancyUpsertRequest) -> dict[str, str]:
    actor = await require_actor(request)
    ensure_permission(actor, 'recruitment.manage')
    db = get_db_from_request(request)
    slug = payload.public_slug or f"{_slugify(payload.title_en)}-{payload.posting_code.lower()}"
    vacancy_id = await db.fetchval(
        """
        INSERT INTO job_postings (
            legal_entity_id, department_id, job_role_id, posting_code, title_en, title_ka,
            description, public_description, employment_type, location_text, status, open_positions,
            salary_min, salary_max, created_by_employee_id, published_at, closes_at,
            public_slug, external_form_url, is_public, application_form_schema
        )
        VALUES (
            $1, $2, $3, $4, $5, $6,
            $7, $8, $9, $10, $11::recruitment_posting_status, $12,
            $13, $14, $15, CASE WHEN $11 = 'published' THEN now() ELSE NULL END, $16,
            $17, $18, $19, $20::jsonb
        )
        RETURNING id
        """,
        actor.legal_entity_id,
        payload.department_id,
        payload.job_role_id,
        payload.posting_code,
        payload.title_en,
        payload.title_ka,
        payload.description,
        payload.public_description or payload.description,
        payload.employment_type,
        payload.location_text,
        payload.status,
        payload.open_positions,
        payload.salary_min,
        payload.salary_max,
        actor.employee_id,
        payload.closes_at,
        slug,
        payload.external_form_url,
        payload.is_public,
        json.dumps([field.model_dump() for field in payload.application_form_schema]),
    )
    return {'vacancy_id': str(vacancy_id), 'public_slug': slug}


@app.put('/vacancies/{vacancy_id}')
async def update_vacancy(request: Request, vacancy_id: UUID, payload: VacancyUpsertRequest) -> dict[str, str]:
    actor = await require_actor(request)
    ensure_permission(actor, 'recruitment.manage')
    db = get_db_from_request(request)
    legal_entity_id = await db.fetchval('SELECT legal_entity_id FROM job_postings WHERE id = $1', vacancy_id)
    if legal_entity_id is None:
        raise HTTPException(status_code=404, detail='ვაკანსია ვერ მოიძებნა')
    if legal_entity_id != actor.legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='სხვა იურიდიულ ერთეულზე ვაკანსიის განახლება აკრძალულია')
    slug = payload.public_slug or f"{_slugify(payload.title_en)}-{payload.posting_code.lower()}"
    await db.execute(
        """
        UPDATE job_postings
           SET department_id = $2,
               job_role_id = $3,
               posting_code = $4,
               title_en = $5,
               title_ka = $6,
               description = $7,
               public_description = $8,
               employment_type = $9,
               location_text = $10,
               status = $11::recruitment_posting_status,
               open_positions = $12,
               salary_min = $13,
               salary_max = $14,
               published_at = CASE WHEN $11 = 'published' AND published_at IS NULL THEN now() ELSE published_at END,
               closes_at = $15,
               public_slug = $16,
               external_form_url = $17,
               is_public = $18,
               application_form_schema = $19::jsonb,
               updated_at = now()
         WHERE id = $1
        """,
        vacancy_id,
        payload.department_id,
        payload.job_role_id,
        payload.posting_code,
        payload.title_en,
        payload.title_ka,
        payload.description,
        payload.public_description or payload.description,
        payload.employment_type,
        payload.location_text,
        payload.status,
        payload.open_positions,
        payload.salary_min,
        payload.salary_max,
        payload.closes_at,
        slug,
        payload.external_form_url,
        payload.is_public,
        json.dumps([field.model_dump() for field in payload.application_form_schema]),
    )
    return {'status': 'updated', 'public_slug': slug}


@app.get('/careers/{company_slug}/{vacancy_slug}', include_in_schema=False)
async def public_careers_vacancy_spa(company_slug: str, vacancy_slug: str) -> Response:
    """Serve the dashboard SPA so the client router can render /careers/{tenant}/{public_slug}."""
    dashboard_index = STATIC_DIR / 'dashboard' / 'index.html'
    if dashboard_index.exists():
        return FileResponse(dashboard_index)
    raise HTTPException(status_code=404, detail='Careers SPA is not available (dashboard bundle missing)')


@app.get('/careers/{company_slug}', response_model=None)
async def public_careers_page(company_slug: str, request: Request) -> Response:
    dashboard_index = STATIC_DIR / 'dashboard' / 'index.html'
    if dashboard_index.exists():
        return FileResponse(dashboard_index)
    db = get_db_from_request(request)
    company = await _resolve_company_profile_by_slug(db, company_slug)
    if company is None:
        raise HTTPException(status_code=404, detail='Careers page not found')
    vacancies = await db.fetch(
        """
        SELECT jp.posting_code,
               jp.title_en,
               jp.title_ka,
               jp.description,
               jp.public_description,
               jp.employment_type,
               jp.location_text,
               jp.public_slug,
               jp.external_form_url,
               jp.application_form_schema,
               coalesce(d.name_ka, d.name_en) AS department_name
          FROM job_postings jp
          LEFT JOIN departments d ON d.id = jp.department_id
         WHERE jp.legal_entity_id = $1
           AND jp.status = 'published'
           AND jp.is_public = true
         ORDER BY coalesce(jp.published_at, jp.created_at) DESC
        """,
        company['id'],
    )
    html = _render_careers_page_html(company, [dict(row) for row in vacancies])
    return HTMLResponse(content=html)


@app.get('/public/careers/{company_slug}/vacancies')
async def public_careers_vacancies_json(
    company_slug: str,
    request: Request,
    department: str | None = None,
    location: str | None = None,
    page: int = 1,
    page_size: int = 6,
) -> dict[str, Any]:
    db = get_db_from_request(request)
    company = await _resolve_company_profile_by_slug(db, company_slug)
    if company is None:
        raise HTTPException(status_code=404, detail='Careers page not found')
    legal_id = company['id']
    primary_color = company.get('primary_color') or '#1d4ed8'
    logo_url = company.get('logo_url')
    logo_text = company.get('logo_text')
    trade_name = company.get('trade_name') or ''
    legal_name = company.get('legal_name') or ''

    filter_args: list[Any] = [legal_id]
    where_extra = ''
    if department and department != 'all':
        where_extra += f' AND coalesce(d.name_ka, d.name_en) = ${len(filter_args) + 1}'
        filter_args.append(department)
    if location and location != 'all':
        where_extra += f' AND coalesce(jp.location_text, \'\') = ${len(filter_args) + 1}'
        filter_args.append(location)

    base_from = f"""
        FROM job_postings jp
        LEFT JOIN departments d ON d.id = jp.department_id
       WHERE jp.legal_entity_id = $1
         AND jp.status = 'published'
         AND jp.is_public = true
{where_extra}
    """

    total_row = await db.fetchrow(f'SELECT count(*)::int AS c {base_from}', *filter_args)
    total = int(total_row['c']) if total_row else 0
    page = max(1, page)
    page_size = max(1, min(int(page_size), 50))
    page_count = max(1, math.ceil(total / page_size)) if total else 1
    offset = (page - 1) * page_size

    lim_idx = len(filter_args) + 1
    off_idx = len(filter_args) + 2
    rows = await db.fetch(
        f"""
        SELECT jp.id, jp.posting_code, jp.title_en, jp.title_ka,
               jp.public_description, jp.description, jp.employment_type, jp.location_text,
               jp.open_positions, jp.salary_min, jp.salary_max, jp.public_slug,
               coalesce(d.name_ka, d.name_en) AS department_name
        {base_from}
        ORDER BY coalesce(jp.published_at, jp.created_at) DESC
        LIMIT ${lim_idx} OFFSET ${off_idx}
        """,
        *filter_args,
        page_size,
        offset,
    )

    dept_rows = await db.fetch(
        """
        SELECT DISTINCT coalesce(d.name_ka, d.name_en) AS name
          FROM job_postings jp
          LEFT JOIN departments d ON d.id = jp.department_id
         WHERE jp.legal_entity_id = $1 AND jp.status = 'published' AND jp.is_public = true
           AND coalesce(d.name_ka, d.name_en) IS NOT NULL
         ORDER BY 1
        """,
        legal_id,
    )
    loc_rows = await db.fetch(
        """
        SELECT DISTINCT jp.location_text AS loc
          FROM job_postings jp
         WHERE jp.legal_entity_id = $1 AND jp.status = 'published' AND jp.is_public = true
           AND jp.location_text IS NOT NULL AND btrim(jp.location_text) <> ''
         ORDER BY 1
        """,
        legal_id,
    )

    items: list[dict[str, Any]] = []
    for r in rows:
        desc = str(r.get('public_description') or r.get('description') or '').replace('\n', ' ').strip()
        summary = desc[:190] + ('...' if len(desc) > 190 else '')
        slug = r['public_slug']
        items.append(
            {
                'id': str(r['id']),
                'posting_code': r['posting_code'],
                'title_en': r['title_en'],
                'title_ka': r['title_ka'],
                'summary': summary,
                'employment_type': r['employment_type'] or 'full_time',
                'location_text': r['location_text'],
                'department_name': r['department_name'],
                'open_positions': int(r['open_positions'] or 0),
                'salary_min': str(r['salary_min']) if r['salary_min'] is not None else None,
                'salary_max': str(r['salary_max']) if r['salary_max'] is not None else None,
                'detail_url': f'/careers/{company_slug}/{slug}',
            }
        )

    return {
        'tenant': {
            'legal_name': legal_name,
            'trade_name': trade_name or legal_name,
            'logo_url': logo_url,
            'logo_text': logo_text,
            'primary_color': primary_color,
        },
        'filters': {
            'departments': [str(x['name']) for x in dept_rows if x['name']],
            'locations': [str(x['loc']) for x in loc_rows if x['loc']],
        },
        'items': items,
        'total': total,
        'page': page,
        'page_size': page_size,
        'page_count': page_count,
    }


@app.get('/public/vacancies/{public_slug}')
async def public_vacancy_detail(public_slug: str, request: Request) -> dict[str, object]:
    db = get_db_from_request(request)
    row = await db.fetchrow(
        """
        SELECT jp.id,
               jp.legal_entity_id,
               jp.posting_code,
               jp.title_en,
               jp.title_ka,
               jp.description,
               jp.public_description,
               jp.employment_type,
               jp.location_text,
               jp.status::text AS status,
               jp.open_positions,
               jp.salary_min,
               jp.salary_max,
               jp.closes_at,
               jp.public_slug,
               jp.external_form_url,
               jp.is_public,
               jp.application_form_schema,
               coalesce(le.trade_name, le.legal_name) AS tenant_name,
               esc.primary_color AS tenant_primary_color,
               coalesce(d.name_ka, d.name_en) AS department_name,
               coalesce(jr.title_en, jr.title_ka) AS job_role_name
          FROM job_postings jp
          JOIN legal_entities le ON le.id = jp.legal_entity_id
          LEFT JOIN entity_system_config esc ON esc.legal_entity_id = le.id
          LEFT JOIN departments d ON d.id = jp.department_id
          LEFT JOIN job_roles jr ON jr.id = jp.job_role_id
         WHERE jp.public_slug = $1
           AND jp.is_public = true
        """,
        public_slug,
    )
    if row is None:
        raise HTTPException(status_code=404, detail='საჯარო ვაკანსია ვერ მოიძებნა')
    tenant_legal_entity_id = getattr(request.state, 'tenant_legal_entity_id', None)
    if tenant_legal_entity_id and str(row['legal_entity_id']) != str(tenant_legal_entity_id):
        raise HTTPException(status_code=404, detail='საჯარო ვაკანსია ვერ მოიძებნა')
    payload = dict(row)
    payload['id'] = str(payload['id'])
    payload['application_form_schema'] = _safe_vacancy_schema(payload['application_form_schema'])
    payload['salary_min'] = str(payload['salary_min']) if payload['salary_min'] is not None else None
    payload['salary_max'] = str(payload['salary_max']) if payload['salary_max'] is not None else None
    payload['closes_at'] = payload['closes_at'].isoformat() if payload['closes_at'] else None
    payload['apply_url'] = f'/public/vacancies/{public_slug}/apply'
    payload['primary_color'] = payload.pop('tenant_primary_color', None)
    return payload


@app.post('/public/vacancies/{public_slug}/apply', status_code=status.HTTP_201_CREATED, response_model=None)
async def public_vacancy_apply(public_slug: str, request: Request) -> Any:
    db = get_db_from_request(request)
    content_type = (request.headers.get('content-type') or '').lower()
    cv_file_name: str | None = None
    cv_file_url: str | None = None
    cv_extracted_text = ''
    payload_data: dict[str, Any]
    if 'multipart/form-data' in content_type or 'application/x-www-form-urlencoded' in content_type:
        form = await request.form()
        answers_value = form.get('answers')
        try:
            answers = json.loads(str(answers_value)) if answers_value else {}
        except json.JSONDecodeError:
            answers = {}
        payload_data = {
            'first_name': str(form.get('first_name') or ''),
            'last_name': str(form.get('last_name') or ''),
            'email': form.get('email'),
            'phone': form.get('phone'),
            'city': form.get('city'),
            'source': form.get('source') or 'career_page',
            'current_company': form.get('current_company'),
            'current_position': form.get('current_position'),
            'notes': form.get('notes'),
            'answers': answers if isinstance(answers, dict) else {},
        }
        for key, value in form.multi_items():
            if isinstance(key, str) and key.startswith('answer__'):
                payload_data['answers'][key.removeprefix('answer__')] = str(value)
        cv_upload = form.get('cv_file')
        if hasattr(cv_upload, 'filename') and hasattr(cv_upload, 'read') and getattr(cv_upload, 'filename', None):
            allowed_suffixes = ('.pdf', '.doc', '.docx', '.txt')
            if not str(cv_upload.filename).lower().endswith(allowed_suffixes):
                raise HTTPException(status_code=422, detail='CV file must be PDF, DOC, DOCX, or TXT')
            file_content = await cv_upload.read()
            cv_file_name = cv_upload.filename
            cv_file_url, _ = _store_upload_content(cv_upload.filename, file_content, CANDIDATE_UPLOADS_DIR, 'candidate_cv')
            cv_extracted_text = _extract_cv_text(cv_upload.filename, cv_upload.content_type, file_content)
    else:
        payload_data = await request.json()

    payload = PublicCandidateApplicationRequest.model_validate(payload_data)
    email = _validate_email(payload.email)
    phone = _validate_phone(payload.phone)
    vacancy = await db.fetchrow(
        """
        SELECT jp.id,
               jp.legal_entity_id,
               jp.external_form_url,
               coalesce(jp.title_ka, jp.title_en, jp.posting_code) AS vacancy_title,
               coalesce(le.trade_name, le.legal_name, 'Careers') AS company_name,
               coalesce(td.subdomain, lower(regexp_replace(coalesce(le.trade_name, le.legal_name), '[^a-zA-Z0-9]+', '-', 'g'))) AS company_slug
          FROM job_postings jp
          JOIN legal_entities le ON le.id = jp.legal_entity_id
          LEFT JOIN tenant_domains td ON td.legal_entity_id = le.id AND td.is_primary = true AND td.is_active = true
         WHERE jp.public_slug = $1
           AND jp.is_public = true
           AND jp.status = 'published'
        """,
        public_slug,
    )
    if vacancy is None:
        raise HTTPException(status_code=404, detail='გამოქვეყნებული ვაკანსია ვერ მოიძებნა')
    tenant_legal_entity_id = getattr(request.state, 'tenant_legal_entity_id', None)
    if tenant_legal_entity_id and str(vacancy['legal_entity_id']) != str(tenant_legal_entity_id):
        raise HTTPException(status_code=404, detail='გამოქვეყნებული ვაკანსია ვერ მოიძებნა')
    if vacancy['external_form_url']:
        raise HTTPException(status_code=409, detail='ამ ვაკანსიაზე განაცხადი მიიღება გარე Google Form-ით')
    stage_id = await db.fetchval(
        """
        SELECT id
          FROM candidate_pipeline_stages
         WHERE legal_entity_id = $1
         ORDER BY CASE WHEN upper(code::text) = 'APPLIED' THEN 0 ELSE 1 END, sort_order
         LIMIT 1
        """,
        vacancy['legal_entity_id'],
    )
    if stage_id is None:
        raise HTTPException(status_code=500, detail='კანდიდატის ეტაპები კონფიგურირებული არ არის')
    tx = await db.transaction()
    try:
        candidate_id = None
        if email:
            candidate_id = await tx.connection.fetchval(
                'SELECT id FROM candidates WHERE legal_entity_id = $1 AND email = $2',
                vacancy['legal_entity_id'],
                email,
            )
        if candidate_id is None:
            candidate_id = await tx.connection.fetchval(
                """
                INSERT INTO candidates (
                    legal_entity_id, first_name, last_name, email, phone, city, source, current_company, current_position, notes
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING id
                """,
                vacancy['legal_entity_id'],
                payload.first_name,
                payload.last_name,
                email,
                phone,
                payload.city,
                payload.source,
                payload.current_company,
                payload.current_position,
                payload.notes,
            )
        application_id = await tx.connection.fetchval(
            """
            INSERT INTO candidate_applications (
                candidate_id, job_posting_id, current_stage_id, application_payload
            )
            VALUES ($1, $2, $3, $4::jsonb)
            ON CONFLICT (candidate_id, job_posting_id) DO UPDATE
               SET application_payload = EXCLUDED.application_payload,
                   updated_at = now()
            RETURNING id
            """,
            candidate_id,
            vacancy['id'],
            stage_id,
            json.dumps({'answers': payload.answers}),
        )
        if cv_file_name or cv_file_url or cv_extracted_text:
            await tx.connection.execute(
                """
                UPDATE candidate_applications
                   SET cv_file_name = $2,
                       cv_file_url = $3,
                       cv_extracted_text = $4,
                       updated_at = now()
                 WHERE id = $1
                """,
                application_id,
                cv_file_name,
                cv_file_url,
                cv_extracted_text,
            )
        await tx.connection.execute(
            """
            INSERT INTO candidate_pipeline (application_id, stage_id, comment)
            VALUES ($1, $2, $3)
            """,
            application_id,
            stage_id,
            'Public application submitted',
        )
        score_payload = await analyze_candidate_application(tx.connection, application_id)
        await tx.commit()
    except Exception:
        await tx.rollback()
        raise
    result = {
        'application_id': str(application_id),
        'status': 'submitted',
        'compatibility_score': score_payload['score'],
        'compatibility_summary': score_payload['summary'],
    }
    if 'multipart/form-data' in content_type or 'application/x-www-form-urlencoded' in content_type:
        careers_url = f"/careers/{vacancy['company_slug']}#{public_slug}"
        return HTMLResponse(
            content=_render_application_success_html(vacancy['company_name'], vacancy['vacancy_title'], careers_url),
            status_code=status.HTTP_201_CREATED,
        )
    return result


@app.post('/inventory/items', status_code=status.HTTP_201_CREATED)
async def create_inventory_item(request: Request, payload: InventoryItemUpsertRequest) -> dict[str, str]:
    actor = await require_actor(request)
    ensure_permission(actor, 'assets.manage')
    db = get_db_from_request(request)
    item_id = await db.fetchval(
        """
        INSERT INTO inventory_items (
            legal_entity_id, category_id, asset_tag, asset_name, brand, model, serial_number,
            current_condition, current_status, purchase_date, purchase_cost, currency_code,
            assigned_department_id, notes
        )
        VALUES (
            $1, $2, $3, $4, $5, $6, $7,
            $8::asset_condition, $9::asset_status, $10, $11, $12,
            $13, $14
        )
        RETURNING id
        """,
        actor.legal_entity_id,
        payload.category_id,
        payload.asset_tag,
        payload.asset_name,
        payload.brand,
        payload.model,
        payload.serial_number,
        payload.current_condition,
        payload.current_status,
        payload.purchase_date,
        payload.purchase_cost,
        payload.currency_code,
        payload.assigned_department_id,
        payload.notes,
    )
    return {'item_id': str(item_id)}


@app.put('/inventory/items/{item_id}')
async def update_inventory_item(request: Request, item_id: UUID, payload: InventoryItemUpsertRequest) -> dict[str, str]:
    actor = await require_actor(request)
    ensure_permission(actor, 'assets.manage')
    db = get_db_from_request(request)
    legal_entity_id = await db.fetchval('SELECT legal_entity_id FROM inventory_items WHERE id = $1', item_id)
    if legal_entity_id is None:
        raise HTTPException(status_code=404, detail='ინვენტარის ჩანაწერი ვერ მოიძებნა')
    if legal_entity_id != actor.legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='სხვა იურიდიულ ერთეულზე ინვენტარის განახლება აკრძალულია')
    await db.execute(
        """
        UPDATE inventory_items
           SET category_id = $2,
               asset_tag = $3,
               asset_name = $4,
               brand = $5,
               model = $6,
               serial_number = $7,
               current_condition = $8::asset_condition,
               current_status = $9::asset_status,
               purchase_date = $10,
               purchase_cost = $11,
               currency_code = $12,
               assigned_department_id = $13,
               notes = $14,
               updated_at = now()
         WHERE id = $1
        """,
        item_id,
        payload.category_id,
        payload.asset_tag,
        payload.asset_name,
        payload.brand,
        payload.model,
        payload.serial_number,
        payload.current_condition,
        payload.current_status,
        payload.purchase_date,
        payload.purchase_cost,
        payload.currency_code,
        payload.assigned_department_id,
        payload.notes,
    )
    return {'status': 'updated'}


@app.post('/inventory/items/{item_id}/assign', status_code=status.HTTP_201_CREATED)
async def assign_inventory_item(request: Request, item_id: UUID, payload: InventoryAssignRequest) -> dict[str, str]:
    actor = await require_actor(request)
    ensure_permission(actor, 'assets.manage')
    db = get_db_from_request(request)
    tx = await db.transaction()
    try:
        assignment_id = await tx.connection.fetchval(
            """
            INSERT INTO asset_assignments (
                item_id, employee_id, assigned_by_employee_id, assigned_at, expected_return_at,
                condition_on_issue, note, employee_acknowledged_at
            )
            VALUES ($1, $2, $3, $4, $5, $6::asset_condition, $7, now())
            RETURNING id
            """,
            item_id,
            payload.employee_id,
            actor.employee_id,
            payload.assigned_at,
            payload.expected_return_at,
            payload.condition_on_issue,
            payload.note,
        )
        if payload.evidence:
            await tx.connection.executemany(
                """
                INSERT INTO asset_condition_evidence (assignment_id, evidence_phase, file_url, note, captured_by_employee_id)
                VALUES ($1, 'issue', $2, $3, $4)
                """,
                [(assignment_id, evidence.file_url, evidence.note, actor.employee_id) for evidence in payload.evidence],
            )
        await tx.connection.execute(
            """
            INSERT INTO asset_handover_forms (assignment_id, employee_signature_name, handover_summary)
            VALUES ($1, $2, $3)
            """,
            assignment_id,
            payload.employee_signature_name,
            payload.note or f'Digital handover completed by {payload.employee_signature_name}',
        )
        await tx.connection.execute(
            """
            UPDATE inventory_items
               SET current_status = 'assigned',
                   current_condition = $2::asset_condition,
                   updated_at = now()
             WHERE id = $1
            """,
            item_id,
            payload.condition_on_issue,
        )
        await tx.commit()
    except Exception:
        await tx.rollback()
        raise
    return {'assignment_id': str(assignment_id)}


@app.post('/payroll/timesheets/{timesheet_id}/mark-paid')
async def mark_timesheet_paid(request: Request, timesheet_id: UUID, payload: PayrollMarkPaidRequest) -> dict[str, str]:
    actor = await require_actor(request)
    ensure_can_export_payroll(actor)
    db = get_db_from_request(request)
    row = await db.fetchrow(
        """
        SELECT mts.id,
               mts.employee_id,
               mts.year,
               mts.month,
               mts.total_minutes,
               mts.overtime_minutes,
               mts.gross_pay,
               mts.employee_pension_amount,
               mts.income_tax_amount,
               mts.net_pay,
               e.employee_number,
               e.first_name,
               e.last_name
          FROM monthly_timesheets mts
          JOIN employees e ON e.id = mts.employee_id
         WHERE mts.id = $1
        """,
        timesheet_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail='ტაბელი ვერ მოიძებნა')
    payslip_name = f"payslip_{row['employee_number']}_{row['year']}_{int(row['month']):02d}.pdf"
    pdf_bytes = _build_simple_payslip_pdf(
        [
            'ITGS HR Payslip',
            f"Employee: {row['first_name']} {row['last_name']} ({row['employee_number']})",
            f"Period: {row['year']}-{int(row['month']):02d}",
            f"Worked hours: {round(int(row['total_minutes']) / 60, 2)}",
            f"Overtime hours: {round(int(row['overtime_minutes']) / 60, 2)}",
            f"Gross pay: {row['gross_pay']} GEL",
            f"Pension: {row['employee_pension_amount']} GEL",
            f"Income tax: {row['income_tax_amount']} GEL",
            f"Net pay: {row['net_pay']} GEL",
            f"Locked by: {actor.employee_id}",
        ]
    )
    paid_at = payload.paid_at or datetime.utcnow()
    payment_id = await db.fetchval(
        """
        INSERT INTO payroll_payment_records (
            timesheet_id, employee_id, paid_at, payment_method, payment_reference, note,
            payslip_file_name, payslip_pdf, locked_by_employee_id
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        ON CONFLICT (timesheet_id) DO UPDATE
           SET paid_at = EXCLUDED.paid_at,
               payment_method = EXCLUDED.payment_method,
               payment_reference = EXCLUDED.payment_reference,
               note = EXCLUDED.note,
               payslip_file_name = EXCLUDED.payslip_file_name,
               payslip_pdf = EXCLUDED.payslip_pdf,
               locked_by_employee_id = EXCLUDED.locked_by_employee_id,
               updated_at = now()
        RETURNING id
        """,
        timesheet_id,
        row['employee_id'],
        paid_at,
        payload.payment_method,
        payload.payment_reference,
        payload.note,
        payslip_name,
        pdf_bytes,
        actor.employee_id,
    )
    await db.execute(
        """
        UPDATE monthly_timesheets
           SET status = 'locked',
               approved_at = coalesce(approved_at, $2),
               approved_by_employee_id = coalesce(approved_by_employee_id, $3),
               updated_at = now()
         WHERE id = $1
        """,
        timesheet_id,
        paid_at,
        actor.employee_id,
    )
    return {'payment_id': str(payment_id), 'payslip_file_name': payslip_name}


@app.get('/payroll/timesheets/{timesheet_id}/payslip.pdf')
async def download_payslip(request: Request, timesheet_id: UUID) -> Response:
    actor = await require_actor(request)
    ensure_can_export_payroll(actor)
    db = get_db_from_request(request)
    row = await db.fetchrow(
        """
        SELECT payslip_file_name, payslip_pdf
          FROM payroll_payment_records
         WHERE timesheet_id = $1
        """,
        timesheet_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail='ხელფასის ფურცელი ვერ მოიძებნა')
    response = Response(content=row['payslip_pdf'], media_type='application/pdf')
    response.headers['Content-Disposition'] = f"inline; filename={row['payslip_file_name']}"
    return response


@app.put('/system/config/{legal_entity_id}')
async def upsert_system_config(request: Request, legal_entity_id: UUID, payload: SystemConfigUpsertRequest) -> dict[str, str]:
    actor = await require_actor(request)
    _ensure_settings_access(actor)
    if actor.legal_entity_id != legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='სხვა იურიდიული ერთეულის კონფიგურაციის შეცვლა აკრძალულია')
    db = get_db_from_request(request)
    normalized_allowed_web_punch_ips: list[str] = []
    for ip_value in payload.allowed_web_punch_ips:
        if not ip_value:
            continue
        try:
            normalized_allowed_web_punch_ips.append(str(_normalize_ip(ip_value)))
        except ValueError:
            raise HTTPException(status_code=400, detail=f'Invalid IP address: {ip_value}')

    if payload.trade_name:
        await db.execute(
            'UPDATE legal_entities SET trade_name = $2, updated_at = now() WHERE id = $1',
            legal_entity_id,
            payload.trade_name,
        )
    await db.execute(
        """
        INSERT INTO entity_system_config (
            legal_entity_id, logo_url, logo_text, primary_color, standalone_chat_url,
            linkedin_url, facebook_url, instagram_url,
            allowed_web_punch_ips, geofence_latitude, geofence_longitude, geofence_radius_meters,
            gps_only_check_in, company_dashboard_enabled, payroll_dashboard_enabled, dashboard_widget_visibility,
            updated_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::text[], $10, $11, $12, $13, $14, $15, $16::jsonb, now())
        ON CONFLICT (legal_entity_id) DO UPDATE
           SET logo_url = EXCLUDED.logo_url,
               logo_text = EXCLUDED.logo_text,
               primary_color = EXCLUDED.primary_color,
               standalone_chat_url = EXCLUDED.standalone_chat_url,
               linkedin_url = EXCLUDED.linkedin_url,
               facebook_url = EXCLUDED.facebook_url,
               instagram_url = EXCLUDED.instagram_url,
               allowed_web_punch_ips = EXCLUDED.allowed_web_punch_ips,
               geofence_latitude = EXCLUDED.geofence_latitude,
               geofence_longitude = EXCLUDED.geofence_longitude,
               geofence_radius_meters = EXCLUDED.geofence_radius_meters,
               gps_only_check_in = EXCLUDED.gps_only_check_in,
               company_dashboard_enabled = EXCLUDED.company_dashboard_enabled,
               payroll_dashboard_enabled = EXCLUDED.payroll_dashboard_enabled,
               dashboard_widget_visibility = EXCLUDED.dashboard_widget_visibility,
               updated_at = now()
        """,
        legal_entity_id,
        payload.logo_url,
        payload.logo_text,
        payload.primary_color,
        payload.standalone_chat_url,
        payload.linkedin_url,
        payload.facebook_url,
        payload.instagram_url,
        normalized_allowed_web_punch_ips,
        payload.geofence_latitude,
        payload.geofence_longitude,
        payload.geofence_radius_meters,
        payload.gps_only_check_in,
        payload.company_dashboard_enabled,
        payload.payroll_dashboard_enabled,
        json.dumps(_normalize_dashboard_widget_visibility(payload.dashboard_widget_visibility)),
    )
    await db.execute(
        """
        INSERT INTO entity_operation_settings (
            legal_entity_id, late_arrival_threshold_minutes,
            require_asset_clearance_for_final_payroll, default_onboarding_course_id
        ) VALUES ($1, $2, $3, $4)
        ON CONFLICT (legal_entity_id) DO UPDATE
           SET late_arrival_threshold_minutes = EXCLUDED.late_arrival_threshold_minutes,
               require_asset_clearance_for_final_payroll = EXCLUDED.require_asset_clearance_for_final_payroll,
               default_onboarding_course_id = EXCLUDED.default_onboarding_course_id,
               updated_at = now()
        """,
        legal_entity_id,
        payload.late_arrival_threshold_minutes,
        payload.require_asset_clearance_for_final_payroll,
        payload.default_onboarding_course_id,
    )
    if payload.income_tax_rate is not None or payload.employee_pension_rate is not None:
        await db.execute(
            """
            UPDATE pay_policies
               SET income_tax_rate = coalesce($2, income_tax_rate),
                   employee_pension_rate = coalesce($3, employee_pension_rate),
                   updated_at = now()
             WHERE legal_entity_id = $1
            """,
            legal_entity_id,
            payload.income_tax_rate,
            payload.employee_pension_rate,
        )
    return {'status': 'saved'}


@app.put('/system/policies/{legal_entity_id}/schedule-managers')
async def update_schedule_manager_assignments(
    request: Request,
    legal_entity_id: UUID,
    payload: ScheduleManagerAssignmentsUpdateRequest,
) -> dict[str, str]:
    actor = await require_actor(request)
    if not _is_super_admin(actor):
        raise HTTPException(status_code=403, detail='Only super admins can manage schedule manager assignments')
    if actor.legal_entity_id != legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='Cross-tenant policy updates are not allowed')
    db = get_db_from_request(request)
    department_rows = await db.fetch(
        'SELECT id FROM departments WHERE legal_entity_id = $1 AND is_active = true',
        legal_entity_id,
    )
    valid_department_ids = {row['id'] for row in department_rows}
    employee_rows = await db.fetch(
        """
        SELECT id, department_id
          FROM employees
         WHERE legal_entity_id = $1
           AND deleted_at IS NULL
           AND employment_status = 'active'
        """,
        legal_entity_id,
    )
    valid_employee_ids = {row['id'] for row in employee_rows}
    requested_rows: list[tuple[UUID, UUID, UUID, UUID | None]] = []
    for assignment in payload.assignments:
        if assignment.department_id not in valid_department_ids:
            raise HTTPException(status_code=400, detail='One or more selected departments are invalid')
        for employee_id in assignment.employee_ids:
            if employee_id not in valid_employee_ids:
                raise HTTPException(status_code=400, detail='One or more selected schedule managers are invalid')
            requested_rows.append((legal_entity_id, assignment.department_id, employee_id, actor.employee_id))

    tx = await db.transaction()
    try:
        await tx.connection.execute(
            'DELETE FROM department_schedule_managers WHERE legal_entity_id = $1',
            legal_entity_id,
        )
        if requested_rows:
            await tx.connection.executemany(
                """
                INSERT INTO department_schedule_managers (
                    legal_entity_id, department_id, employee_id, created_by_employee_id
                )
                VALUES ($1, $2, $3, $4)
                """,
                requested_rows,
            )
        await tx.commit()
    except Exception:
        await tx.rollback()
        raise

    await _log_audit_event(
        db,
        actor_employee_id=actor.employee_id,
        legal_entity_id=legal_entity_id,
        action_code='policy.schedule_managers.updated',
        details={
            'assignment_count': len(requested_rows),
            'department_count': len({row[1] for row in requested_rows}),
        },
    )
    return {'status': 'saved'}


@app.put('/system/policies/{legal_entity_id}/employee-editors')
async def update_employee_editor_assignments(
    request: Request,
    legal_entity_id: UUID,
    payload: EmployeeEditorAssignmentsUpdateRequest,
) -> dict[str, str]:
    actor = await require_actor(request)
    if not _is_super_admin(actor):
        raise HTTPException(status_code=403, detail='Only super admins can manage employee editor assignments')
    if actor.legal_entity_id != legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='Cross-tenant policy updates are not allowed')
    db = get_db_from_request(request)
    department_rows = await db.fetch(
        'SELECT id FROM departments WHERE legal_entity_id = $1 AND is_active = true',
        legal_entity_id,
    )
    valid_department_ids = {row['id'] for row in department_rows}
    employee_rows = await db.fetch(
        """
        SELECT id
          FROM employees
         WHERE legal_entity_id = $1
           AND deleted_at IS NULL
           AND employment_status = 'active'
        """,
        legal_entity_id,
    )
    valid_employee_ids = {row['id'] for row in employee_rows}
    requested_rows: list[tuple[UUID, UUID, UUID, UUID | None]] = []
    for assignment in payload.assignments:
        if assignment.department_id not in valid_department_ids:
            raise HTTPException(status_code=400, detail='One or more selected departments are invalid')
        for employee_id in assignment.employee_ids:
            if employee_id not in valid_employee_ids:
                raise HTTPException(status_code=400, detail='One or more selected employee editors are invalid')
            requested_rows.append((legal_entity_id, assignment.department_id, employee_id, actor.employee_id))

    tx = await db.transaction()
    try:
        await tx.connection.execute(
            'DELETE FROM department_employee_editors WHERE legal_entity_id = $1',
            legal_entity_id,
        )
        if requested_rows:
            await tx.connection.executemany(
                """
                INSERT INTO department_employee_editors (
                    legal_entity_id, department_id, employee_id, created_by_employee_id
                )
                VALUES ($1, $2, $3, $4)
                """,
                requested_rows,
            )
        await tx.commit()
    except Exception:
        await tx.rollback()
        raise

    await _log_audit_event(
        db,
        actor_employee_id=actor.employee_id,
        legal_entity_id=legal_entity_id,
        action_code='policy.employee_editors.updated',
        details={
            'assignment_count': len(requested_rows),
            'department_count': len({row[1] for row in requested_rows}),
        },
    )
    return {'status': 'saved'}


@app.put('/system/policies/{legal_entity_id}/leave')
async def update_leave_policies(
    request: Request,
    legal_entity_id: UUID,
    payload: LeavePoliciesUpdateRequest,
) -> dict[str, str]:
    actor = await require_actor(request)
    if not _is_super_admin(actor):
        raise HTTPException(status_code=403, detail='Only super admins can manage leave policies')
    if actor.legal_entity_id != legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='Cross-tenant policy updates are not allowed')
    db = get_db_from_request(request)
    if payload.global_leave_approver_employee_id is not None:
        exists = await db.fetchval(
            """
            SELECT 1
              FROM employees
             WHERE id = $1
               AND legal_entity_id = $2
               AND deleted_at IS NULL
            """,
            payload.global_leave_approver_employee_id,
            legal_entity_id,
        )
        if exists is None:
            raise HTTPException(status_code=400, detail='Global approver must belong to this company')

    valid_departments = {
        row['id']
        for row in await db.fetch(
            'SELECT id FROM departments WHERE legal_entity_id = $1 AND is_active = true',
            legal_entity_id,
        )
    }
    valid_employee_ids = {
        row['id']
        for row in await db.fetch(
            """
            SELECT id
              FROM employees
             WHERE legal_entity_id = $1
               AND deleted_at IS NULL
               AND employment_status = 'active'
            """,
            legal_entity_id,
        )
    }
    approver_rows: list[tuple[UUID, UUID, UUID | None, UUID | None]] = []
    for assignment in payload.department_approvers:
        if assignment.department_id not in valid_departments:
            raise HTTPException(status_code=400, detail='One or more departments are invalid')
        if assignment.approver_employee_id is not None and assignment.approver_employee_id not in valid_employee_ids:
            raise HTTPException(status_code=400, detail='One or more approvers are invalid')
        approver_rows.append((assignment.department_id, legal_entity_id, assignment.approver_employee_id, actor.employee_id))

    tx = await db.transaction()
    try:
        await tx.connection.execute(
            """
            INSERT INTO entity_leave_policy_settings (
                legal_entity_id,
                paid_leave_allowance_days,
                unpaid_leave_allowance_days,
                eligibility_months,
                enable_birthday_off,
                enable_day_off,
                global_leave_approver_employee_id,
                updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, now())
            ON CONFLICT (legal_entity_id) DO UPDATE
               SET paid_leave_allowance_days = EXCLUDED.paid_leave_allowance_days,
                   unpaid_leave_allowance_days = EXCLUDED.unpaid_leave_allowance_days,
                   eligibility_months = EXCLUDED.eligibility_months,
                   enable_birthday_off = EXCLUDED.enable_birthday_off,
                   enable_day_off = EXCLUDED.enable_day_off,
                   global_leave_approver_employee_id = EXCLUDED.global_leave_approver_employee_id,
                   updated_at = now()
            """,
            legal_entity_id,
            payload.paid_leave_allowance_days,
            payload.unpaid_leave_allowance_days,
            payload.eligibility_months,
            payload.enable_birthday_off,
            payload.enable_day_off,
            payload.global_leave_approver_employee_id,
        )
        await tx.connection.execute(
            'DELETE FROM department_leave_approvers WHERE legal_entity_id = $1',
            legal_entity_id,
        )
        if approver_rows:
            await tx.connection.executemany(
                """
                INSERT INTO department_leave_approvers (
                    department_id, legal_entity_id, approver_employee_id, created_by_employee_id, updated_at
                )
                VALUES ($1, $2, $3, $4, now())
                """,
                approver_rows,
            )
        await tx.commit()
    except Exception:
        await tx.rollback()
        raise

    await _log_audit_event(
        db,
        actor_employee_id=actor.employee_id,
        legal_entity_id=legal_entity_id,
        action_code='policy.leave.updated',
        details={
            'paid_leave_allowance_days': payload.paid_leave_allowance_days,
            'unpaid_leave_allowance_days': payload.unpaid_leave_allowance_days,
            'eligibility_months': payload.eligibility_months,
            'enable_birthday_off': payload.enable_birthday_off,
            'enable_day_off': payload.enable_day_off,
            'global_leave_approver_employee_id': str(payload.global_leave_approver_employee_id) if payload.global_leave_approver_employee_id else None,
            'department_approver_count': len(approver_rows),
        },
    )
    return {'status': 'saved'}


@app.put('/system/tenants/{legal_entity_id}/subscriptions')
async def update_tenant_subscriptions(
    request: Request,
    legal_entity_id: UUID,
    payload: TenantSubscriptionUpdateRequest,
) -> dict[str, str]:
    actor = await require_actor(request)
    _ensure_settings_access(actor)
    if not _is_platform_super_admin(actor):
        raise HTTPException(status_code=403, detail='Only the platform superadmin can change master tenant modules')
    if actor.legal_entity_id != legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='სხვა იურიდიული ერთეულის გამოწერის შეცვლა აკრძალულია')
    db = get_db_from_request(request)
    await db.execute(
        """
        INSERT INTO tenant_subscriptions (
            legal_entity_id, attendance_enabled, payroll_enabled, ats_enabled, chat_enabled,
            device_management_enabled, mobile_sync_enabled, assets_enabled, org_chart_enabled, performance_enabled, updated_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, now())
        ON CONFLICT (legal_entity_id) DO UPDATE
           SET attendance_enabled = EXCLUDED.attendance_enabled,
               payroll_enabled = EXCLUDED.payroll_enabled,
               ats_enabled = EXCLUDED.ats_enabled,
               chat_enabled = EXCLUDED.chat_enabled,
               device_management_enabled = EXCLUDED.device_management_enabled,
               mobile_sync_enabled = EXCLUDED.mobile_sync_enabled,
               assets_enabled = EXCLUDED.assets_enabled,
               org_chart_enabled = EXCLUDED.org_chart_enabled,
               performance_enabled = EXCLUDED.performance_enabled,
               updated_at = now()
        """,
        legal_entity_id,
        payload.attendance_enabled,
        payload.payroll_enabled,
        payload.ats_enabled,
        payload.chat_enabled,
        payload.device_management_enabled,
        payload.mobile_sync_enabled,
        payload.assets_enabled,
        payload.org_chart_enabled,
        payload.performance_enabled,
    )
    return {'status': 'saved'}


@app.post('/system/tenants', status_code=status.HTTP_201_CREATED)
async def create_legal_entity(request: Request, payload: LegalEntityCreateRequest) -> dict[str, str]:
    actor = await require_actor(request)
    _ensure_settings_access(actor)
    if 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='კომპანიის დამატება მხოლოდ superadmin მომხმარებლისთვის არის ხელმისაწვდომი')

    db = get_db_from_request(request)
    legal_name = _clean_text(payload.legal_name)
    trade_name = _clean_text(payload.trade_name)
    tax_id = _clean_text(payload.tax_id)
    admin_username = _clean_text(payload.admin_username)
    admin_email = _validate_email(payload.admin_email)
    admin_first_name = _clean_text(payload.admin_first_name) or 'Company'
    admin_last_name = _clean_text(payload.admin_last_name) or 'Administrator'
    host = _clean_text(payload.host.lower() if payload.host else None)
    subdomain = _clean_text(payload.subdomain.lower() if payload.subdomain else None)
    base_host = urlparse(settings.public_base_url).hostname
    resolved_host = host or (f'{subdomain}.{base_host}' if subdomain and base_host else None)

    if legal_name is None or trade_name is None or tax_id is None or admin_username is None:
        raise HTTPException(status_code=422, detail='კომპანიის დასამატებლად შეავსეთ legal name, trade name, tax id და admin username')

    existing_username = await db.fetchval('SELECT 1 FROM auth_identities WHERE username = $1', admin_username)
    if existing_username:
        raise HTTPException(status_code=409, detail='ეს admin username უკვე დაკავებულია')

    tx = await db.transaction()
    try:
        legal_entity_id = await tx.connection.fetchval(
            """
            INSERT INTO legal_entities (legal_name, trade_name, tax_id, timezone, currency_code, city, country_code)
            VALUES ($1, $2, $3, 'Asia/Tbilisi', 'GEL', 'Tbilisi', 'GE')
            RETURNING id
            """,
            legal_name,
            trade_name,
            tax_id,
        )
        department_id = await tx.connection.fetchval(
            """
            INSERT INTO departments (legal_entity_id, code, name_en, name_ka)
            VALUES ($1, 'ADMIN', 'Administration', 'ადმინისტრაცია')
            RETURNING id
            """,
            legal_entity_id,
        )
        job_role_id = await tx.connection.fetchval(
            """
            INSERT INTO job_roles (legal_entity_id, code, title_en, title_ka, is_managerial)
            VALUES ($1, 'COMPANY_ADMIN', 'Company Admin', 'კომპანიის ადმინისტრატორი', true)
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
            VALUES ($1, 'ADM-0001', NULL, $2, $3, $4, $5, $6, current_date, 'active')
            RETURNING id
            """,
            legal_entity_id,
            admin_first_name,
            admin_last_name,
            admin_email,
            department_id,
            job_role_id,
        )
        await tx.connection.execute(
            """
            INSERT INTO employee_compensation (employee_id, policy_id, effective_from, salary_type, base_salary, is_pension_participant)
            VALUES ($1, $2, current_date, 'monthly_fixed', 0, false)
            """,
            employee_id,
            pay_policy_id,
        )
        tenant_admin_role_id = await _ensure_access_role(
            tx.connection,
            code='TENANT_ADMIN',
            name_en='Tenant Administrator',
            name_ka='კომპანიის ადმინისტრატორი',
            description='Full tenant-level access without platform-wide cross-tenant override',
            permission_codes=TENANT_ADMIN_PERMISSIONS,
        )
        if tenant_admin_role_id is None:
            raise HTTPException(status_code=500, detail='ADMIN role ვერ მოიძებნა')
        await tx.connection.execute(
            """
            INSERT INTO employee_access_roles (employee_id, access_role_id, assigned_by_employee_id)
            VALUES ($1, $2, $1)
            ON CONFLICT DO NOTHING
            """,
            employee_id,
            tenant_admin_role_id,
        )
        await tx.connection.execute(
            """
            INSERT INTO auth_identities (employee_id, username, password_hash, is_active)
            VALUES ($1, $2, $3, true)
            """,
            employee_id,
            admin_username,
            hash_password(payload.admin_password),
        )
        await tx.connection.execute(
            """
            INSERT INTO entity_operation_settings (legal_entity_id, late_arrival_threshold_minutes, require_asset_clearance_for_final_payroll)
            VALUES ($1, 15, true)
            ON CONFLICT (legal_entity_id) DO NOTHING
            """,
            legal_entity_id,
        )
        await tx.connection.execute(
            """
            INSERT INTO entity_system_config (
                legal_entity_id, logo_url, logo_text, primary_color, standalone_chat_url,
                linkedin_url, facebook_url, instagram_url,
                allowed_web_punch_ips, geofence_latitude, geofence_longitude, geofence_radius_meters
            )
            VALUES ($1, NULL, 'HR', '#0F172A', NULL, NULL, NULL, NULL, ARRAY[]::text[], NULL, NULL, NULL)
            ON CONFLICT (legal_entity_id) DO NOTHING
            """,
            legal_entity_id,
        )
        await tx.connection.execute(
            """
            INSERT INTO tenant_subscriptions (
                legal_entity_id, attendance_enabled, payroll_enabled, ats_enabled, chat_enabled,
                device_management_enabled, mobile_sync_enabled, assets_enabled, org_chart_enabled, performance_enabled
            )
            VALUES ($1, true, true, true, true, true, true, true, true, true)
            ON CONFLICT (legal_entity_id) DO NOTHING
            """,
            legal_entity_id,
        )
        await tx.connection.execute(
            """
            INSERT INTO entity_leave_policy_settings (
                legal_entity_id, paid_leave_allowance_days, unpaid_leave_allowance_days, eligibility_months,
                enable_birthday_off, enable_day_off
            )
            VALUES ($1, 24, 15, 11, false, false)
            ON CONFLICT (legal_entity_id) DO NOTHING
            """,
            legal_entity_id,
        )
        if resolved_host:
            domain_id = await tx.connection.fetchval(
                """
                INSERT INTO tenant_domains (legal_entity_id, host, subdomain, is_primary, is_active)
                VALUES ($1, $2, $3, true, true)
                RETURNING id
                """,
                legal_entity_id,
                resolved_host,
                subdomain,
            )
        else:
            domain_id = None
        await tx.commit()
    except PostgresError as exc:
        await tx.rollback()
        raise HTTPException(status_code=409, detail=_db_error_message(exc)) from exc
    except Exception:
        await tx.rollback()
        raise

    return {
        'legal_entity_id': str(legal_entity_id),
        'employee_id': str(employee_id),
        'domain_id': str(domain_id) if domain_id else '',
        'admin_username': admin_username,
    }


@app.post('/system/tenants/{legal_entity_id}/domains', status_code=status.HTTP_201_CREATED)
async def create_tenant_domain(
    request: Request,
    legal_entity_id: UUID,
    payload: TenantDomainUpsertRequest,
) -> dict[str, str]:
    actor = await require_actor(request)
    _ensure_settings_access(actor)
    if actor.legal_entity_id != legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='სხვა იურიდიული ერთეულის დომენის შეცვლა აკრძალულია')
    db = get_db_from_request(request)
    domain_id = await db.fetchval(
        """
        INSERT INTO tenant_domains (legal_entity_id, host, subdomain, is_primary, is_active)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id
        """,
        legal_entity_id,
        payload.host.strip().lower(),
        _clean_text(payload.subdomain.lower() if payload.subdomain else None),
        payload.is_primary,
        payload.is_active,
    )
    if payload.is_primary:
        await db.execute(
            """
            UPDATE tenant_domains
               SET is_primary = false,
                   updated_at = now()
             WHERE legal_entity_id = $1
               AND id <> $2
            """,
            legal_entity_id,
            domain_id,
        )
    return {'domain_id': str(domain_id)}


@app.put('/system/tenants/domains/{domain_id}')
async def update_tenant_domain(
    request: Request,
    domain_id: UUID,
    payload: TenantDomainUpsertRequest,
) -> dict[str, str]:
    actor = await require_actor(request)
    _ensure_settings_access(actor)
    db = get_db_from_request(request)
    legal_entity_id = await db.fetchval('SELECT legal_entity_id FROM tenant_domains WHERE id = $1', domain_id)
    if legal_entity_id is None:
        raise HTTPException(status_code=404, detail='კომპანიის დომენი ვერ მოიძებნა')
    if legal_entity_id != actor.legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='სხვა იურიდიული ერთეულის დომენის შეცვლა აკრძალულია')
    await db.execute(
        """
        UPDATE tenant_domains
           SET host = $2,
               subdomain = $3,
               is_primary = $4,
               is_active = $5,
               updated_at = now()
         WHERE id = $1
        """,
        domain_id,
        payload.host.strip().lower(),
        _clean_text(payload.subdomain.lower() if payload.subdomain else None),
        payload.is_primary,
        payload.is_active,
    )
    if payload.is_primary:
        await db.execute(
            """
            UPDATE tenant_domains
               SET is_primary = false,
                   updated_at = now()
             WHERE legal_entity_id = $1
               AND id <> $2
            """,
            legal_entity_id,
            domain_id,
        )
    return {'status': 'updated'}


@app.put('/system/policies/{legal_entity_id}/worksites')
async def update_worksites(
    request: Request,
    legal_entity_id: UUID,
    payload: WorksitesBulkUpdateRequest,
) -> dict[str, str]:
    actor = await require_actor(request)
    if not _is_super_admin(actor):
        raise HTTPException(status_code=403, detail='Only super admins can manage worksites')
    if actor.legal_entity_id != legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='Cross-tenant worksite updates are not allowed')
    db = get_db_from_request(request)
    tx = await db.transaction()
    try:
        await tx.connection.execute(
            """
            UPDATE worksites
               SET is_active = false,
                   updated_at = now()
             WHERE legal_entity_id = $1
            """,
            legal_entity_id,
        )
        for worksite in payload.worksites:
            await tx.connection.execute(
                """
                INSERT INTO worksites (
                    id, legal_entity_id, name, latitude, longitude, radius_meters, address_text,
                    is_active, created_by_employee_id, updated_at
                )
                VALUES (coalesce($1, gen_random_uuid()), $2, $3, $4, $5, $6, $7, $8, $9, now())
                ON CONFLICT (id) DO UPDATE
                   SET name = EXCLUDED.name,
                       latitude = EXCLUDED.latitude,
                       longitude = EXCLUDED.longitude,
                       radius_meters = EXCLUDED.radius_meters,
                       address_text = EXCLUDED.address_text,
                       is_active = EXCLUDED.is_active,
                       updated_at = now()
                """,
                worksite.id,
                legal_entity_id,
                worksite.name.strip(),
                worksite.latitude,
                worksite.longitude,
                worksite.radius_meters,
                worksite.address_text,
                worksite.is_active,
                actor.employee_id,
            )
        await tx.commit()
    except Exception:
        await tx.rollback()
        raise
    await _log_audit_event(
        db,
        actor_employee_id=actor.employee_id,
        legal_entity_id=legal_entity_id,
        action_code='policy.worksites.updated',
        details={'count': len(payload.worksites)},
    )
    return {'status': 'saved'}


@app.post('/system/policies/{legal_entity_id}/middleware-keys', status_code=status.HTTP_201_CREATED)
async def create_middleware_api_key(
    request: Request,
    legal_entity_id: UUID,
    payload: MiddlewareApiKeyCreateRequest,
) -> dict[str, str]:
    actor = await require_actor(request)
    if not _is_super_admin(actor):
        raise HTTPException(status_code=403, detail='Only super admins can create middleware API keys')
    if actor.legal_entity_id != legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='Cross-tenant middleware key creation is not allowed')
    db = get_db_from_request(request)
    raw_key = secrets.token_urlsafe(32)
    key_id = await db.fetchval(
        """
        INSERT INTO device_middleware_api_keys (
            legal_entity_id, key_name, api_key_hash, created_by_employee_id
        )
        VALUES ($1, $2, $3, $4)
        RETURNING id
        """,
        legal_entity_id,
        payload.key_name.strip(),
        _hash_secret_value(raw_key),
        actor.employee_id,
    )
    await _log_audit_event(
        db,
        actor_employee_id=actor.employee_id,
        legal_entity_id=legal_entity_id,
        action_code='policy.middleware_key.created',
        details={'key_id': str(key_id), 'key_name': payload.key_name.strip()},
    )
    return {'key_id': str(key_id), 'api_key': raw_key, 'key_name': payload.key_name.strip()}


@app.delete('/system/policies/{legal_entity_id}/middleware-keys/{key_id}')
async def revoke_middleware_api_key(request: Request, legal_entity_id: UUID, key_id: UUID) -> dict[str, str]:
    actor = await require_actor(request)
    if not _is_super_admin(actor):
        raise HTTPException(status_code=403, detail='Only super admins can revoke middleware API keys')
    if actor.legal_entity_id != legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='Cross-tenant middleware key revoke is not allowed')
    db = get_db_from_request(request)
    updated = await db.execute(
        """
        UPDATE device_middleware_api_keys
           SET revoked_at = now()
         WHERE id = $1
           AND legal_entity_id = $2
        """,
        key_id,
        legal_entity_id,
    )
    if updated.endswith('0'):
        raise HTTPException(status_code=404, detail='Middleware API key not found')
    await _log_audit_event(
        db,
        actor_employee_id=actor.employee_id,
        legal_entity_id=legal_entity_id,
        action_code='policy.middleware_key.revoked',
        details={'key_id': str(key_id)},
    )
    return {'status': 'revoked'}


async def _resolve_middleware_legal_entity_id(request: Request) -> UUID | None:
    middleware_key = (request.headers.get('x-middleware-key') or '').strip()
    if not middleware_key:
        return None
    db = get_db_from_request(request)
    row = await db.fetchrow(
        """
        SELECT id, legal_entity_id
          FROM device_middleware_api_keys
         WHERE api_key_hash = $1
           AND revoked_at IS NULL
         LIMIT 1
        """,
        _hash_secret_value(middleware_key),
    )
    if row is None:
        raise HTTPException(status_code=401, detail='Invalid middleware API key')
    await db.execute('UPDATE device_middleware_api_keys SET last_used_at = now() WHERE id = $1', row['id'])
    return row['legal_entity_id']


@app.post('/api/v1/devices/enroll-card')
async def start_card_enrollment(request: Request, payload: CardEnrollmentStartRequest) -> dict[str, object]:
    actor = await require_actor(request)
    ensure_permission(actor, 'device.manage')
    db = get_db_from_request(request)
    employee = await db.fetchrow(
        'SELECT id, legal_entity_id FROM employees WHERE id = $1 AND deleted_at IS NULL',
        payload.employee_id,
    )
    if employee is None:
        raise HTTPException(status_code=404, detail='Employee not found')
    device_entity_id = await db.fetchval(
        'SELECT legal_entity_id FROM device_registry WHERE id = $1 AND is_active = true',
        payload.device_id,
    )
    if device_entity_id is None:
        raise HTTPException(status_code=404, detail='Device not found')
    if employee['legal_entity_id'] != device_entity_id:
        raise HTTPException(status_code=400, detail='Employee and device must belong to the same company')
    enrollment_token = secrets.token_urlsafe(24)
    session_id = await db.fetchval(
        """
        INSERT INTO device_card_enrollment_sessions (
            legal_entity_id, employee_id, device_id, enrollment_token, expires_at, created_by_employee_id
        )
        VALUES ($1, $2, $3, $4, now() + interval '15 minutes', $5)
        RETURNING id
        """,
        employee['legal_entity_id'],
        payload.employee_id,
        payload.device_id,
        enrollment_token,
        actor.employee_id,
    )
    await _log_audit_event(
        db,
        actor_employee_id=actor.employee_id,
        legal_entity_id=employee['legal_entity_id'],
        action_code='device.card_enrollment.started',
        target_employee_id=payload.employee_id,
        details={'device_id': str(payload.device_id)},
    )
    return {
        'session_id': str(session_id),
        'enrollment_token': enrollment_token,
        'expires_at': (datetime.utcnow() + timedelta(minutes=15)).isoformat() + 'Z',
    }


@app.post('/api/v1/devices/enroll-card/read')
async def complete_card_enrollment(request: Request, payload: CardEnrollmentReadRequest) -> dict[str, object]:
    db = get_db_from_request(request)
    middleware_legal_entity_id = await _resolve_middleware_legal_entity_id(request)
    actor = None
    card_number = _clean_text(payload.card_id)
    if not card_number:
        raise HTTPException(status_code=422, detail='ბარათის ნომერი ცარიელია')
    if middleware_legal_entity_id is None:
        actor = await require_actor(request)
        ensure_permission(actor, 'device.manage')
    session = await db.fetchrow(
        """
        SELECT id, legal_entity_id, employee_id, device_id
          FROM device_card_enrollment_sessions
         WHERE enrollment_token = $1
           AND completed_at IS NULL
           AND expires_at >= now()
         ORDER BY created_at DESC
         LIMIT 1
        """,
        payload.enrollment_token,
    )
    if session is None:
        raise HTTPException(status_code=404, detail='Enrollment session is invalid or expired')
    if middleware_legal_entity_id is not None and middleware_legal_entity_id != session['legal_entity_id']:
        raise HTTPException(status_code=403, detail='Middleware key does not belong to the target company')
    if actor is not None and actor.legal_entity_id != session['legal_entity_id'] and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='Cross-tenant card enrollment is not allowed')
    existing_card_owner = await db.fetchrow(
        """
        SELECT e.id,
               e.first_name,
               e.last_name,
               dr.device_name
          FROM employee_device_identities edi
          JOIN device_registry dr ON dr.id = edi.device_id
          JOIN employees e ON e.id = edi.employee_id
         WHERE dr.legal_entity_id = $1
           AND edi.is_active = true
           AND edi.card_number = $2
           AND edi.employee_id <> $3
           AND e.deleted_at IS NULL
         LIMIT 1
        """,
        session['legal_entity_id'],
        card_number,
        session['employee_id'],
    )
    if existing_card_owner is not None:
        owner_name = f"{existing_card_owner['first_name']} {existing_card_owner['last_name']}".strip()
        raise HTTPException(
            status_code=409,
            detail=f'ეს ბარათი უკვე მიბმულია სხვა თანამშრომელზე: {owner_name or existing_card_owner["id"]}',
        )
    await db.execute(
        """
        WITH employee_row AS (
            SELECT id, employee_number, default_device_user_id, personal_number
              FROM employees
             WHERE id = $1
        ),
        current_identity AS (
            SELECT device_user_id
              FROM employee_device_identities
             WHERE device_id = $2
               AND employee_id = $1
        ),
        next_numeric_pin AS (
            SELECT (coalesce(max(device_user_id::bigint), 0) + 1)::text AS value
              FROM employee_device_identities
             WHERE device_id = $2
               AND device_user_id ~ '^[0-9]+$'
        ),
        chosen_identity AS (
            SELECT coalesce(
                CASE WHEN ci.device_user_id ~ '^[0-9]+$' THEN ci.device_user_id END,
                CASE
                    WHEN e.default_device_user_id ~ '^[0-9]+$'
                     AND NOT EXISTS (
                         SELECT 1
                           FROM employee_device_identities other
                          WHERE other.device_id = $2
                            AND other.device_user_id = e.default_device_user_id
                            AND other.employee_id <> $1
                     )
                    THEN e.default_device_user_id
                END,
                CASE
                    WHEN e.employee_number ~ '^[0-9]+$'
                     AND NOT EXISTS (
                         SELECT 1
                           FROM employee_device_identities other
                          WHERE other.device_id = $2
                            AND other.device_user_id = e.employee_number
                            AND other.employee_id <> $1
                     )
                    THEN e.employee_number
                END,
                next_numeric_pin.value
            ) AS device_user_id,
            right(regexp_replace(COALESCE(e.personal_number, e.employee_number), '\\D', '', 'g'), 4) AS pin_code
              FROM employee_row e
              LEFT JOIN current_identity ci ON true
              CROSS JOIN next_numeric_pin
        )
        INSERT INTO employee_device_identities (device_id, employee_id, device_user_id, pin_code, card_number, is_active, updated_at)
        SELECT $2, $1, device_user_id, pin_code, $3, true, now()
          FROM chosen_identity
        ON CONFLICT (device_id, employee_id) DO UPDATE
           SET device_user_id = EXCLUDED.device_user_id,
               pin_code = EXCLUDED.pin_code,
               card_number = EXCLUDED.card_number,
               is_active = true,
               updated_at = now()
        """,
        session['employee_id'],
        session['device_id'],
        card_number,
    )
    device = await build_driver(db, session['device_id'])
    await queue_employee_upsert_for_device(db, device.device, session['employee_id'])
    await db.execute(
        """
        UPDATE device_card_enrollment_sessions
           SET card_number = $2,
               completed_at = now(),
               updated_at = now()
         WHERE id = $1
        """,
        session['id'],
        card_number,
    )
    await _log_audit_event(
        db,
        actor_employee_id=actor.employee_id if actor else None,
        legal_entity_id=session['legal_entity_id'],
        action_code='device.card_enrolled',
        target_employee_id=session['employee_id'],
        details={'device_id': str(session['device_id']), 'card_number': card_number},
    )
    return {'status': 'completed', 'card_number': card_number}


@app.post('/api/v1/devices/bridge/heartbeat')
async def device_bridge_heartbeat(request: Request) -> dict[str, object]:
    db = get_db_from_request(request)
    legal_entity_id = await _resolve_middleware_legal_entity_id(request)
    if legal_entity_id is None:
        raise HTTPException(status_code=401, detail='Middleware API key is required')
    raw = await request.body()
    parsed: dict[str, Any] = {}
    if raw.strip():
        try:
            blob = json.loads(raw.decode('utf-8'))
            parsed = blob if isinstance(blob, dict) else {}
        except (json.JSONDecodeError, TypeError, ValueError):
            parsed = {}
    payload = MiddlewareBridgeHeartbeatRequest.model_validate(parsed)
    if 'device_pings' in parsed:
        for ping in payload.device_pings:
            if not ping.reachable:
                continue
            await db.execute(
                """
                UPDATE device_registry
                   SET last_seen_at = now(),
                       updated_at = now()
                 WHERE id = $1
                   AND legal_entity_id = $2
                   AND is_active = true
                """,
                ping.device_id,
                legal_entity_id,
            )
    elif not parsed:
        await db.execute(
            """
            UPDATE device_registry
               SET last_seen_at = now(),
                   updated_at = now()
             WHERE legal_entity_id = $1
               AND is_active = true
               AND transport IN ('sdk_bridge', 'raw_socket')
            """,
            legal_entity_id,
        )
    tenant = await db.fetchrow(
        """
        SELECT trade_name
          FROM legal_entities
         WHERE id = $1
        """,
        legal_entity_id,
    )
    return {
        'status': 'ok',
        'legal_entity_id': str(legal_entity_id),
        'tenant_name': tenant['trade_name'] if tenant else None,
        'server_time': datetime.now(timezone.utc).isoformat(),
    }


@app.post('/api/v1/devices/sdk-bridge/commands/next')
async def next_sdk_bridge_commands(
    request: Request,
    payload: MiddlewareDeviceCommandFetchRequest,
) -> dict[str, object]:
    db = get_db_from_request(request)
    legal_entity_id = await _resolve_middleware_legal_entity_id(request)
    if legal_entity_id is None:
        raise HTTPException(status_code=401, detail='Middleware API key is required')

    rows = await db.fetch(
        """
        SELECT
            dcq.id AS command_id,
            dcq.command_type::text AS command_type,
            dcq.payload,
            dr.id AS device_id,
            dr.device_name,
            dr.model,
            dr.serial_number,
            dr.host,
            dr.port,
            dr.password_ciphertext AS password,
            dr.device_timezone,
            dr.metadata
          FROM device_command_queue dcq
          JOIN device_registry dr ON dr.id = dcq.device_id
         WHERE dr.legal_entity_id = $1
           AND dr.is_active = true
           AND dr.brand = 'zk'
           AND dr.transport IN ('sdk_bridge', 'raw_socket')
           AND dcq.status IN ('queued', 'failed')
         ORDER BY dcq.created_at
         LIMIT $2
        """,
        legal_entity_id,
        payload.limit,
    )
    return {
        'commands': [
            {
                'id': str(row['command_id']),
                'command_type': row['command_type'],
                'payload': _json_object(row['payload']),
                'device': {
                    'id': str(row['device_id']),
                    'device_name': row['device_name'],
                    'model': row['model'],
                    'serial_number': row['serial_number'],
                    'host': row['host'],
                    'port': row['port'],
                    'password': row['password'],
                    'device_timezone': row['device_timezone'],
                    'metadata': _json_object(row['metadata']),
                },
            }
            for row in rows
        ],
    }


@app.get('/api/v1/devices/sdk-bridge/devices')
async def list_sdk_bridge_devices(request: Request) -> dict[str, object]:
    db = get_db_from_request(request)
    legal_entity_id = await _resolve_middleware_legal_entity_id(request)
    if legal_entity_id is None:
        raise HTTPException(status_code=401, detail='Middleware API key is required')
    rows = await db.fetch(
        """
        SELECT id,
               device_name,
               model,
               serial_number,
               host,
               port,
               password_ciphertext AS password,
               device_timezone,
               metadata
          FROM device_registry
         WHERE legal_entity_id = $1
           AND is_active = true
           AND brand = 'zk'
           AND transport IN ('sdk_bridge', 'raw_socket')
         ORDER BY device_name
        """,
        legal_entity_id,
    )
    return {
        'devices': [
            {
                'id': str(row['id']),
                'device_name': row['device_name'],
                'model': row['model'],
                'serial_number': row['serial_number'],
                'host': row['host'],
                'port': row['port'],
                'password': row['password'],
                'device_timezone': row['device_timezone'],
                'metadata': _json_object(row['metadata']),
            }
            for row in rows
        ]
    }


@app.post('/api/v1/devices/sdk-bridge/commands/{command_id}/result')
async def complete_sdk_bridge_command(
    request: Request,
    command_id: UUID,
    payload: MiddlewareDeviceCommandResultRequest,
) -> dict[str, str]:
    db = get_db_from_request(request)
    legal_entity_id = await _resolve_middleware_legal_entity_id(request)
    if legal_entity_id is None:
        raise HTTPException(status_code=401, detail='Middleware API key is required')
    status_value = payload.status.strip().lower()
    if status_value not in {'completed', 'failed'}:
        raise HTTPException(status_code=422, detail='Command status must be completed or failed')
    row = await db.fetchrow(
        """
        UPDATE device_command_queue dcq
           SET status = $3::device_command_status,
               attempt_count = attempt_count + 1,
               last_attempt_at = now(),
               last_error = CASE WHEN $3 = 'failed' THEN $4 ELSE NULL END,
               updated_at = now()
          FROM device_registry dr
         WHERE dcq.id = $1
           AND dcq.device_id = dr.id
           AND dr.legal_entity_id = $2
           AND dr.brand = 'zk'
           AND dr.transport IN ('sdk_bridge', 'raw_socket')
         RETURNING dcq.id
        """,
        command_id,
        legal_entity_id,
        status_value,
        (payload.error or '')[:4000],
    )
    if row is None:
        raise HTTPException(status_code=404, detail='SDK bridge command not found')
    return {'status': status_value, 'command_id': str(command_id)}


@app.post('/api/v1/attendance/middleware-import')
async def import_attendance_from_middleware(
    request: Request,
    payload: MiddlewareAttendanceImportRequest,
) -> dict[str, int]:
    db = get_db_from_request(request)
    legal_entity_id = await _resolve_middleware_legal_entity_id(request)
    if legal_entity_id is None:
        raise HTTPException(status_code=401, detail='Middleware API key is required')

    imported_count = 0
    duplicate_count = 0
    unmatched_count = 0
    skipped_count = 0
    device_cache: dict[tuple[str | None, str | None], dict[str, Any] | None] = {}

    for item in payload.logs:
        person_id = item.person_id.strip()
        if not person_id:
            skipped_count += 1
            continue
        numeric_person_id = _numeric_identity_key(person_id)

        employee = await db.fetchrow(
            """
            SELECT e.id
              FROM employees e
              LEFT JOIN employee_device_identities edi
                ON edi.employee_id = e.id
               AND edi.is_active = true
             WHERE e.legal_entity_id = $1
               AND e.deleted_at IS NULL
               AND (
                    e.default_device_user_id = $2
                    OR e.employee_number = $2
                    OR e.personal_number = $2
                    OR edi.device_user_id = $2
                    OR edi.card_number = $2
                    OR edi.pin_code = $2
                    OR (
                        $3::text IS NOT NULL
                        AND (
                            ltrim(coalesce(edi.device_user_id, ''), '0') = $3
                            OR ltrim(coalesce(edi.card_number, ''), '0') = $3
                            OR ltrim(coalesce(edi.pin_code, ''), '0') = $3
                        )
                    )
                    OR (
                        nullif(regexp_replace($2, '[^0-9]', '', 'g'), '') IS NOT NULL
                        AND nullif(regexp_replace(coalesce(edi.card_number, ''), '[^0-9]', '', 'g'), '') IS NOT NULL
                        AND regexp_replace($2, '[^0-9]', '', 'g')
                            = regexp_replace(edi.card_number, '[^0-9]', '', 'g')
                    )
               )
             ORDER BY CASE
                    WHEN e.default_device_user_id = $2 THEN 0
                    WHEN edi.device_user_id = $2 THEN 1
                    WHEN edi.card_number = $2 THEN 2
                    WHEN $3::text IS NOT NULL AND ltrim(coalesce(edi.card_number, ''), '0') = $3 THEN 3
                    WHEN $3::text IS NOT NULL AND ltrim(coalesce(edi.device_user_id, ''), '0') = $3 THEN 4
                    WHEN e.employee_number = $2 THEN 5
                    WHEN e.personal_number = $2 THEN 6
                    ELSE 7
               END
             LIMIT 1
            """,
            legal_entity_id,
            person_id,
            numeric_person_id,
        )
        if employee is None:
            unmatched_count += 1
            continue

        device_lookup_key = (
            item.device_serial.strip() if item.device_serial else None,
            item.device_name.strip() if item.device_name else None,
        )
        if device_lookup_key not in device_cache:
            row = await db.fetchrow(
                """
                SELECT id, device_timezone
                  FROM device_registry
                 WHERE legal_entity_id = $1
                   AND is_active = true
                   AND (
                        ($2::text IS NOT NULL AND serial_number = $2)
                        OR ($3::text IS NOT NULL AND lower(device_name) = lower($3))
                   )
                 ORDER BY last_seen_at DESC NULLS LAST, created_at DESC
                 LIMIT 1
                """,
                legal_entity_id,
                device_lookup_key[0],
                device_lookup_key[1],
            )
            if row is None:
                row = await db.fetchrow(
                    """
                    SELECT id, device_timezone
                      FROM device_registry
                     WHERE legal_entity_id = $1
                       AND is_active = true
                     ORDER BY CASE
                           WHEN brand = 'zk' AND transport IN ('sdk_bridge', 'raw_socket') THEN 0
                           WHEN transport IN ('sdk_bridge', 'raw_socket') THEN 1
                           ELSE 2
                       END,
                       last_seen_at DESC NULLS LAST,
                       created_at DESC
                     LIMIT 1
                    """,
                    legal_entity_id,
                )
            device_cache[device_lookup_key] = dict(row) if row is not None else None
        device_info = device_cache[device_lookup_key]
        device_id = device_info['id'] if device_info is not None else None
        if device_id is None:
            skipped_count += 1
            continue
        event_ts = _middleware_event_ts_utc(
            item.event_ts,
            str(device_info.get('device_timezone') or '') if device_info is not None else 'Asia/Tbilisi',
        )
        duplicate = await db.fetchval(
            """
            SELECT id
              FROM raw_attendance_logs
             WHERE employee_id = $1
               AND device_user_id = $2
               AND event_ts = $3
               AND coalesce(device_id::text, '') = coalesce($4::text, '')
             LIMIT 1
            """,
            employee['id'],
            person_id,
            event_ts,
            str(device_id) if device_id is not None else None,
        )
        if duplicate is not None:
            duplicate_count += 1
            continue

        hardware_reported = _normalize_middleware_direction(item.direction)
        normalized_direction = await _infer_next_attendance_direction(db, employee['id'], event_ts)
        raw_payload_body: dict[str, Any] = dict(item.raw_payload) if isinstance(item.raw_payload, dict) else {}
        raw_payload_body.setdefault('source', 'middleware_import')
        raw_payload_body.setdefault('person_id', person_id)
        raw_payload_body.setdefault('device_serial', item.device_serial)
        raw_payload_body.setdefault('device_name', item.device_name)
        raw_payload_body['hardware_reported_direction'] = item.direction
        raw_payload_body['hardware_normalized_direction'] = hardware_reported
        attendance_log_id = await db.fetchval(
            """
            INSERT INTO raw_attendance_logs (
                device_id, employee_id, device_user_id, event_ts, direction, verify_mode, external_log_id, raw_payload
            )
            VALUES ($1, $2, $3, $4, $5::attendance_direction, $6, $7, $8::jsonb)
            RETURNING id
            """,
            device_id,
            employee['id'],
            person_id,
            event_ts,
            normalized_direction,
            item.verify_mode,
            item.external_log_id,
            json.dumps(raw_payload_body, ensure_ascii=False),
        )
        await _apply_attendance_event_to_work_session(
            db,
            employee['id'],
            normalized_direction,
            event_ts,
            int(attendance_log_id) if attendance_log_id is not None else None,
        )
        await db.execute(
            'UPDATE raw_attendance_logs SET processed_at = now() WHERE id = $1',
            int(attendance_log_id) if attendance_log_id is not None else None,
        )
        imported_count += 1

    await _append_capture_log(
        {
            'captured_at': datetime.utcnow().isoformat() + 'Z',
            'source': 'app.middleware_attendance_import',
            'headers': {key: value for key, value in request.headers.items()},
            'summary': {
                'legal_entity_id': str(legal_entity_id),
                'imported_count': imported_count,
                'duplicate_count': duplicate_count,
                'unmatched_count': unmatched_count,
                'skipped_count': skipped_count,
            },
            'first_logs': [
                {
                    'person_id': item.person_id,
                    'event_ts': item.event_ts.isoformat(),
                    'direction': item.direction,
                    'device_serial': item.device_serial,
                    'device_name': item.device_name,
                }
                for item in payload.logs[:5]
            ],
        }
    )
    return {
        'imported_count': imported_count,
        'duplicate_count': duplicate_count,
        'unmatched_count': unmatched_count,
        'skipped_count': skipped_count,
    }


@app.put('/rbac/employees/{employee_id}/roles')
async def update_employee_roles(request: Request, employee_id: UUID, payload: EmployeeRoleUpdateRequest) -> dict[str, str]:
    actor = await require_actor(request)
    _ensure_settings_access(actor)
    db = get_db_from_request(request)
    employee_entity_id = await db.fetchval('SELECT legal_entity_id FROM employees WHERE id = $1', employee_id)
    if employee_entity_id is None:
        raise HTTPException(status_code=404, detail='თანამშრომელი ვერ მოიძებნა')
    if employee_entity_id != actor.legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='სხვა იურიდიულ ერთეულზე როლების მინიჭება აკრძალულია')
    requested_codes = list(dict.fromkeys(code.upper() for code in payload.role_codes))
    role_rows = await db.fetch('SELECT id, upper(code::text) AS code FROM access_roles WHERE upper(code::text) = ANY($1::text[])', requested_codes)
    if len(role_rows) != len(requested_codes):
        raise HTTPException(status_code=400, detail='ერთი ან რამდენიმე role კოდი არასწორია')
    tx = await db.transaction()
    try:
        await tx.connection.execute('DELETE FROM employee_access_roles WHERE employee_id = $1', employee_id)
        if role_rows:
            await tx.connection.executemany(
                """
                INSERT INTO employee_access_roles (employee_id, access_role_id, assigned_by_employee_id)
                VALUES ($1, $2, $3)
                """,
                [(employee_id, row['id'], actor.employee_id) for row in role_rows],
            )
        await tx.commit()
    except Exception:
        await tx.rollback()
        raise
    return {'status': 'updated'}


@app.put('/system/rbac/roles/{role_code}/permissions')
async def update_role_permissions(request: Request, role_code: str, payload: RolePermissionsUpdateRequest) -> dict[str, object]:
    actor = await require_actor(request)
    _ensure_settings_access(actor)
    db = get_db_from_request(request)
    role = await db.fetchrow(
        """
        SELECT id, upper(code::text) AS code
          FROM access_roles
         WHERE upper(code::text) = $1
         LIMIT 1
        """,
        role_code.upper(),
    )
    if role is None:
        raise HTTPException(status_code=404, detail='Role not found')
    requested_codes = sorted({code for code in payload.permission_codes if code in PERMISSION_DESCRIPTIONS})
    if len(requested_codes) != len(set(payload.permission_codes)):
        invalid_codes = sorted(set(payload.permission_codes) - set(PERMISSION_DESCRIPTIONS))
        if invalid_codes:
            raise HTTPException(status_code=400, detail=f'Unknown permissions: {", ".join(invalid_codes)}')
    base_rows = await db.fetch(
        """
        SELECT permission_code
          FROM access_role_permissions
         WHERE access_role_id = $1
        """,
        role['id'],
    )
    base_permissions = {row['permission_code'] for row in base_rows}
    tx = await db.transaction()
    try:
        await tx.connection.execute(
            """
            DELETE FROM tenant_role_permission_overrides
             WHERE legal_entity_id = $1
               AND access_role_id = $2
            """,
            actor.legal_entity_id,
            role['id'],
        )
        override_rows = []
        for permission_code in sorted(PERMISSION_DESCRIPTIONS):
            desired = permission_code in requested_codes
            if desired != (permission_code in base_permissions):
                override_rows.append((actor.legal_entity_id, role['id'], permission_code, desired, actor.employee_id))
        if override_rows:
            await tx.connection.executemany(
                """
                INSERT INTO tenant_role_permission_overrides (
                    legal_entity_id, access_role_id, permission_code, is_enabled, created_by_employee_id
                )
                VALUES ($1, $2, $3, $4, $5)
                """,
                override_rows,
            )
        await tx.commit()
    except Exception:
        await tx.rollback()
        raise
    await _log_audit_event(
        db,
        actor_employee_id=actor.employee_id,
        legal_entity_id=actor.legal_entity_id,
        action_code='rbac.role_permissions.updated',
        details={'role_code': role['code'], 'permission_codes': requested_codes},
    )
    return {'status': 'updated', 'role_code': role['code'], 'permission_count': len(requested_codes)}


async def _revoke_employee_access(db: Database, employee_id: UUID) -> None:
    await db.execute(
        """
        UPDATE auth_identities
           SET is_active = false,
               updated_at = now()
         WHERE employee_id = $1
        """,
        employee_id,
    )
    await db.execute(
        """
        UPDATE auth_invites
           SET expires_at = now(),
               updated_at = now()
         WHERE employee_id = $1
           AND expires_at > now()
        """,
        employee_id,
    )


async def _log_audit_event(
    db: Database,
    *,
    actor_employee_id: UUID | None,
    legal_entity_id: UUID,
    action_code: str,
    target_employee_id: UUID | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    await db.execute(
        """
        INSERT INTO audit_logs (
            legal_entity_id,
            actor_employee_id,
            target_employee_id,
            action_code,
            details
        )
        VALUES ($1, $2, $3, $4, $5::jsonb)
        """,
        legal_entity_id,
        actor_employee_id,
        target_employee_id,
        action_code,
        json.dumps(details or {}),
    )


def _is_super_admin(actor) -> bool:
    return bool({'ADMIN', 'TENANT_ADMIN'} & actor.role_codes)


def _is_platform_super_admin(actor) -> bool:
    return 'ADMIN' in actor.role_codes


def _ensure_settings_access(actor) -> None:
    ensure_permission(actor, 'settings.manage')


def _ensure_route_tenant(actor, legal_entity_id: UUID) -> None:
    if legal_entity_id != actor.legal_entity_id:
        raise HTTPException(status_code=403, detail='Route legal_entity_id must match the authenticated actor tenant')


async def _get_leave_policy_settings(db: Database, legal_entity_id: UUID) -> dict[str, Any]:
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


async def _resolve_leave_approver_employee_id(db: Database, actor_employee_id: UUID, legal_entity_id: UUID) -> UUID | None:
    employee_row = await db.fetchrow(
        """
        SELECT department_id, coalesce(line_manager_id, manager_employee_id) AS fallback_manager_id
          FROM employees
         WHERE id = $1
        """,
        actor_employee_id,
    )
    if employee_row is None:
        return None
    if employee_row['department_id'] is not None:
        department_approver = await db.fetchval(
            """
            SELECT approver_employee_id
              FROM department_leave_approvers
             WHERE legal_entity_id = $1
               AND department_id = $2
            """,
            legal_entity_id,
            employee_row['department_id'],
        )
        if department_approver is not None:
            return department_approver
    global_approver = await db.fetchval(
        'SELECT global_leave_approver_employee_id FROM entity_leave_policy_settings WHERE legal_entity_id = $1',
        legal_entity_id,
    )
    return global_approver or employee_row['fallback_manager_id']


def _is_sick_leave_code(code: str | None) -> bool:
    return (code or '').upper() in {'SICK', 'SICK_LEAVE', 'BULLETIN', 'MEDICAL', 'MEDICAL_BULLETIN'}


def _is_birthday_leave_code(code: str | None) -> bool:
    return (code or '').upper() in {'BIRTHDAY_OFF', 'BIRTHDAY', 'BIRTHDAY_LEAVE'}


def _is_day_off_code(code: str | None) -> bool:
    return (code or '').upper() in {'DAY_OFF', 'DAYOFF', 'PERSONAL_DAY'}


async def _create_leave_request(
    db: Database,
    *,
    actor,
    leave_type_id: UUID,
    start_date: date,
    end_date: date,
    reason: str,
    doctor_note: UploadFile | None,
) -> UUID:
    if end_date < start_date:
        raise HTTPException(status_code=400, detail='End date cannot be earlier than start date')
    leave_type = await db.fetchrow(
        """
        SELECT id, upper(code::text) AS code, is_active, is_paid, annual_allowance_days
          FROM leave_types
         WHERE id = $1
           AND legal_entity_id = $2
        """,
        leave_type_id,
        actor.legal_entity_id,
    )
    if leave_type is None or not leave_type['is_active']:
        raise HTTPException(status_code=400, detail='Selected leave type is not available')

    policy = await _get_leave_policy_settings(db, actor.legal_entity_id)
    leave_code = leave_type['code']
    if leave_type['is_paid'] and not _is_sick_leave_code(leave_type['code']):
        hire_date = await db.fetchval('SELECT hire_date FROM employees WHERE id = $1', actor.employee_id)
        if hire_date is not None:
            completed_months = max(
                0,
                (start_date.year - hire_date.year) * 12
                + (start_date.month - hire_date.month)
                - (1 if start_date.day < hire_date.day else 0),
            )
            if completed_months < int(policy['eligibility_months'] or 0):
                raise HTTPException(status_code=400, detail='Paid leave is not available yet under the eligibility rule')
    if _is_birthday_leave_code(leave_code) and not policy['enable_birthday_off']:
        raise HTTPException(status_code=400, detail='Birthday off is disabled in company policies')
    if _is_day_off_code(leave_code) and not policy['enable_day_off']:
        raise HTTPException(status_code=400, detail='Day off is disabled in company policies')
    if _is_sick_leave_code(leave_code) and (doctor_note is None or not doctor_note.filename):
        raise HTTPException(status_code=400, detail='Medical certificate is required for sick leave')

    approver_employee_id = await _resolve_leave_approver_employee_id(db, actor.employee_id, actor.legal_entity_id)
    requested_days = await db.fetchval(
        """
        SELECT count(*)
          FROM generate_series($1::date, $2::date, interval '1 day') AS d(day)
         WHERE extract(isodow FROM d.day) < 6
        """,
        start_date,
        end_date,
    )

    attachment_url = None
    attachment_size = None
    if doctor_note and doctor_note.filename:
        attachment_url, attachment_size = await _store_upload(doctor_note, LEAVE_UPLOADS_DIR, 'doctor_note')

    leave_request_id = await db.fetchval(
        """
        INSERT INTO leave_requests (
            employee_id,
            leave_type_id,
            manager_employee_id,
            start_date,
            end_date,
            requested_days,
            reason,
            status,
            approval_stage,
            attachment_url
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, 'submitted', 'manager_pending', $8)
        RETURNING id
        """,
        actor.employee_id,
        leave_type_id,
        approver_employee_id,
        start_date,
        end_date,
        Decimal(str(requested_days or 0)),
        reason.strip(),
        attachment_url,
    )
    if attachment_url:
        await db.execute(
            """
            INSERT INTO leave_request_files (leave_request_id, file_name, file_url, content_type, file_size)
            VALUES ($1, $2, $3, $4, $5)
            """,
            leave_request_id,
            _safe_file_name(doctor_note.filename or 'doctor_note.bin'),
            attachment_url,
            doctor_note.content_type,
            attachment_size,
        )
    await _log_audit_event(
        db,
        actor_employee_id=actor.employee_id,
        legal_entity_id=actor.legal_entity_id,
        action_code='leave.request.submitted',
        target_employee_id=approver_employee_id,
        details={
            'leave_request_id': str(leave_request_id),
            'leave_type_id': str(leave_type_id),
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'requested_days': int(requested_days or 0),
            'requires_attachment': _is_sick_leave_code(leave_code),
            'attachment_uploaded': bool(attachment_url),
        },
    )
    await send_leave_approval_request(db, leave_request_id)
    return leave_request_id


@app.post('/employees/{employee_id}/deactivate')
async def deactivate_employee(request: Request, employee_id: UUID) -> dict[str, str]:
    actor = await require_actor(request)
    ensure_permission(actor, 'employee.manage')
    db = get_db_from_request(request)
    employee = await db.fetchrow(
        """
        SELECT legal_entity_id, employment_status
          FROM employees
         WHERE id = $1
           AND deleted_at IS NULL
        """,
        employee_id,
    )
    if employee is None:
        raise HTTPException(status_code=404, detail='Employee not found')
    if employee['legal_entity_id'] != actor.legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='Cross-tenant deactivation is not allowed')
    synced_devices = await fetch_employee_synced_devices(db, employee_id)
    await db.execute(
        """
        UPDATE employees
           SET employment_status = 'suspended',
               updated_at = now()
         WHERE id = $1
        """,
        employee_id,
    )
    await delete_employee_from_all_devices(db, employee_id)
    await _revoke_employee_access(db, employee_id)
    await _log_audit_event(
        db,
        actor_employee_id=actor.employee_id,
        legal_entity_id=actor.legal_entity_id,
        action_code='employee.deactivated',
        target_employee_id=employee_id,
        details={
            'employment_status': 'suspended',
            'removed_device_ids': [device['id'] for device in synced_devices],
            'removed_device_count': len(synced_devices),
        },
    )
    return {'status': 'deactivated'}


@app.delete('/employees/{employee_id}')
async def archive_employee(request: Request, employee_id: UUID) -> dict[str, str]:
    actor = await require_actor(request)
    ensure_permission(actor, 'employee.manage')
    db = get_db_from_request(request)
    employee = await db.fetchrow(
        """
        SELECT legal_entity_id, deleted_at
          FROM employees
         WHERE id = $1
        """,
        employee_id,
    )
    if employee is None or employee['deleted_at'] is not None:
        raise HTTPException(status_code=404, detail='Employee not found')
    if employee['legal_entity_id'] != actor.legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='Cross-tenant delete is not allowed')
    synced_devices = await fetch_employee_synced_devices(db, employee_id)
    await db.execute(
        """
        UPDATE employees
           SET employment_status = 'terminated',
               termination_date = coalesce(termination_date, greatest(hire_date, (timezone('Asia/Tbilisi', now()))::date)),
               deleted_at = now(),
               updated_at = now()
         WHERE id = $1
        """,
        employee_id,
    )
    await delete_employee_from_all_devices(db, employee_id)
    await _revoke_employee_access(db, employee_id)
    await _log_audit_event(
        db,
        actor_employee_id=actor.employee_id,
        legal_entity_id=actor.legal_entity_id,
        action_code='employee.archived',
        target_employee_id=employee_id,
        details={
            'deleted_at': datetime.utcnow().isoformat(),
            'removed_device_ids': [device['id'] for device in synced_devices],
            'removed_device_count': len(synced_devices),
        },
    )
    return {'status': 'archived'}


@app.post('/employees/{employee_id}/separation')
async def record_separation(request: Request, employee_id: UUID, payload: SeparationRecordRequest) -> dict[str, str]:
    actor = await require_actor(request)
    ensure_permission(actor, 'employee.manage')
    db = get_db_from_request(request)
    await db.execute(
        """
        INSERT INTO employee_separations (
            employee_id, separation_date, reason_category, reason_details, eligible_rehire, created_by_employee_id
        ) VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (employee_id) DO UPDATE
           SET separation_date = EXCLUDED.separation_date,
               reason_category = EXCLUDED.reason_category,
               reason_details = EXCLUDED.reason_details,
               eligible_rehire = EXCLUDED.eligible_rehire,
               created_by_employee_id = EXCLUDED.created_by_employee_id
        """,
        employee_id,
        payload.separation_date,
        payload.reason_category,
        payload.reason_details,
        payload.eligible_rehire,
        actor.employee_id,
    )
    await db.execute(
        "UPDATE employees SET termination_date = $2, employment_status = 'terminated', updated_at = now() WHERE id = $1",
        employee_id,
        payload.separation_date,
    )
    return {'status': 'recorded'}


@app.post('/ess/leave/request', status_code=status.HTTP_201_CREATED)
async def create_leave_request(
    request: Request,
    leave_type_id: UUID = Form(...),
    start_date: date = Form(...),
    end_date: date = Form(...),
    reason: str = Form(...),
    doctor_note: UploadFile | None = File(default=None),
) -> dict[str, str]:
    actor = await require_actor(request)
    db = get_db_from_request(request)
    leave_request_id = await _create_leave_request(
        db,
        actor=actor,
        leave_type_id=leave_type_id,
        start_date=start_date,
        end_date=end_date,
        reason=reason,
        doctor_note=doctor_note,
    )
    return {'leave_request_id': str(leave_request_id)}


@app.post('/ess/leave/sick', status_code=status.HTTP_201_CREATED)
async def create_sick_leave_request(
    request: Request,
    start_date: date = Form(...),
    end_date: date = Form(...),
    reason: str = Form(...),
    doctor_note: UploadFile | None = File(default=None),
) -> dict[str, str]:
    actor = await require_actor(request)
    db = get_db_from_request(request)
    leave_type_id = await db.fetchval(
        """
        SELECT id
          FROM leave_types
         WHERE legal_entity_id = $1
           AND upper(code::text) IN ('SICK', 'SICK_LEAVE', 'BULLETIN')
           AND is_active = true
         ORDER BY code
         LIMIT 1
        """,
        actor.legal_entity_id,
    )
    if leave_type_id is None:
        raise HTTPException(status_code=400, detail='Sick leave type is not configured yet')
    leave_request_id = await _create_leave_request(
        db,
        actor=actor,
        leave_type_id=leave_type_id,
        start_date=start_date,
        end_date=end_date,
        reason=reason,
        doctor_note=doctor_note,
    )
    return {'leave_request_id': str(leave_request_id)}

@app.post('/timesheets/{employee_id}/{year}/{month}/recalculate')
async def recalculate_monthly_timesheet(request: Request, employee_id: UUID, year: int, month: int) -> dict[str, object]:
    actor = await require_actor(request)
    try:
        ensure_can_export_payroll(actor)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail='თვე უნდა იყოს 1-დან 12-მდე')
    db = get_db_from_request(request)
    await _ensure_payroll_dashboard_enabled(db, actor.legal_entity_id)
    employee_row = await db.fetchrow(
        'SELECT legal_entity_id FROM employees WHERE id = $1 AND deleted_at IS NULL',
        employee_id,
    )
    if employee_row is None:
        raise HTTPException(status_code=404, detail='Employee was not found')
    if employee_row['legal_entity_id'] != actor.legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='Employee belongs to another legal entity')
    result = await build_monthly_timesheet_from_db(db, employee_id, year, month)
    await persist_monthly_timesheet(db, result, actor.employee_id)
    return {
        'employee_id': str(result.employee_id),
        'year': year,
        'month': month,
        'total_minutes': result.total_minutes,
        'night_minutes': result.night_minutes,
        'holiday_minutes': result.holiday_minutes,
        'overtime_minutes': result.overtime_minutes,
        'incomplete_session_count': result.incomplete_session_count,
        'gross_pay': str(result.payroll.gross_pay),
        'employee_pension_amount': str(result.payroll.employee_pension_amount),
        'income_tax_amount': str(result.payroll.income_tax_amount),
        'net_pay': str(result.payroll.net_pay),
    }


@app.get('/timesheets/{employee_id}/{year}/{month}/export.xlsx')
async def export_employee_timesheet_xlsx(request: Request, employee_id: UUID, year: int, month: int) -> Response:
    actor = await require_actor(request)
    try:
        ensure_can_export_payroll(actor)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    db = get_db_from_request(request)
    await _ensure_payroll_dashboard_enabled(db, actor.legal_entity_id)
    employee_row = await db.fetchrow(
        'SELECT legal_entity_id FROM employees WHERE id = $1 AND deleted_at IS NULL',
        employee_id,
    )
    if employee_row is None:
        raise HTTPException(status_code=404, detail='Employee was not found')
    if employee_row['legal_entity_id'] != actor.legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='Employee belongs to another legal entity')
    result = await build_monthly_timesheet_from_db(db, employee_id, year, month)
    await persist_monthly_timesheet(db, result, actor.employee_id)
    rows = [
        ['თანამშრომელი', str(result.employee_id)],
        ['წელი', str(year)],
        ['თვე', str(month)],
        ['ნამუშევარი საათები', f'{round(result.total_minutes / 60, 2)}'],
        ['ზეგანაკვეთური საათები', f'{round(result.overtime_minutes / 60, 2)}'],
        ['ღამის საათები', f'{round(result.night_minutes / 60, 2)}'],
        ['დღესასწაულის საათები', f'{round(result.holiday_minutes / 60, 2)}'],
        ['მთლიანი ხელფასი', str(result.payroll.gross_pay)],
        ['დასარიცხი გადასახადი', str(result.payroll.income_tax_amount)],
        ['გასაცემი ხელფასი', str(result.payroll.net_pay)],
    ]
    workbook = _build_minimal_xlsx('Timesheet', ['ველი', 'მნიშვნელობა'], rows)
    response = Response(
        content=workbook,
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response.headers['Content-Disposition'] = f'attachment; filename=timesheet_{year}_{month:02d}.xlsx'
    return response


@app.get('/timesheets/{employee_id}/{year}/{month}/export.pdf')
async def export_employee_timesheet_pdf(request: Request, employee_id: UUID, year: int, month: int) -> Response:
    actor = await require_actor(request)
    try:
        ensure_can_export_payroll(actor)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    db = get_db_from_request(request)
    await _ensure_payroll_dashboard_enabled(db, actor.legal_entity_id)
    employee_row = await db.fetchrow(
        'SELECT legal_entity_id FROM employees WHERE id = $1 AND deleted_at IS NULL',
        employee_id,
    )
    if employee_row is None:
        raise HTTPException(status_code=404, detail='Employee was not found')
    if employee_row['legal_entity_id'] != actor.legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='Employee belongs to another legal entity')
    result = await build_monthly_timesheet_from_db(db, employee_id, year, month)
    await persist_monthly_timesheet(db, result, actor.employee_id)
    pdf = _build_simple_table_pdf(
        'Georgian Timesheet',
        [
            f'Employee: {result.employee_id}',
            f'Period: {year}-{month:02d}',
            f'Total hours: {round(result.total_minutes / 60, 2)}',
            f'Overtime: {round(result.overtime_minutes / 60, 2)}',
            f'Night: {round(result.night_minutes / 60, 2)}',
            f'Holiday: {round(result.holiday_minutes / 60, 2)}',
            f'Gross pay: {result.payroll.gross_pay}',
            f'Income tax: {result.payroll.income_tax_amount}',
            f'Net pay: {result.payroll.net_pay}',
        ],
    )
    response = Response(content=pdf, media_type='application/pdf')
    response.headers['Content-Disposition'] = f'inline; filename=timesheet_{year}_{month:02d}.pdf'
    return response


@app.get('/attendance/review-queue')
async def attendance_review_queue(request: Request) -> list[dict[str, object]]:
    actor = await require_actor(request)
    ensure_permission(actor, 'attendance.review')
    db = get_db_from_request(request)
    if actor.has('attendance.read_all'):
        rows = await db.fetch(
            """
            SELECT arf.id, arf.employee_id, e.employee_number, e.first_name, e.last_name,
                   arf.work_date, arf.flag_type, arf.severity, arf.details, arf.raised_at
              FROM attendance_review_flags arf
              JOIN employees e ON e.id = arf.employee_id
             WHERE arf.resolved_at IS NULL
             ORDER BY arf.raised_at DESC
            """
        )
    else:
        rows = await db.fetch(
            """
            SELECT arf.id, arf.employee_id, e.employee_number, e.first_name, e.last_name,
                   arf.work_date, arf.flag_type, arf.severity, arf.details, arf.raised_at
              FROM attendance_review_flags arf
              JOIN employees e ON e.id = arf.employee_id
             WHERE arf.resolved_at IS NULL
               AND e.department_id = ANY($1::uuid[])
             ORDER BY arf.raised_at DESC
            """,
            list(actor.managed_department_ids),
        )
    return [dict(row) for row in rows]


@app.get('/dashboard/summary')
async def dashboard_summary(request: Request) -> dict[str, object]:
    actor = await require_actor(request)
    if not (actor.has('attendance.read_all') or actor.has('employee.manage') or bool({'ADMIN', 'TENANT_ADMIN'} & actor.role_codes)):
        raise HTTPException(status_code=403, detail='Dashboard summary is available only for company-wide operations access')
    db = get_db_from_request(request)
    await _ensure_company_dashboard_enabled(db, actor.legal_entity_id)
    headcounts = await db.fetchrow(
        """
        SELECT
            count(*) FILTER (WHERE employment_status = 'active') AS active_employees,
            count(*) FILTER (WHERE employment_status = 'terminated') AS terminated_employees,
            count(*) AS total_employees
          FROM employees
         WHERE legal_entity_id = $1
           AND deleted_at IS NULL
        """,
        actor.legal_entity_id,
    )
    open_flags = await db.fetchval(
        """
        SELECT count(*)
         FROM attendance_review_flags arf
          JOIN employees e ON e.id = arf.employee_id
         WHERE e.legal_entity_id = $1
           AND e.deleted_at IS NULL
           AND arf.resolved_at IS NULL
        """,
        actor.legal_entity_id,
    )
    open_leave = await db.fetchval(
        """
        SELECT count(*)
         FROM leave_requests lr
          JOIN employees e ON e.id = lr.employee_id
         WHERE e.legal_entity_id = $1
           AND e.deleted_at IS NULL
           AND lr.status = 'submitted'
        """,
        actor.legal_entity_id,
    )
    devices_online = await db.fetchval(
        """
        SELECT count(*)
          FROM device_registry
         WHERE legal_entity_id = $1
           AND is_active = true
           AND transport::text IN ('sdk_bridge', 'raw_socket', 'adms', 'adms_push')
           AND last_seen_at >= now() - interval '10 minutes'
        """,
        actor.legal_entity_id,
    )
    offline_device_alerts = await db.fetchval(
        """
        SELECT count(*)
          FROM device_registry
         WHERE legal_entity_id = $1
           AND is_active = true
           AND transport::text IN ('sdk_bridge', 'raw_socket', 'adms', 'adms_push')
           AND (last_seen_at IS NULL OR last_seen_at < now() - interval '10 minutes')
        """,
        actor.legal_entity_id,
    )
    offboarding_open = await db.fetchval(
        """
        SELECT count(*)
         FROM offboarding_clearances oc
          JOIN employees e ON e.id = oc.employee_id
         WHERE e.legal_entity_id = $1
           AND e.deleted_at IS NULL
           AND oc.status <> 'cleared'
        """,
        actor.legal_entity_id,
    )
    return {
        'legal_entity_id': str(actor.legal_entity_id),
        'active_employees': int(headcounts['active_employees'] or 0),
        'terminated_employees': int(headcounts['terminated_employees'] or 0),
        'total_employees': int(headcounts['total_employees'] or 0),
        'open_attendance_flags': int(open_flags or 0),
        'pending_leave_approvals': int(open_leave or 0),
        'devices_online': int(devices_online or 0),
        'offline_device_alerts': int(offline_device_alerts or 0),
        'open_offboarding_clearances': int(offboarding_open or 0),
    }


@app.post('/payroll/drafts/generate')
async def generate_payroll_draft(request: Request, payload: PayrollDraftGenerateRequest) -> dict[str, object]:
    actor = await require_actor(request)
    try:
        ensure_can_export_payroll(actor)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    db = get_db_from_request(request)
    await _ensure_payroll_dashboard_enabled(db, actor.legal_entity_id)
    if payload.department_id is not None:
        department_entity_id = await db.fetchval('SELECT legal_entity_id FROM departments WHERE id = $1', payload.department_id)
        if department_entity_id is None:
            raise HTTPException(status_code=404, detail='Department was not found')
        if department_entity_id != actor.legal_entity_id:
            raise HTTPException(status_code=403, detail='Department belongs to another legal entity')

    employee_rows = await db.fetch(
        """
        SELECT id, employee_number, first_name || ' ' || last_name AS full_name, termination_date
          FROM employees
         WHERE legal_entity_id = $1
           AND deleted_at IS NULL
           AND employment_status IN ('active', 'suspended', 'terminated')
           AND ($2::uuid IS NULL OR department_id = $2)
         ORDER BY employee_number
        """,
        actor.legal_entity_id,
        payload.department_id,
    )
    generated = 0
    skipped_for_holds = 0
    preview: list[dict[str, object]] = []
    for employee in employee_rows:
        active_hold = await db.fetchval(
            'SELECT 1 FROM final_payroll_holds WHERE employee_id = $1 AND resolved_at IS NULL',
            employee['id'],
        )
        if employee['termination_date'] is not None and active_hold:
            skipped_for_holds += 1
            continue
        result = await build_monthly_timesheet_from_db(db, employee['id'], payload.year, payload.month)
        await persist_monthly_timesheet(db, result, actor.employee_id)
        generated += 1
        if len(preview) < 8:
            preview.append(
                {
                    'employee_id': str(employee['id']),
                    'employee_number': employee['employee_number'],
                    'employee_name': employee['full_name'],
                    'salary_type': result.payroll.salary_type,
                    'gross_pay': str(result.payroll.gross_pay),
                    'net_pay': str(result.payroll.net_pay),
                }
            )
    return {
        'status': 'generated',
        'generated_count': generated,
        'skipped_for_holds': skipped_for_holds,
        'year': payload.year,
        'month': payload.month,
        'department_id': str(payload.department_id) if payload.department_id else None,
        'preview': preview,
    }


@app.get('/payroll/export/{year}/{month}')
async def payroll_export(request: Request, year: int, month: int, department_id: UUID | None = None) -> Response:
    actor = await require_actor(request)
    try:
        ensure_can_export_payroll(actor)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    db = get_db_from_request(request)
    await _ensure_payroll_dashboard_enabled(db, actor.legal_entity_id)
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail='თვე უნდა იყოს 1-დან 12-მდე')
    db = get_db_from_request(request)
    await _ensure_payroll_dashboard_enabled(db, actor.legal_entity_id)
    if department_id is not None:
        department_entity_id = await db.fetchval('SELECT legal_entity_id FROM departments WHERE id = $1', department_id)
        if department_entity_id is None:
            raise HTTPException(status_code=404, detail='Department was not found')
        if department_entity_id != actor.legal_entity_id:
            raise HTTPException(status_code=403, detail='Department belongs to another legal entity')
    employee_rows = await db.fetch(
        """
        SELECT id, employee_number, first_name || ' ' || last_name AS full_name, termination_date
          FROM employees
         WHERE legal_entity_id = $1
           AND deleted_at IS NULL
           AND employment_status IN ('active', 'suspended', 'terminated')
           AND ($2::uuid IS NULL OR department_id = $2)
         ORDER BY employee_number
        """,
        actor.legal_entity_id,
        department_id,
    )
    results = []
    employee_index: dict[UUID, tuple[str, str]] = {}
    skipped_for_holds = 0
    for employee in employee_rows:
        active_hold = await db.fetchval(
            'SELECT 1 FROM final_payroll_holds WHERE employee_id = $1 AND resolved_at IS NULL',
            employee['id'],
        )
        if employee['termination_date'] is not None and active_hold:
            skipped_for_holds += 1
            continue
        result = await build_monthly_timesheet_from_db(db, employee['id'], year, month)
        await persist_monthly_timesheet(db, result, actor.employee_id)
        results.append(result)
        employee_index[employee['id']] = (employee['employee_number'], employee['full_name'])
    rows = payroll_export_rows(results, employee_index)

    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            'employee_id',
            'employee_number',
            'full_name',
            'year',
            'month',
            'salary_type',
            'total_hours',
            'night_hours',
            'overtime_hours',
            'holiday_hours',
            'hourly_rate',
            'regular_pay',
            'overtime_pay',
            'night_pay',
            'holiday_pay',
            'gross_pay',
            'employee_pension_amount',
            'income_tax_amount',
            'net_pay',
        ],
    )
    writer.writeheader()
    writer.writerows(rows)
    response = Response(content=buffer.getvalue(), media_type='text/csv')
    suffix = f'_{department_id}' if department_id else ''
    response.headers['Content-Disposition'] = f'attachment; filename=payroll_{year}_{month:02d}{suffix}.csv'
    response.headers['X-Skipped-Final-Payroll-Holds'] = str(skipped_for_holds)
    return response
