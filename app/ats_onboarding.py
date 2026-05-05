from __future__ import annotations

import secrets
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from urllib.parse import urlencode
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from .api_support import get_db_from_request, require_actor
from .auth import hash_password
from .config import settings
from .device_middleware import prepare_employee_device_profiles
from .mail_engine import send_and_log_email
from .rbac import apply_rls_context, ensure_permission
from .tenant_integrity import ensure_employee_reference_tenant

ATS_ROUTER = APIRouter(prefix='/ats', tags=['ats-onboarding'])
GEORGIA_TZ = ZoneInfo('Asia/Tbilisi')
CV_KEYWORD_STOPWORDS = {
    'and', 'the', 'for', 'with', 'from', 'that', 'this', 'your', 'will', 'have', 'has',
    'are', 'you', 'our', 'job', 'role', 'team', 'work', 'year', 'years', 'plus', 'using',
    'experience', 'skills', 'required', 'preferred', 'candidate', 'position', 'must',
}


def q2(value: Decimal) -> Decimal:
    return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


class QuizOptionCreate(BaseModel):
    option_key: str
    option_text: str
    is_correct: bool = False


class QuizQuestionCreate(BaseModel):
    question_text: str
    options: list[QuizOptionCreate]


class CourseModuleCreate(BaseModel):
    module_type: Literal['video', 'quiz']
    title: str
    description: str | None = None
    media_url: str | None = None
    duration_seconds: int | None = Field(default=None, ge=0)
    passing_score: int | None = Field(default=None, ge=0, le=100)
    questions: list[QuizQuestionCreate] = Field(default_factory=list)


class OnboardingCourseCreateRequest(BaseModel):
    legal_entity_id: UUID
    code: str
    name_en: str
    name_ka: str
    description: str | None = None
    modules: list[CourseModuleCreate]


class HirePayload(BaseModel):
    hire_date: date
    pay_policy_id: UUID
    base_salary: Decimal = Field(ge=0)
    personal_number: str | None = None
    email: EmailStr | None = None
    mobile_phone: str | None = None
    manager_employee_id: UUID | None = None
    onboarding_course_id: UUID | None = None
    access_role_codes: list[str] = Field(default_factory=lambda: ['EMPLOYEE'])


class MoveCandidateStageRequest(BaseModel):
    stage_code: str
    comment: str | None = None
    hire_payload: HirePayload | None = None


class InterviewScheduleRequest(BaseModel):
    scheduled_at: datetime
    duration_minutes: int = Field(default=45, ge=15, le=240)
    notes: str | None = None


class QuizSubmitRequest(BaseModel):
    selected_option_ids: list[UUID]


class VideoCompletionRequest(BaseModel):
    watched_seconds: int = Field(default=0, ge=0)


async def _generate_employee_number(conn: object, legal_entity_id: UUID) -> str:
    current_year = datetime.now().year
    pattern = rf'^EMP-{current_year}-(\d+)$'
    next_serial = await conn.fetchval(
        """
        SELECT coalesce(
            max((regexp_match(employee_number, $2))[1]::bigint),
            0
        ) + 1
          FROM employees
         WHERE legal_entity_id = $1
           AND employee_number ~ $2
        """,
        legal_entity_id,
        pattern,
    )
    return f"EMP-{current_year}-{int(next_serial):05d}"


async def _assign_course(conn: object, employee_id: UUID, course_id: UUID, assigned_by_employee_id: UUID | None) -> UUID:
    assignment_id = await conn.fetchval(
        """
        INSERT INTO onboarding_course_assignments (employee_id, course_id, assigned_by_employee_id, due_at, status)
        VALUES ($1, $2, $3, now() + interval '14 days', 'assigned')
        RETURNING id
        """,
        employee_id,
        course_id,
        assigned_by_employee_id,
    )
    modules = await conn.fetch(
        'SELECT id FROM onboarding_course_modules WHERE course_id = $1 ORDER BY sort_order',
        course_id,
    )
    await conn.executemany(
        """
        INSERT INTO onboarding_assignment_modules (assignment_id, module_id, status)
        VALUES ($1, $2, 'assigned')
        """,
        [(assignment_id, module['id']) for module in modules],
    )
    return assignment_id


