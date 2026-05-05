from __future__ import annotations

from .db import Database, set_database_rls_context


async def ensure_runtime_schema(db: Database) -> None:
    statements = [
        """
        CREATE TABLE IF NOT EXISTS entity_system_config (
            legal_entity_id uuid PRIMARY KEY REFERENCES legal_entities(id) ON DELETE CASCADE,
            logo_url text,
            logo_text text,
            primary_color text NOT NULL DEFAULT '#1A2238',
            standalone_chat_url text,
            linkedin_url text,
            facebook_url text,
            instagram_url text,
            allowed_web_punch_ips text[] NOT NULL DEFAULT ARRAY[]::text[],
            geofence_latitude numeric(10,7),
            geofence_longitude numeric(10,7),
            geofence_radius_meters integer,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """,
        """
        ALTER TABLE entity_system_config
            ADD COLUMN IF NOT EXISTS linkedin_url text
        """,
        """
        ALTER TABLE entity_system_config
            ADD COLUMN IF NOT EXISTS facebook_url text
        """,
        """
        ALTER TABLE entity_system_config
            ADD COLUMN IF NOT EXISTS instagram_url text
        """,
        """
        ALTER TABLE entity_system_config
            ADD COLUMN IF NOT EXISTS gps_only_check_in boolean NOT NULL DEFAULT false
        """,
        """
        ALTER TABLE entity_system_config
            ADD COLUMN IF NOT EXISTS company_dashboard_enabled boolean NOT NULL DEFAULT true
        """,
        """
        ALTER TABLE entity_system_config
            ADD COLUMN IF NOT EXISTS payroll_dashboard_enabled boolean NOT NULL DEFAULT true
        """,
        """
        ALTER TABLE entity_system_config
            ADD COLUMN IF NOT EXISTS dashboard_widget_visibility jsonb NOT NULL DEFAULT '{
                "summary_cards": true,
                "analytics": true,
                "live_feed": true,
                "action_center": true,
                "upcoming_schedule": true,
                "celebrations": true
            }'::jsonb
        """,
        """
        CREATE TABLE IF NOT EXISTS tenant_subscriptions (
            legal_entity_id uuid PRIMARY KEY REFERENCES legal_entities(id) ON DELETE CASCADE,
            attendance_enabled boolean NOT NULL DEFAULT true,
            payroll_enabled boolean NOT NULL DEFAULT true,
            ats_enabled boolean NOT NULL DEFAULT true,
            chat_enabled boolean NOT NULL DEFAULT true,
            device_management_enabled boolean NOT NULL DEFAULT true,
            mobile_sync_enabled boolean NOT NULL DEFAULT true,
            assets_enabled boolean NOT NULL DEFAULT true,
            org_chart_enabled boolean NOT NULL DEFAULT true,
            performance_enabled boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """,
        """
        ALTER TABLE tenant_subscriptions
            ADD COLUMN IF NOT EXISTS device_management_enabled boolean NOT NULL DEFAULT true
        """,
        """
        ALTER TABLE tenant_subscriptions
            ADD COLUMN IF NOT EXISTS mobile_sync_enabled boolean NOT NULL DEFAULT true
        """,
        """
        CREATE TABLE IF NOT EXISTS tenant_domains (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            legal_entity_id uuid NOT NULL REFERENCES legal_entities(id) ON DELETE CASCADE,
            host text NOT NULL UNIQUE,
            subdomain text,
            is_primary boolean NOT NULL DEFAULT false,
            is_active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_tenant_domains_entity
            ON tenant_domains (legal_entity_id, is_active, is_primary DESC)
        """,
        """
        ALTER TABLE employee_compensation
            ADD COLUMN IF NOT EXISTS salary_type text NOT NULL DEFAULT 'monthly_fixed'
        """,
        """
        ALTER TABLE employees
            ADD COLUMN IF NOT EXISTS line_manager_id uuid REFERENCES employees(id) ON DELETE SET NULL
        """,
        """
        ALTER TABLE employees
            ADD COLUMN IF NOT EXISTS deleted_at timestamptz
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_employees_legal_entity_deleted_at
            ON employees (legal_entity_id, deleted_at)
        """,
        """
        ALTER TABLE shift_patterns
            ADD COLUMN IF NOT EXISTS grace_period_minutes integer NOT NULL DEFAULT 15
        """,
        """
        ALTER TABLE device_registry
            ADD COLUMN IF NOT EXISTS device_type text NOT NULL DEFAULT 'biometric_terminal'
        """,
        """
        ALTER TABLE raw_attendance_logs
            ADD COLUMN IF NOT EXISTS processed_at timestamptz
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_raw_attendance_logs_unprocessed
            ON raw_attendance_logs (employee_id, event_ts)
            WHERE processed_at IS NULL AND employee_id IS NOT NULL
        """,
        """
        ALTER TABLE job_postings
            ADD COLUMN IF NOT EXISTS public_slug text
        """,
        """
        ALTER TABLE job_postings
            ADD COLUMN IF NOT EXISTS application_form_schema jsonb NOT NULL DEFAULT '[]'::jsonb
        """,
        """
        ALTER TABLE job_postings
            ADD COLUMN IF NOT EXISTS external_form_url text
        """,
        """
        ALTER TABLE job_postings
            ADD COLUMN IF NOT EXISTS public_description text
        """,
        """
        ALTER TABLE job_postings
            ADD COLUMN IF NOT EXISTS is_public boolean NOT NULL DEFAULT true
        """,
        """
        ALTER TABLE candidate_applications
            ADD COLUMN IF NOT EXISTS application_payload jsonb NOT NULL DEFAULT '{}'::jsonb
        """,
        """
        ALTER TABLE candidate_applications
            ADD COLUMN IF NOT EXISTS compatibility_score numeric(5,2)
        """,
        """
        ALTER TABLE candidate_applications
            ADD COLUMN IF NOT EXISTS compatibility_summary text
        """,
        """
        ALTER TABLE candidate_applications
            ADD COLUMN IF NOT EXISTS cv_file_name text
        """,
        """
        ALTER TABLE candidate_applications
            ADD COLUMN IF NOT EXISTS cv_file_url text
        """,
        """
        ALTER TABLE candidate_applications
            ADD COLUMN IF NOT EXISTS cv_extracted_text text
        """,
        """
        ALTER TABLE candidate_applications
            ADD COLUMN IF NOT EXISTS interview_scheduled_at timestamptz
        """,
        """
        ALTER TABLE candidate_applications
            ADD COLUMN IF NOT EXISTS interview_duration_minutes integer
        """,
        """
        ALTER TABLE candidate_applications
            ADD COLUMN IF NOT EXISTS interview_notes text
        """,
        """
        ALTER TABLE candidate_applications
            ADD COLUMN IF NOT EXISTS interview_calendar_url text
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_job_postings_public_slug
            ON job_postings (public_slug)
            WHERE public_slug IS NOT NULL
        """,
        """
        CREATE TABLE IF NOT EXISTS worksites (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            legal_entity_id uuid NOT NULL REFERENCES legal_entities(id) ON DELETE CASCADE,
            name text NOT NULL,
            latitude numeric(10,7) NOT NULL,
            longitude numeric(10,7) NOT NULL,
            radius_meters integer NOT NULL DEFAULT 150,
            address_text text,
            is_active boolean NOT NULL DEFAULT true,
            created_by_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_worksites_entity_active
            ON worksites (legal_entity_id, is_active, name)
        """,
        """
        CREATE TABLE IF NOT EXISTS web_punch_events (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            employee_id uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
            legal_entity_id uuid NOT NULL REFERENCES legal_entities(id) ON DELETE CASCADE,
            direction attendance_direction NOT NULL DEFAULT 'unknown',
            punch_ts timestamptz NOT NULL DEFAULT now(),
            source_ip text,
            latitude numeric(10,7),
            longitude numeric(10,7),
            is_valid boolean NOT NULL DEFAULT false,
            validation_reason text,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """,
        """
        ALTER TABLE web_punch_events
            ADD COLUMN IF NOT EXISTS worksite_id uuid REFERENCES worksites(id) ON DELETE SET NULL
        """,
        """
        ALTER TABLE web_punch_events
            ADD COLUMN IF NOT EXISTS location_name text
        """,
        """
        ALTER TABLE web_punch_events
            ADD COLUMN IF NOT EXISTS location_source text
        """,
        """
        ALTER TABLE web_punch_events
            ADD COLUMN IF NOT EXISTS gps_accuracy_meters numeric(8,2)
        """,
        """
        ALTER TABLE web_punch_events
            ADD COLUMN IF NOT EXISTS is_location_suspicious boolean NOT NULL DEFAULT false
        """,
        """
        ALTER TABLE web_punch_events
            ADD COLUMN IF NOT EXISTS location_risk_reason text
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_web_punch_events_employee_ts
            ON web_punch_events (employee_id, punch_ts DESC)
        """,
        """
        ALTER TABLE leave_requests
            ADD COLUMN IF NOT EXISTS attachment_url text
        """,
        """
        ALTER TABLE leave_requests
            ADD COLUMN IF NOT EXISTS approval_stage text NOT NULL DEFAULT 'manager_pending'
        """,
        """
        CREATE TABLE IF NOT EXISTS leave_request_files (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            leave_request_id uuid NOT NULL REFERENCES leave_requests(id) ON DELETE CASCADE,
            file_name text NOT NULL,
            file_url text NOT NULL,
            content_type text,
            file_size integer,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS auth_invites (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            employee_id uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
            legal_entity_id uuid NOT NULL REFERENCES legal_entities(id) ON DELETE CASCADE,
            username citext NOT NULL,
            invite_token text NOT NULL UNIQUE,
            temp_password_hash text NOT NULL,
            recipient_email text,
            sent_via text NOT NULL DEFAULT 'email',
            expires_at timestamptz NOT NULL,
            accepted_at timestamptz,
            created_by_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_auth_invites_employee
            ON auth_invites (employee_id, expires_at DESC)
        """,
        """
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            employee_id uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
            identity_id uuid REFERENCES auth_identities(id) ON DELETE CASCADE,
            reset_token text NOT NULL UNIQUE,
            expires_at timestamptz NOT NULL,
            used_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS attendance_manual_adjustments (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            employee_id uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
            legal_entity_id uuid NOT NULL REFERENCES legal_entities(id) ON DELETE CASCADE,
            session_id uuid REFERENCES attendance_work_sessions(id) ON DELETE SET NULL,
            work_date date NOT NULL,
            corrected_check_in timestamptz NOT NULL,
            corrected_check_out timestamptz,
            reason_comment text NOT NULL,
            created_by_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_attendance_manual_adjustments_employee_work_date
            ON attendance_manual_adjustments (employee_id, work_date DESC)
        """,
        """
        CREATE TABLE IF NOT EXISTS employee_file_uploads (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            employee_id uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
            legal_entity_id uuid NOT NULL REFERENCES legal_entities(id) ON DELETE CASCADE,
            file_category text NOT NULL,
            file_name text NOT NULL,
            file_url text NOT NULL,
            content_type text,
            file_size integer,
            created_by_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS payroll_payment_records (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            timesheet_id uuid NOT NULL REFERENCES monthly_timesheets(id) ON DELETE CASCADE,
            employee_id uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
            paid_at timestamptz NOT NULL,
            payment_method text NOT NULL,
            payment_reference text,
            note text,
            payslip_file_name text NOT NULL,
            payslip_pdf bytea NOT NULL,
            locked_by_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (timesheet_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS asset_handover_forms (
            assignment_id uuid PRIMARY KEY REFERENCES asset_assignments(id) ON DELETE CASCADE,
            employee_signature_name text NOT NULL,
            handover_summary text NOT NULL,
            acknowledged_at timestamptz NOT NULL DEFAULT now(),
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS employee_google_calendar_connections (
            employee_id uuid PRIMARY KEY REFERENCES employees(id) ON DELETE CASCADE,
            legal_entity_id uuid NOT NULL REFERENCES legal_entities(id) ON DELETE CASCADE,
            google_subject text,
            google_email text,
            calendar_id text NOT NULL DEFAULT 'primary',
            access_token text NOT NULL,
            refresh_token text,
            token_type text,
            scope text,
            expires_at timestamptz,
            connected_at timestamptz NOT NULL DEFAULT now(),
            last_synced_at timestamptz,
            sync_error text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_employee_google_calendar_connections_entity
            ON employee_google_calendar_connections (legal_entity_id, google_email)
        """,
        """
        CREATE TABLE IF NOT EXISTS slack_workspace_connections (
            legal_entity_id uuid PRIMARY KEY REFERENCES legal_entities(id) ON DELETE CASCADE,
            team_id text NOT NULL,
            team_name text,
            access_token text NOT NULL,
            scope text,
            bot_user_id text,
            authed_user_id text,
            connected_by_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
            connected_at timestamptz NOT NULL DEFAULT now(),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_slack_workspace_connections_team
            ON slack_workspace_connections (team_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS employee_message_dispatches (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            legal_entity_id uuid NOT NULL REFERENCES legal_entities(id) ON DELETE CASCADE,
            sender_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
            target_employee_id uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
            channel text NOT NULL,
            provider text NOT NULL,
            subject text,
            message_body text NOT NULL,
            status text NOT NULL DEFAULT 'queued',
            error text,
            external_message_id text,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_employee_message_dispatches_target_created
            ON employee_message_dispatches (target_employee_id, created_at DESC)
        """,
        """
        CREATE TABLE IF NOT EXISTS audit_logs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            legal_entity_id uuid NOT NULL REFERENCES legal_entities(id) ON DELETE CASCADE,
            actor_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
            target_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
            action_code text NOT NULL,
            details jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_audit_logs_entity_created
            ON audit_logs (legal_entity_id, created_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_audit_logs_target_created
            ON audit_logs (target_employee_id, created_at DESC)
        """,
        """
        CREATE TABLE IF NOT EXISTS device_middleware_api_keys (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            legal_entity_id uuid NOT NULL REFERENCES legal_entities(id) ON DELETE CASCADE,
            key_name text NOT NULL,
            api_key_hash text NOT NULL UNIQUE,
            created_by_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
            last_used_at timestamptz,
            revoked_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_device_middleware_api_keys_entity
            ON device_middleware_api_keys (legal_entity_id, revoked_at, created_at DESC)
        """,
        """
        CREATE TABLE IF NOT EXISTS device_card_enrollment_sessions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            legal_entity_id uuid NOT NULL REFERENCES legal_entities(id) ON DELETE CASCADE,
            employee_id uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
            device_id uuid NOT NULL REFERENCES device_registry(id) ON DELETE CASCADE,
            enrollment_token text NOT NULL UNIQUE,
            card_number text,
            completed_at timestamptz,
            expires_at timestamptz NOT NULL,
            created_by_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_device_card_enrollment_sessions_employee
            ON device_card_enrollment_sessions (employee_id, expires_at DESC)
        """,
        """
        CREATE TABLE IF NOT EXISTS auth_refresh_sessions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            employee_id uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
            legal_entity_id uuid NOT NULL REFERENCES legal_entities(id) ON DELETE CASCADE,
            username citext NOT NULL,
            token_jti text NOT NULL UNIQUE,
            token_hash text NOT NULL,
            platform text,
            device_label text,
            app_version text,
            user_agent text,
            push_token text,
            created_ip text,
            last_seen_at timestamptz,
            expires_at timestamptz NOT NULL,
            rotated_at timestamptz,
            revoked_at timestamptz,
            replaced_by_session_id uuid REFERENCES auth_refresh_sessions(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_auth_refresh_sessions_employee
            ON auth_refresh_sessions (employee_id, revoked_at, expires_at DESC)
        """,
        """
        CREATE TABLE IF NOT EXISTS tenant_role_permission_overrides (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            legal_entity_id uuid NOT NULL REFERENCES legal_entities(id) ON DELETE CASCADE,
            access_role_id uuid NOT NULL REFERENCES access_roles(id) ON DELETE CASCADE,
            permission_code citext NOT NULL REFERENCES permissions(code) ON DELETE CASCADE,
            is_enabled boolean NOT NULL,
            created_by_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (legal_entity_id, access_role_id, permission_code)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_tenant_role_permission_overrides_entity_role
            ON tenant_role_permission_overrides (legal_entity_id, access_role_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS entity_leave_policy_settings (
            legal_entity_id uuid PRIMARY KEY REFERENCES legal_entities(id) ON DELETE CASCADE,
            paid_leave_allowance_days integer NOT NULL DEFAULT 24,
            unpaid_leave_allowance_days integer NOT NULL DEFAULT 15,
            eligibility_months integer NOT NULL DEFAULT 11,
            enable_birthday_off boolean NOT NULL DEFAULT false,
            enable_day_off boolean NOT NULL DEFAULT false,
            global_leave_approver_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS department_schedule_managers (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            legal_entity_id uuid NOT NULL REFERENCES legal_entities(id) ON DELETE CASCADE,
            department_id uuid NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
            employee_id uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
            created_by_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (department_id, employee_id)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_department_schedule_managers_department
            ON department_schedule_managers (department_id, employee_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS department_employee_editors (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            legal_entity_id uuid NOT NULL REFERENCES legal_entities(id) ON DELETE CASCADE,
            department_id uuid NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
            employee_id uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
            created_by_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (department_id, employee_id)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_department_employee_editors_department
            ON department_employee_editors (department_id, employee_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS department_leave_approvers (
            department_id uuid PRIMARY KEY REFERENCES departments(id) ON DELETE CASCADE,
            legal_entity_id uuid NOT NULL REFERENCES legal_entities(id) ON DELETE CASCADE,
            approver_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
            created_by_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_department_leave_approvers_entity
            ON department_leave_approvers (legal_entity_id, department_id)
        """,
    ]
    for statement in statements:
        await db.execute(statement)

    legal_entity_ids = await db.fetch('SELECT id FROM legal_entities ORDER BY created_at')
    try:
        for row in legal_entity_ids:
            legal_entity_id = row['id']
            set_database_rls_context(legal_entity_id=legal_entity_id)
            await db.execute(
                """
                INSERT INTO tenant_subscriptions (legal_entity_id)
                VALUES ($1)
                ON CONFLICT (legal_entity_id) DO NOTHING
                """,
                legal_entity_id,
            )
            await db.execute(
                """
                UPDATE employees
                   SET line_manager_id = manager_employee_id
                 WHERE legal_entity_id = $1
                   AND line_manager_id IS NULL
                   AND manager_employee_id IS NOT NULL
                """,
                legal_entity_id,
            )
            await db.execute(
                """
                INSERT INTO entity_leave_policy_settings (legal_entity_id)
                VALUES ($1)
                ON CONFLICT (legal_entity_id) DO NOTHING
                """,
                legal_entity_id,
            )
    finally:
        set_database_rls_context(legal_entity_id=None)