def _candidate_full_name(row: object) -> str:
    first_name = str(row['first_name'] or '').strip()  # type: ignore[index]
    last_name = str(row['last_name'] or '').strip()  # type: ignore[index]
    return f'{first_name} {last_name}'.strip() or 'Candidate'


def _google_calendar_event_link(*, title: str, start_at: datetime, end_at: datetime, details: str | None = None) -> str:
    localized_start = start_at if start_at.tzinfo else start_at.replace(tzinfo=GEORGIA_TZ)
    localized_end = end_at if end_at.tzinfo else end_at.replace(tzinfo=GEORGIA_TZ)
    start_utc = localized_start.astimezone(tz=ZoneInfo('UTC')).strftime('%Y%m%dT%H%M%SZ')
    end_utc = localized_end.astimezone(tz=ZoneInfo('UTC')).strftime('%Y%m%dT%H%M%SZ')
    return f"https://calendar.google.com/calendar/render?{urlencode({
        'action': 'TEMPLATE',
        'text': title,
        'dates': f'{start_utc}/{end_utc}',
        'details': details or '',
    })}"


def _extract_keyword_candidates(text: str) -> list[str]:
    raw_keywords = re.findall(r"[A-Za-z0-9+#.]{3,}", text.lower())
    ordered: list[str] = []
    seen = set()
    for keyword in raw_keywords:
        if keyword in CV_KEYWORD_STOPWORDS:
            continue
        if keyword.isdigit():
            continue
        if keyword not in seen:
            seen.add(keyword)
            ordered.append(keyword)
    return ordered


async def analyze_candidate_application(db, application_id: UUID) -> dict[str, object]:
    row = await db.fetchrow(
        """
        SELECT ca.id,
               ca.application_payload,
               ca.cv_extracted_text,
               c.first_name,
               c.last_name,
               c.email,
               c.phone,
               c.city,
               c.current_company,
               c.current_position,
               c.notes,
               coalesce(jp.public_description, jp.description, '') AS posting_text,
               coalesce(jp.title_en, '') AS posting_title
          FROM candidate_applications ca
          JOIN candidates c ON c.id = ca.candidate_id
          JOIN job_postings jp ON jp.id = ca.job_posting_id
         WHERE ca.id = $1
        """,
        application_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail='Candidate application not found')

    answer_payload = row['application_payload'] or {}
    answer_text = ''
    if isinstance(answer_payload, dict):
        answers = answer_payload.get('answers')
        if isinstance(answers, dict):
            answer_text = ' '.join(str(value) for value in answers.values() if value is not None)

    candidate_text = ' '.join(
        part for part in [
            row['cv_extracted_text'],
            answer_text,
            row['current_position'],
            row['current_company'],
            row['notes'],
            row['city'],
        ]
        if part
    ).lower()
    posting_text = f"{row['posting_title']} {row['posting_text']}".strip().lower()

    keywords = _extract_keyword_candidates(posting_text)[:30]
    matched_keywords = [keyword for keyword in keywords if candidate_text and keyword in candidate_text]
    if keywords and candidate_text:
        score = round((len(matched_keywords) / len(keywords)) * 100, 2)
    else:
        score = 0.0
    score = min(max(score, 0.0), 100.0)

    summary = (
        f"Matched {len(matched_keywords)} of {len(keywords)} hiring keywords"
        + (f": {', '.join(matched_keywords[:8])}" if matched_keywords else '.')
    )

    await db.execute(
        """
        UPDATE candidate_applications
           SET compatibility_score = $2,
               compatibility_summary = $3,
               updated_at = now()
         WHERE id = $1
        """,
        application_id,
        score,
        summary,
    )
    return {
        'score': score,
        'summary': summary,
        'matched_keywords': matched_keywords,
    }


def _candidate_invite_link(token: str) -> str:
    return f"{settings.public_base_url}/ux/app?invite_token={token}"


def _candidate_invite_email_html(
    *,
    employee_name: str,
    invite_link: str,
    department_name: str | None,
    job_role_title: str | None,
) -> str:
    role_line = f"{job_role_title or 'Team Member'}"
    department_line = department_name or 'ITGS HR'
    return f"""
    <div style="margin:0;padding:32px;background:#edf2ff;font-family:'Segoe UI',Arial,sans-serif;color:#172033;">
      <div style="max-width:640px;margin:0 auto;background:rgba(255,255,255,0.98);border-radius:28px;overflow:hidden;box-shadow:0 24px 80px rgba(15,23,42,0.16);">
        <div style="padding:24px 32px;background:linear-gradient(135deg,#1f2f50 0%,#243a63 58%,#f7fafc 58%,#ffffff 100%);color:#ffffff;">
          <div style="font-size:11px;letter-spacing:0.28em;text-transform:uppercase;opacity:0.75;">Welcome Aboard</div>
          <h1 style="margin:18px 0 0;font-size:30px;line-height:1.15;font-weight:700;">Complete your employee registration</h1>
        </div>
        <div style="padding:32px;">
          <div style="font-size:15px;line-height:1.7;color:#334155;">
            <p style="margin:0 0 16px;">Hello {employee_name},</p>
            <p style="margin:0 0 16px;">Congratulations. You have been selected for the <strong>{role_line}</strong> role in <strong>{department_line}</strong>.</p>
            <p style="margin:0 0 16px;">Use the secure link below to complete your profile, set your password, and activate your ESS access.</p>
          </div>
          <div style="margin-top:28px;">
            <a href="{invite_link}" style="display:inline-block;padding:14px 22px;border-radius:14px;background:linear-gradient(135deg,#2563eb,#1d4ed8);color:#ffffff;text-decoration:none;font-weight:700;">
              Complete Registration
            </a>
          </div>
          <p style="margin:28px 0 0;font-size:13px;line-height:1.6;color:#64748b;">This invitation stays valid for {settings.invite_ttl_minutes} minutes.</p>
        </div>
      </div>
    </div>
    """.strip()


async def _create_candidate_invite(
    conn: object,
    *,
    application_id: UUID,
    payload: HirePayload,
    actor_employee_id: UUID,
) -> dict[str, object]:
    application = await conn.fetchrow(
        """
        SELECT ca.id,
               c.first_name,
               c.last_name,
               c.email AS candidate_email,
               c.phone,
               jp.legal_entity_id,
               jp.department_id,
               jp.job_role_id,
               coalesce(d.name_ka, d.name_en) AS department_name,
               coalesce(jr.title_ka, jr.title_en) AS job_role_title
          FROM candidate_applications ca
          JOIN candidates c ON c.id = ca.candidate_id
          JOIN job_postings jp ON jp.id = ca.job_posting_id
     LEFT JOIN departments d ON d.id = jp.department_id
     LEFT JOIN job_roles jr ON jr.id = jp.job_role_id
         WHERE ca.id = $1
        """,
        application_id,
    )
    if application is None:
        raise HTTPException(status_code=404, detail='Candidate application not found')

    invite_email = (str(payload.email or application['candidate_email'] or '')).strip().lower()
    if not invite_email:
        raise HTTPException(status_code=422, detail='Candidate email is required before moving to Hired')

    existing_identity = await conn.fetchval(
        'SELECT employee_id FROM auth_identities WHERE username = $1 LIMIT 1',
        invite_email,
    )
    if existing_identity is not None:
        raise HTTPException(status_code=409, detail='This candidate email already has login access')

    existing_employee = await conn.fetchval(
        """
        SELECT id
          FROM employees
         WHERE legal_entity_id = $1
           AND lower(email) = lower($2)
           AND deleted_at IS NULL
         LIMIT 1
        """,
        application['legal_entity_id'],
        invite_email,
    )
    if existing_employee is not None:
        raise HTTPException(status_code=409, detail='An employee with this email already exists')

    await ensure_employee_reference_tenant(
        conn,
        application['legal_entity_id'],
        department_id=application['department_id'],
        job_role_id=application['job_role_id'],
        manager_employee_id=payload.manager_employee_id,
        pay_policy_id=payload.pay_policy_id,
    )
    if payload.onboarding_course_id is not None:
        course_exists = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1
                  FROM onboarding_courses
                 WHERE id = $1
                   AND legal_entity_id = $2
            )
            """,
            payload.onboarding_course_id,
            application['legal_entity_id'],
        )
        if not course_exists:
            raise HTTPException(status_code=422, detail='onboarding_course_id does not belong to the target tenant')

    employee_number = await _generate_employee_number(conn, application['legal_entity_id'])
    employee_id = await conn.fetchval(
        """
        INSERT INTO employees (
            legal_entity_id, employee_number, personal_number, first_name, last_name,
            email, mobile_phone, department_id, job_role_id, manager_employee_id,
            line_manager_id, hire_date, employment_status, default_device_user_id
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $10, $11, 'draft', $2)
        RETURNING id
        """,
        application['legal_entity_id'],
        employee_number,
        payload.personal_number,
        application['first_name'],
        application['last_name'],
        invite_email,
        payload.mobile_phone or application['phone'],
        application['department_id'],
        application['job_role_id'],
        payload.manager_employee_id,
        payload.hire_date,
    )
    await conn.execute(
        """
        INSERT INTO employee_compensation (
            employee_id, policy_id, effective_from, salary_type, base_salary, hourly_rate_override, is_pension_participant
        ) VALUES ($1, $2, $3, 'monthly_fixed', $4, NULL, true)
        """,
        employee_id,
        payload.pay_policy_id,
        payload.hire_date,
        payload.base_salary,
    )
    role_id = await conn.fetchval("SELECT id FROM access_roles WHERE code = 'ESS_EMPLOYEE' LIMIT 1")
    if role_id is None:
        raise HTTPException(status_code=500, detail='ESS employee role is not configured')
    await conn.execute(
        """
        INSERT INTO employee_access_roles (employee_id, access_role_id, assigned_by_employee_id)
        VALUES ($1, $2, $3)
        ON CONFLICT DO NOTHING
        """,
        employee_id,
        role_id,
        actor_employee_id,
    )
    await conn.execute(
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
        invite_email,
        hash_password(secrets.token_urlsafe(24)),
    )
    invite_token = secrets.token_urlsafe(32)
    await conn.execute(
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
        application['legal_entity_id'],
        invite_email,
        invite_token,
        hash_password(secrets.token_urlsafe(24)),
        invite_email,
        settings.invite_ttl_minutes,
        actor_employee_id,
    )
    await conn.execute(
        """
        UPDATE candidate_applications
           SET application_status = 'hired', decided_at = now(), updated_at = now()
         WHERE id = $1
        """,
        application_id,
    )
    return {
        'employee_id': employee_id,
        'invite_token': invite_token,
        'invite_email': invite_email,
        'employee_name': f"{application['first_name']} {application['last_name']}".strip(),
        'department_name': application['department_name'],
        'job_role_title': application['job_role_title'],
        'legal_entity_id': application['legal_entity_id'],
    }


@ATS_ROUTER.post('/courses', status_code=201)
async def create_onboarding_course(request: Request, payload: OnboardingCourseCreateRequest) -> dict[str, str]:
    actor = await require_actor(request)
    ensure_permission(actor, 'recruitment.manage')
    if payload.legal_entity_id != actor.legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='Cross-entity course creation is not allowed')
    video_count = sum(1 for module in payload.modules if module.module_type == 'video')
    quiz_modules = [module for module in payload.modules if module.module_type == 'quiz']
    if video_count < 3 or not quiz_modules:
        raise HTTPException(status_code=400, detail='An onboarding course must include at least 3 videos and 1 quiz module')
    for module in quiz_modules:
        if not module.questions:
            raise HTTPException(status_code=400, detail='Quiz modules require at least one question')
        for question in module.questions:
            if len([option for option in question.options if option.is_correct]) != 1:
                raise HTTPException(status_code=400, detail='Each quiz question must have exactly one correct option')

    db = get_db_from_request(request)
    tx = await db.transaction()
    try:
        course_id = await tx.connection.fetchval(
            """
            INSERT INTO onboarding_courses (legal_entity_id, code, name_en, name_ka, description)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            payload.legal_entity_id,
            payload.code,
            payload.name_en,
            payload.name_ka,
            payload.description,
        )
        for index, module in enumerate(payload.modules, start=1):
            module_id = await tx.connection.fetchval(
                """
                INSERT INTO onboarding_course_modules (
                    course_id, sort_order, module_type, title, description, media_url, duration_seconds, passing_score
                ) VALUES ($1, $2, $3::onboarding_module_type, $4, $5, $6, $7, $8)
                RETURNING id
                """,
                course_id,
                index,
                module.module_type,
                module.title,
                module.description,
                module.media_url,
                module.duration_seconds,
                module.passing_score,
            )
            if module.module_type == 'quiz':
                for question_index, question in enumerate(module.questions, start=1):
                    question_id = await tx.connection.fetchval(
                        """
                        INSERT INTO onboarding_quiz_questions (module_id, sort_order, question_text)
                        VALUES ($1, $2, $3)
                        RETURNING id
                        """,
                        module_id,
                        question_index,
                        question.question_text,
                    )
                    await tx.connection.executemany(
                        """
                        INSERT INTO onboarding_quiz_options (question_id, option_key, option_text, is_correct)
                        VALUES ($1, $2, $3, $4)
                        """,
                        [
                            (question_id, option.option_key, option.option_text, option.is_correct)
                            for option in question.options
                        ],
                    )
        await tx.commit()
    except Exception:
        await tx.rollback()
        raise
    return {'course_id': str(course_id)}


@ATS_ROUTER.get('/kanban/{legal_entity_id}')
async def recruitment_kanban(request: Request, legal_entity_id: UUID) -> dict[str, list[dict[str, object]]]:
    actor = await require_actor(request)
    ensure_permission(actor, 'recruitment.read')
    if actor.legal_entity_id != legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='Cross-entity recruitment access is not allowed')
    db = get_db_from_request(request)
    rows = await db.fetch(
        """
        SELECT job_posting_id, posting_code, title_en, title_ka, posting_status, board_column,
               total_candidates, hired_candidates
          FROM v_ats_kanban_board
         WHERE legal_entity_id = $1
         ORDER BY posting_code
        """,
        legal_entity_id,
    )
    board = {'Draft': [], 'Published': [], 'Interview': [], 'Offer': [], 'Hired': []}
    for row in rows:
        board[row['board_column']].append(dict(row))
    return board


@ATS_ROUTER.post('/applications/{application_id}/move')
async def move_application_stage(request: Request, application_id: UUID, payload: MoveCandidateStageRequest) -> dict[str, str]:
    actor = await require_actor(request)
    ensure_permission(actor, 'recruitment.manage')
    db = get_db_from_request(request)
    stage = await db.fetchrow(
        """
        SELECT cps.id, cps.code::text AS code, cps.is_hired, cps.is_rejected, cps.is_terminal,
               jp.legal_entity_id
          FROM candidate_applications ca
          JOIN job_postings jp ON jp.id = ca.job_posting_id
          JOIN candidate_pipeline_stages cps ON cps.legal_entity_id = jp.legal_entity_id
         WHERE ca.id = $1
           AND upper(cps.code::text) = upper($2)
         LIMIT 1
        """,
        application_id,
        payload.stage_code,
    )
    if stage is None:
        raise HTTPException(status_code=404, detail='Target stage not found for this legal entity')
    if actor.legal_entity_id != stage['legal_entity_id'] and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='Cross-entity stage updates are not allowed')
    if stage['is_hired'] and payload.hire_payload is None:
        raise HTTPException(status_code=400, detail='hire_payload is required when moving a candidate to HIRED')

    tx = await db.transaction()
    invite_meta: dict[str, object] | None = None
    try:
        await apply_rls_context(tx.connection, actor)
        await tx.connection.execute(
            """
            UPDATE candidate_applications
               SET current_stage_id = $2,
                   application_status = CASE
                       WHEN $3 THEN 'hired'
                       WHEN $4 THEN 'rejected'
                       ELSE application_status
                   END,
                   decided_at = CASE WHEN $5 THEN now() ELSE decided_at END,
                   updated_at = now()
             WHERE id = $1
            """,
            application_id,
            stage['id'],
            stage['is_hired'],
            stage['is_rejected'],
            stage['is_terminal'],
        )
        await tx.connection.execute(
            """
            INSERT INTO candidate_pipeline (application_id, stage_id, moved_by_employee_id, comment)
            VALUES ($1, $2, $3, $4)
            """,
            application_id,
            stage['id'],
            actor.employee_id,
            payload.comment,
        )
        if stage['is_hired']:
            invite_meta = await _create_candidate_invite(
                tx.connection,
                application_id=application_id,
                payload=payload.hire_payload,
                actor_employee_id=actor.employee_id,
            )
        await tx.commit()
    except Exception:
        await tx.rollback()
        raise

    result: dict[str, str] = {'stage_code': stage['code']}
    if stage['is_hired'] and invite_meta is not None:
        prepared_device_profiles = await prepare_employee_device_profiles(db, UUID(str(invite_meta['employee_id'])))
        invite_link = _candidate_invite_link(str(invite_meta['invite_token']))
        email_status = 'skipped'
        if settings.smtp_host:
            await send_and_log_email(
                db,
                legal_entity_id=invite_meta['legal_entity_id'],
                event_type='ats_hire_invite',
                event_key=str(application_id),
                to_email=str(invite_meta['invite_email']),
                subject='Welcome to ITGS HR',
                body_text=(
                    f"Hello {invite_meta['employee_name']},\n\n"
                    f"You have been selected to join ITGS HR.\n"
                    f"Please complete your registration here: {invite_link}\n\n"
                    f"This invite remains valid for {settings.invite_ttl_minutes} minutes."
                ),
                body_html=_candidate_invite_email_html(
                    employee_name=str(invite_meta['employee_name']),
                    invite_link=invite_link,
                    department_name=invite_meta['department_name'],
                    job_role_title=invite_meta['job_role_title'],
                ),
                extra_payload={
                    'employee_id': str(invite_meta['employee_id']),
                    'application_id': str(application_id),
                    'username': str(invite_meta['invite_email']),
                },
            )
            email_status = 'sent'
        result.update(
            {
                'employee_id': str(invite_meta['employee_id']),
                'invite_link': invite_link,
                'invite_email_status': email_status,
                'prepared_device_profiles': str(prepared_device_profiles),
            }
        )
    return result


@ATS_ROUTER.post('/applications/{application_id}/schedule-interview')
async def schedule_interview(request: Request, application_id: UUID, payload: InterviewScheduleRequest) -> dict[str, object]:
    actor = await require_actor(request)
    ensure_permission(actor, 'recruitment.manage')
    db = get_db_from_request(request)
    row = await db.fetchrow(
        """
        SELECT ca.id,
               ca.current_stage_id,
               jp.legal_entity_id,
               coalesce(jp.title_ka, jp.title_en, 'Interview') AS job_title,
               c.first_name,
               c.last_name,
               c.email AS candidate_email,
               owner.email AS owner_email,
               owner.first_name || ' ' || owner.last_name AS owner_name
          FROM candidate_applications ca
          JOIN job_postings jp ON jp.id = ca.job_posting_id
          JOIN candidates c ON c.id = ca.candidate_id
          LEFT JOIN employees owner ON owner.id = ca.owner_employee_id
         WHERE ca.id = $1
        """,
        application_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail='Candidate application not found')
    if actor.legal_entity_id != row['legal_entity_id'] and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='Cross-entity interview scheduling is not allowed')

    scheduled_at = payload.scheduled_at if payload.scheduled_at.tzinfo else payload.scheduled_at.replace(tzinfo=GEORGIA_TZ)
    end_at = scheduled_at + timedelta(minutes=payload.duration_minutes)
    candidate_name = _candidate_full_name(row)
    calendar_url = _google_calendar_event_link(
        title=f"Interview: {candidate_name} - {row['job_title']}",
        start_at=scheduled_at,
        end_at=end_at,
        details=payload.notes or f"Interview scheduled for {candidate_name}",
    )

    await db.execute(
        """
        UPDATE candidate_applications
           SET interview_scheduled_at = $2,
               interview_duration_minutes = $3,
               interview_notes = $4,
               interview_calendar_url = $5,
               updated_at = now()
         WHERE id = $1
        """,
        application_id,
        scheduled_at,
        payload.duration_minutes,
        payload.notes,
        calendar_url,
    )
    stage_id = await db.fetchval(
        """
        SELECT cps.id
          FROM candidate_pipeline_stages cps
         WHERE cps.legal_entity_id = $1
           AND upper(cps.code::text) = 'INTERVIEW'
         LIMIT 1
        """,
        row['legal_entity_id'],
    )
    if stage_id is not None:
        await db.execute(
            """
            INSERT INTO candidate_pipeline (application_id, stage_id, moved_by_employee_id, comment)
            VALUES ($1, $2, $3, $4)
            """,
            application_id,
            stage_id,
            actor.employee_id,
            f'Interview scheduled for {scheduled_at.astimezone(GEORGIA_TZ).strftime("%Y-%m-%d %H:%M")}',
        )
    if settings.smtp_host:
        body_text = (
            f"Interview scheduled for {candidate_name}\n"
            f"Date: {scheduled_at.astimezone(GEORGIA_TZ).strftime('%Y-%m-%d %H:%M')}\n"
            f"Google Calendar link: {calendar_url}"
        )
        if row['candidate_email']:
            await send_and_log_email(
                db,
                legal_entity_id=row['legal_entity_id'],
                event_type='ats_interview_candidate',
                event_key=f'{application_id}:candidate',
                to_email=str(row['candidate_email']),
                subject=f'Interview invitation - {row["job_title"]}',
                body_text=body_text,
                body_html=f'<p>{body_text.replace(chr(10), "<br/>")}</p>',
                extra_payload={'application_id': str(application_id)},
            )
        if row['owner_email']:
            await send_and_log_email(
                db,
                legal_entity_id=row['legal_entity_id'],
                event_type='ats_interview_owner',
                event_key=f'{application_id}:owner',
                to_email=str(row['owner_email']),
                subject=f'Interview scheduled - {candidate_name}',
                body_text=body_text,
                body_html=f'<p>{body_text.replace(chr(10), "<br/>")}</p>',
                extra_payload={'application_id': str(application_id)},
            )

    return {
        'status': 'scheduled',
        'scheduled_at': scheduled_at.isoformat(),
        'duration_minutes': payload.duration_minutes,
        'calendar_url': calendar_url,
        'email_status': 'sent' if settings.smtp_host else 'skipped',
    }


@ATS_ROUTER.post('/assignments/{assignment_id}/modules/{module_id}/complete-video')
async def complete_video_module(request: Request, assignment_id: UUID, module_id: UUID, payload: VideoCompletionRequest) -> dict[str, object]:
    actor = await require_actor(request)
    db = get_db_from_request(request)
    row = await db.fetchrow(
        """
        SELECT oca.employee_id, ocm.module_type::text AS module_type
          FROM onboarding_course_assignments oca
          JOIN onboarding_assignment_modules oam ON oam.assignment_id = oca.id
          JOIN onboarding_course_modules ocm ON ocm.id = oam.module_id
         WHERE oca.id = $1
           AND ocm.id = $2
        """,
        assignment_id,
        module_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail='Assignment module not found')
    if actor.employee_id != row['employee_id'] and not actor.has('recruitment.manage'):
        raise HTTPException(status_code=403, detail='You can only complete your own onboarding modules')
    if row['module_type'] != 'video':
        raise HTTPException(status_code=400, detail='This endpoint is only for video modules')
    await db.execute(
        """
        UPDATE onboarding_assignment_modules
           SET watched_seconds = greatest(watched_seconds, $3),
               status = 'completed',
               completed_at = now(),
               updated_at = now()
         WHERE assignment_id = $1
           AND module_id = $2
        """,
        assignment_id,
        module_id,
        payload.watched_seconds,
    )
    await _refresh_assignment_status(db, assignment_id)
    return {'assignment_id': str(assignment_id), 'module_id': str(module_id), 'status': 'completed'}


@ATS_ROUTER.post('/assignments/{assignment_id}/modules/{module_id}/submit-quiz')
async def submit_quiz(request: Request, assignment_id: UUID, module_id: UUID, payload: QuizSubmitRequest) -> dict[str, object]:
    actor = await require_actor(request)
    db = get_db_from_request(request)
    assignment = await db.fetchrow(
        'SELECT employee_id FROM onboarding_course_assignments WHERE id = $1',
        assignment_id,
    )
    if assignment is None:
        raise HTTPException(status_code=404, detail='Assignment not found')
    if actor.employee_id != assignment['employee_id'] and not actor.has('recruitment.manage'):
        raise HTTPException(status_code=403, detail='You can only submit your own onboarding quiz')

    questions = await db.fetch(
        """
        SELECT oqq.id AS question_id, oqo.id AS option_id, oqo.is_correct
          FROM onboarding_quiz_questions oqq
          JOIN onboarding_quiz_options oqo ON oqo.question_id = oqq.id
         WHERE oqq.module_id = $1
        """,
        module_id,
    )
    if not questions:
        raise HTTPException(status_code=404, detail='Quiz module has no questions')
    correct_option_ids = {row['option_id'] for row in questions if row['is_correct']}
    question_ids = {row['question_id'] for row in questions}
    total_questions = len(question_ids)
    selected_option_ids = set(payload.selected_option_ids)
    correct_answers = len(correct_option_ids & selected_option_ids)
    score = int((Decimal(correct_answers) / Decimal(total_questions) * Decimal('100')).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    passing_score = await db.fetchval('SELECT coalesce(passing_score, 100) FROM onboarding_course_modules WHERE id = $1', module_id)
    passed = score >= passing_score
    await db.execute(
        """
        UPDATE onboarding_assignment_modules
           SET score_percent = $3,
               status = CASE WHEN $4 THEN 'completed'::onboarding_assignment_status ELSE 'in_progress'::onboarding_assignment_status END,
               completed_at = CASE WHEN $4 THEN now() ELSE completed_at END,
               updated_at = now()
         WHERE assignment_id = $1
           AND module_id = $2
        """,
        assignment_id,
        module_id,
        score,
        passed,
    )
    await _refresh_assignment_status(db, assignment_id)
    return {'assignment_id': str(assignment_id), 'module_id': str(module_id), 'score': score, 'passed': passed}


async def _refresh_assignment_status(db, assignment_id: UUID) -> None:
    counts = await db.fetchrow(
        """
        SELECT count(*) AS total_count,
               count(*) FILTER (WHERE status = 'completed') AS completed_count
          FROM onboarding_assignment_modules
         WHERE assignment_id = $1
        """,
        assignment_id,
    )
    total_count = counts['total_count']
    completed_count = counts['completed_count']
    if total_count and total_count == completed_count:
        await db.execute(
            """
            UPDATE onboarding_course_assignments
               SET status = 'completed', completed_at = now(), updated_at = now()
             WHERE id = $1
            """,
            assignment_id,
        )
    else:
        await db.execute(
            """
            UPDATE onboarding_course_assignments
               SET status = 'in_progress', updated_at = now()
             WHERE id = $1
            """,
            assignment_id,
        )


@ATS_ROUTER.post('/seed-default-stages/{legal_entity_id}')
async def seed_default_stages(request: Request, legal_entity_id: UUID) -> dict[str, str]:
    actor = await require_actor(request)
    ensure_permission(actor, 'recruitment.manage')
    if actor.legal_entity_id != legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='Cross-entity stage seeding is not allowed')
    db = get_db_from_request(request)
    await db.execute('SELECT hrms.seed_default_candidate_pipeline_stages($1)', legal_entity_id)
    return {'status': 'seeded'}
