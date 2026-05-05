BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE SCHEMA IF NOT EXISTS hrms;
SET search_path TO hrms, public;

CREATE TYPE employee_status AS ENUM ('draft', 'active', 'suspended', 'terminated');
CREATE TYPE device_brand AS ENUM ('zk', 'dahua', 'suprema');
CREATE TYPE device_transport AS ENUM ('adms', 'adms_push', 'biostar', 'http_cgi', 'rest_api', 'raw_socket', 'sdk_bridge');
CREATE TYPE device_command_type AS ENUM ('upsert_user', 'delete_user', 'upsert_template', 'delete_template');
CREATE TYPE device_command_status AS ENUM ('queued', 'processing', 'completed', 'failed');
CREATE TYPE attendance_direction AS ENUM ('in', 'out', 'unknown');
CREATE TYPE template_type AS ENUM ('fingerprint', 'face', 'card', 'palm');
CREATE TYPE shift_pattern_type AS ENUM ('fixed_weekly', 'cycle');
CREATE TYPE asset_condition AS ENUM ('new', 'excellent', 'good', 'fair', 'damaged', 'retired', 'lost');
CREATE TYPE asset_status AS ENUM ('in_stock', 'assigned', 'repair', 'retired', 'disposed', 'lost');
CREATE TYPE checklist_item_status AS ENUM ('pending', 'in_progress', 'completed', 'skipped', 'blocked');
CREATE TYPE review_status AS ENUM ('open', 'needs_review', 'approved', 'corrected', 'rejected', 'flagged');
CREATE TYPE timesheet_status AS ENUM ('draft', 'manager_review', 'approved', 'exported', 'locked');
CREATE TYPE payroll_cycle AS ENUM ('monthly', 'biweekly', 'weekly');
CREATE TYPE pipeline_application_status AS ENUM ('active', 'hired', 'rejected', 'withdrawn');
CREATE TYPE recruitment_posting_status AS ENUM ('draft', 'published', 'closed', 'on_hold');

CREATE OR REPLACE FUNCTION hrms.touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION hrms.uuid_array_setting(setting_name text)
RETURNS uuid[]
LANGUAGE sql
STABLE
AS $$
    SELECT CASE
        WHEN coalesce(current_setting(setting_name, true), '') = '' THEN ARRAY[]::uuid[]
        ELSE string_to_array(current_setting(setting_name, true), ',')::uuid[]
    END;
$$;

CREATE TABLE legal_entities (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_name text NOT NULL,
    trade_name text NOT NULL,
    tax_id text NOT NULL UNIQUE,
    timezone text NOT NULL DEFAULT 'Asia/Tbilisi',
    currency_code char(3) NOT NULL DEFAULT 'GEL',
    address_line text,
    city text,
    country_code char(2) NOT NULL DEFAULT 'GE',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE departments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id uuid NOT NULL REFERENCES legal_entities(id) ON DELETE CASCADE,
    parent_department_id uuid REFERENCES departments(id) ON DELETE SET NULL,
    code citext NOT NULL,
    name_en text NOT NULL,
    name_ka text NOT NULL,
    cost_center_code text,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (legal_entity_id, code)
);

CREATE TABLE job_roles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id uuid NOT NULL REFERENCES legal_entities(id) ON DELETE CASCADE,
    code citext NOT NULL,
    title_en text NOT NULL,
    title_ka text NOT NULL,
    description text,
    is_managerial boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (legal_entity_id, code)
);

CREATE TABLE access_roles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code citext NOT NULL UNIQUE,
    name_en text NOT NULL,
    name_ka text NOT NULL,
    description text NOT NULL,
    is_system boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE permissions (
    code citext PRIMARY KEY,
    description text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE access_role_permissions (
    access_role_id uuid NOT NULL REFERENCES access_roles(id) ON DELETE CASCADE,
    permission_code citext NOT NULL REFERENCES permissions(code) ON DELETE CASCADE,
    PRIMARY KEY (access_role_id, permission_code)
);

CREATE TABLE pay_policies (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id uuid NOT NULL REFERENCES legal_entities(id) ON DELETE CASCADE,
    code citext NOT NULL,
    name text NOT NULL,
    payroll_cycle payroll_cycle NOT NULL DEFAULT 'monthly',
    standard_weekly_hours numeric(5,2) NOT NULL DEFAULT 40.00 CHECK (standard_weekly_hours > 0),
    overtime_multiplier numeric(5,2) NOT NULL CHECK (overtime_multiplier >= 1.00),
    night_bonus_multiplier numeric(5,2) NOT NULL DEFAULT 0.00 CHECK (night_bonus_multiplier >= 0.00),
    holiday_multiplier numeric(5,2) NOT NULL DEFAULT 2.00 CHECK (holiday_multiplier >= 1.00),
    employee_pension_rate numeric(6,5) NOT NULL DEFAULT 0.02000 CHECK (employee_pension_rate >= 0 AND employee_pension_rate <= 1),
    income_tax_rate numeric(6,5) NOT NULL DEFAULT 0.20000 CHECK (income_tax_rate >= 0 AND income_tax_rate <= 1),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (legal_entity_id, code)
);

CREATE TABLE employees (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id uuid NOT NULL REFERENCES legal_entities(id) ON DELETE CASCADE,
    employee_number text NOT NULL,
    personal_number text,
    first_name text NOT NULL,
    last_name text NOT NULL,
    first_name_ka text,
    last_name_ka text,
    birth_date date,
    email citext,
    mobile_phone text,
    department_id uuid REFERENCES departments(id) ON DELETE SET NULL,
    job_role_id uuid REFERENCES job_roles(id) ON DELETE SET NULL,
    manager_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
    hire_date date NOT NULL,
    termination_date date,
    employment_status employee_status NOT NULL DEFAULT 'active',
    timezone text NOT NULL DEFAULT 'Asia/Tbilisi',
    default_device_user_id text,
    home_address text,
    emergency_contact_name text,
    emergency_contact_phone text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (legal_entity_id, employee_number),
    UNIQUE (legal_entity_id, personal_number),
    CHECK (termination_date IS NULL OR termination_date >= hire_date)
);

ALTER TABLE departments
    ADD COLUMN manager_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL;

CREATE TABLE employee_access_roles (
    employee_id uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    access_role_id uuid NOT NULL REFERENCES access_roles(id) ON DELETE CASCADE,
    assigned_at timestamptz NOT NULL DEFAULT now(),
    assigned_by_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
    PRIMARY KEY (employee_id, access_role_id)
);

CREATE TABLE employee_compensation (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    policy_id uuid NOT NULL REFERENCES pay_policies(id) ON DELETE RESTRICT,
    effective_from date NOT NULL,
    effective_to date,
    base_salary numeric(14,2) NOT NULL CHECK (base_salary >= 0),
    currency_code char(3) NOT NULL DEFAULT 'GEL',
    hourly_rate_override numeric(14,4) CHECK (hourly_rate_override IS NULL OR hourly_rate_override >= 0),
    is_pension_participant boolean NOT NULL DEFAULT true,
    notes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (effective_to IS NULL OR effective_to >= effective_from)
);
CREATE INDEX idx_employee_compensation_employee_dates ON employee_compensation (employee_id, effective_from DESC, effective_to);

CREATE TABLE device_registry (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id uuid NOT NULL REFERENCES legal_entities(id) ON DELETE CASCADE,
    brand device_brand NOT NULL,
    transport device_transport NOT NULL,
    device_name text NOT NULL,
    model text NOT NULL,
    serial_number text NOT NULL UNIQUE,
    host text NOT NULL,
    port integer NOT NULL CHECK (port BETWEEN 1 AND 65535),
    api_base_url text,
    username text,
    password_ciphertext text,
    device_timezone text NOT NULL DEFAULT 'Asia/Tbilisi',
    is_active boolean NOT NULL DEFAULT true,
    poll_interval_seconds integer NOT NULL DEFAULT 60 CHECK (poll_interval_seconds >= 10),
    last_seen_at timestamptz,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (legal_entity_id, device_name)
);

CREATE TABLE employee_device_identities (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id uuid NOT NULL REFERENCES device_registry(id) ON DELETE CASCADE,
    employee_id uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    device_user_id text NOT NULL,
    card_number text,
    pin_code text,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (device_id, device_user_id),
    UNIQUE (device_id, employee_id)
);

CREATE TABLE device_command_queue (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id uuid NOT NULL REFERENCES device_registry(id) ON DELETE CASCADE,
    employee_id uuid REFERENCES employees(id) ON DELETE CASCADE,
    command_type device_command_type NOT NULL,
    payload jsonb NOT NULL,
    status device_command_status NOT NULL DEFAULT 'queued',
    attempt_count integer NOT NULL DEFAULT 0,
    last_attempt_at timestamptz,
    last_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_device_command_queue_ready ON device_command_queue (device_id, status, created_at) WHERE status IN ('queued', 'failed');

CREATE TABLE device_push_batches (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id uuid NOT NULL REFERENCES device_registry(id) ON DELETE CASCADE,
    batch_kind text NOT NULL,
    request_query text,
    raw_body text NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(),
    processed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_device_push_batches_unprocessed ON device_push_batches (device_id, received_at) WHERE processed_at IS NULL;

CREATE TABLE biometric_templates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    device_id uuid REFERENCES device_registry(id) ON DELETE CASCADE,
    template_kind template_type NOT NULL,
    template_index integer NOT NULL DEFAULT 0,
    template_data bytea NOT NULL,
    sha256_checksum text NOT NULL,
    source_system text NOT NULL,
    enrolled_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (employee_id, device_id, template_kind, template_index)
);
CREATE INDEX idx_biometric_templates_checksum ON biometric_templates (sha256_checksum);

CREATE TABLE raw_attendance_logs (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    device_id uuid NOT NULL REFERENCES device_registry(id) ON DELETE CASCADE,
    employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
    device_user_id text NOT NULL,
    event_ts timestamptz NOT NULL,
    direction attendance_direction NOT NULL DEFAULT 'unknown',
    verify_mode text,
    source_batch_id uuid REFERENCES device_push_batches(id) ON DELETE SET NULL,
    external_log_id text,
    raw_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (device_id, device_user_id, event_ts)
);
CREATE INDEX idx_raw_attendance_logs_employee_ts ON raw_attendance_logs (employee_id, event_ts);
CREATE INDEX idx_raw_attendance_logs_device_ts ON raw_attendance_logs (device_id, event_ts DESC);

CREATE TABLE shift_patterns (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id uuid NOT NULL REFERENCES legal_entities(id) ON DELETE CASCADE,
    code citext NOT NULL,
    name text NOT NULL,
    pattern_type shift_pattern_type NOT NULL,
    cycle_length_days integer NOT NULL DEFAULT 7 CHECK (cycle_length_days >= 1 AND cycle_length_days <= 366),
    timezone text NOT NULL DEFAULT 'Asia/Tbilisi',
    standard_weekly_hours numeric(5,2) NOT NULL DEFAULT 40.00 CHECK (standard_weekly_hours > 0),
    early_check_in_grace_minutes integer NOT NULL DEFAULT 60 CHECK (early_check_in_grace_minutes >= 0),
    late_check_out_grace_minutes integer NOT NULL DEFAULT 240 CHECK (late_check_out_grace_minutes >= 0),
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (legal_entity_id, code)
);

CREATE TABLE shift_pattern_segments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    shift_pattern_id uuid NOT NULL REFERENCES shift_patterns(id) ON DELETE CASCADE,
    day_index integer NOT NULL CHECK (day_index >= 1 AND day_index <= 366),
    start_time time NOT NULL,
    planned_minutes integer NOT NULL CHECK (planned_minutes > 0 AND planned_minutes <= 1440),
    break_minutes integer NOT NULL DEFAULT 0 CHECK (break_minutes >= 0 AND break_minutes <= planned_minutes),
    crosses_midnight boolean NOT NULL DEFAULT false,
    label text,
    UNIQUE (shift_pattern_id, day_index)
);
CREATE INDEX idx_shift_pattern_segments_pattern_day ON shift_pattern_segments (shift_pattern_id, day_index);


CREATE OR REPLACE FUNCTION hrms.seed_standard_shift_patterns(p_legal_entity_id uuid)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_9_6 uuid;
    v_24_48 uuid;
    v_rotating uuid;
BEGIN
    INSERT INTO shift_patterns (
        legal_entity_id, code, name, pattern_type, cycle_length_days, timezone,
        standard_weekly_hours, early_check_in_grace_minutes, late_check_out_grace_minutes
    )
    VALUES (
        p_legal_entity_id, 'FIXED_9_6', '09:00-18:00 Office', 'fixed_weekly', 7, 'Asia/Tbilisi',
        40.00, 60, 180
    )
    ON CONFLICT (legal_entity_id, code) DO UPDATE
       SET name = EXCLUDED.name,
           standard_weekly_hours = EXCLUDED.standard_weekly_hours,
           early_check_in_grace_minutes = EXCLUDED.early_check_in_grace_minutes,
           late_check_out_grace_minutes = EXCLUDED.late_check_out_grace_minutes,
           updated_at = now()
    RETURNING id INTO v_9_6;

    DELETE FROM shift_pattern_segments WHERE shift_pattern_id = v_9_6;
    INSERT INTO shift_pattern_segments (shift_pattern_id, day_index, start_time, planned_minutes, break_minutes, crosses_midnight, label)
    VALUES
        (v_9_6, 1, '09:00', 540, 60, false, 'Monday'),
        (v_9_6, 2, '09:00', 540, 60, false, 'Tuesday'),
        (v_9_6, 3, '09:00', 540, 60, false, 'Wednesday'),
        (v_9_6, 4, '09:00', 540, 60, false, 'Thursday'),
        (v_9_6, 5, '09:00', 540, 60, false, 'Friday');

    INSERT INTO shift_patterns (
        legal_entity_id, code, name, pattern_type, cycle_length_days, timezone,
        standard_weekly_hours, early_check_in_grace_minutes, late_check_out_grace_minutes
    )
    VALUES (
        p_legal_entity_id, 'FIRE_24_48', '24/48 Duty Shift', 'cycle', 3, 'Asia/Tbilisi',
        40.00, 120, 240
    )
    ON CONFLICT (legal_entity_id, code) DO UPDATE
       SET name = EXCLUDED.name,
           pattern_type = EXCLUDED.pattern_type,
           cycle_length_days = EXCLUDED.cycle_length_days,
           standard_weekly_hours = EXCLUDED.standard_weekly_hours,
           early_check_in_grace_minutes = EXCLUDED.early_check_in_grace_minutes,
           late_check_out_grace_minutes = EXCLUDED.late_check_out_grace_minutes,
           updated_at = now()
    RETURNING id INTO v_24_48;

    DELETE FROM shift_pattern_segments WHERE shift_pattern_id = v_24_48;
    INSERT INTO shift_pattern_segments (shift_pattern_id, day_index, start_time, planned_minutes, break_minutes, crosses_midnight, label)
    VALUES
        (v_24_48, 1, '08:00', 1440, 120, true, 'Duty day');

    INSERT INTO shift_patterns (
        legal_entity_id, code, name, pattern_type, cycle_length_days, timezone,
        standard_weekly_hours, early_check_in_grace_minutes, late_check_out_grace_minutes
    )
    VALUES (
        p_legal_entity_id, 'ROTATING_DAY_NIGHT', 'Rotating Day/Night', 'cycle', 2, 'Asia/Tbilisi',
        40.00, 60, 180
    )
    ON CONFLICT (legal_entity_id, code) DO UPDATE
       SET name = EXCLUDED.name,
           pattern_type = EXCLUDED.pattern_type,
           cycle_length_days = EXCLUDED.cycle_length_days,
           standard_weekly_hours = EXCLUDED.standard_weekly_hours,
           early_check_in_grace_minutes = EXCLUDED.early_check_in_grace_minutes,
           late_check_out_grace_minutes = EXCLUDED.late_check_out_grace_minutes,
           updated_at = now()
    RETURNING id INTO v_rotating;

    DELETE FROM shift_pattern_segments WHERE shift_pattern_id = v_rotating;
    INSERT INTO shift_pattern_segments (shift_pattern_id, day_index, start_time, planned_minutes, break_minutes, crosses_midnight, label)
    VALUES
        (v_rotating, 1, '08:00', 720, 60, false, 'Day shift'),
        (v_rotating, 2, '20:00', 720, 60, true, 'Night shift');
END;
$$;

CREATE TABLE assigned_shifts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    shift_pattern_id uuid NOT NULL REFERENCES shift_patterns(id) ON DELETE RESTRICT,
    employee_id uuid REFERENCES employees(id) ON DELETE CASCADE,
    department_id uuid REFERENCES departments(id) ON DELETE CASCADE,
    effective_from date NOT NULL,
    effective_to date,
    rotation_anchor_date date,
    created_by_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (num_nonnulls(employee_id, department_id) = 1),
    CHECK (effective_to IS NULL OR effective_to >= effective_from)
);
CREATE INDEX idx_assigned_shifts_employee_dates ON assigned_shifts (employee_id, effective_from, effective_to);
CREATE INDEX idx_assigned_shifts_department_dates ON assigned_shifts (department_id, effective_from, effective_to);

CREATE TABLE public_holidays_ge (
    holiday_date date PRIMARY KEY,
    holiday_code text NOT NULL UNIQUE,
    name_en text NOT NULL,
    name_ka text NOT NULL,
    is_movable boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE attendance_work_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    work_date date NOT NULL,
    assigned_shift_id uuid REFERENCES assigned_shifts(id) ON DELETE SET NULL,
    source_log_in_id bigint REFERENCES raw_attendance_logs(id) ON DELETE SET NULL,
    source_log_out_id bigint REFERENCES raw_attendance_logs(id) ON DELETE SET NULL,
    check_in_ts timestamptz NOT NULL,
    check_out_ts timestamptz,
    total_minutes integer NOT NULL DEFAULT 0 CHECK (total_minutes >= 0),
    night_minutes integer NOT NULL DEFAULT 0 CHECK (night_minutes >= 0),
    holiday_minutes integer NOT NULL DEFAULT 0 CHECK (holiday_minutes >= 0),
    overtime_minutes integer NOT NULL DEFAULT 0 CHECK (overtime_minutes >= 0),
    review_status review_status NOT NULL DEFAULT 'open',
    incomplete_reason text,
    manager_review_required boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (check_out_ts IS NULL OR check_out_ts >= check_in_ts)
);
CREATE INDEX idx_attendance_work_sessions_employee_work_date ON attendance_work_sessions (employee_id, work_date);
CREATE INDEX idx_attendance_work_sessions_review ON attendance_work_sessions (manager_review_required, review_status) WHERE manager_review_required = true;

CREATE TABLE attendance_review_flags (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    session_id uuid REFERENCES attendance_work_sessions(id) ON DELETE CASCADE,
    work_date date NOT NULL,
    flag_type text NOT NULL,
    severity text NOT NULL CHECK (severity IN ('low', 'medium', 'high')),
    details text NOT NULL,
    raised_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    resolved_by_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
    resolution_note text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_attendance_review_flags_open ON attendance_review_flags (employee_id, work_date, raised_at DESC) WHERE resolved_at IS NULL;

CREATE TABLE monthly_timesheets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    year smallint NOT NULL CHECK (year >= 2000),
    month smallint NOT NULL CHECK (month BETWEEN 1 AND 12),
    total_minutes integer NOT NULL DEFAULT 0 CHECK (total_minutes >= 0),
    night_minutes integer NOT NULL DEFAULT 0 CHECK (night_minutes >= 0),
    holiday_minutes integer NOT NULL DEFAULT 0 CHECK (holiday_minutes >= 0),
    overtime_minutes integer NOT NULL DEFAULT 0 CHECK (overtime_minutes >= 0),
    incomplete_session_count integer NOT NULL DEFAULT 0 CHECK (incomplete_session_count >= 0),
    base_salary numeric(14,2) NOT NULL DEFAULT 0,
    overtime_pay numeric(14,2) NOT NULL DEFAULT 0,
    night_pay numeric(14,2) NOT NULL DEFAULT 0,
    holiday_pay numeric(14,2) NOT NULL DEFAULT 0,
    gross_pay numeric(14,2) NOT NULL DEFAULT 0,
    employee_pension_amount numeric(14,2) NOT NULL DEFAULT 0,
    income_tax_amount numeric(14,2) NOT NULL DEFAULT 0,
    net_pay numeric(14,2) NOT NULL DEFAULT 0,
    status timesheet_status NOT NULL DEFAULT 'draft',
    generated_at timestamptz NOT NULL DEFAULT now(),
    approved_at timestamptz,
    approved_by_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (employee_id, year, month)
);

CREATE TABLE asset_categories (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id uuid NOT NULL REFERENCES legal_entities(id) ON DELETE CASCADE,
    code citext NOT NULL,
    name_en text NOT NULL,
    name_ka text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (legal_entity_id, code)
);

CREATE TABLE inventory_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id uuid NOT NULL REFERENCES legal_entities(id) ON DELETE CASCADE,
    category_id uuid REFERENCES asset_categories(id) ON DELETE SET NULL,
    asset_tag text NOT NULL,
    asset_name text NOT NULL,
    brand text,
    model text,
    serial_number text,
    current_condition asset_condition NOT NULL DEFAULT 'new',
    current_status asset_status NOT NULL DEFAULT 'in_stock',
    purchase_date date,
    purchase_cost numeric(14,2),
    currency_code char(3) NOT NULL DEFAULT 'GEL',
    assigned_department_id uuid REFERENCES departments(id) ON DELETE SET NULL,
    notes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (legal_entity_id, asset_tag),
    UNIQUE (legal_entity_id, serial_number)
);

CREATE TABLE asset_assignments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    item_id uuid NOT NULL REFERENCES inventory_items(id) ON DELETE CASCADE,
    employee_id uuid NOT NULL REFERENCES employees(id) ON DELETE RESTRICT,
    assigned_by_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
    assigned_at timestamptz NOT NULL,
    expected_return_at timestamptz,
    returned_at timestamptz,
    condition_on_issue asset_condition NOT NULL,
    condition_on_return asset_condition,
    employee_acknowledged_at timestamptz,
    return_received_by_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
    note text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (returned_at IS NULL OR returned_at >= assigned_at)
);
ALTER TABLE asset_assignments
    ADD CONSTRAINT asset_assignments_no_overlap
    EXCLUDE USING gist (
        item_id WITH =,
        tstzrange(assigned_at, coalesce(returned_at, 'infinity'::timestamptz), '[)') WITH &&
    );
CREATE INDEX idx_asset_assignments_employee_open ON asset_assignments (employee_id, assigned_at DESC) WHERE returned_at IS NULL;

CREATE TABLE job_postings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id uuid NOT NULL REFERENCES legal_entities(id) ON DELETE CASCADE,
    department_id uuid REFERENCES departments(id) ON DELETE SET NULL,
    job_role_id uuid REFERENCES job_roles(id) ON DELETE SET NULL,
    posting_code text NOT NULL,
    title_en text NOT NULL,
    title_ka text NOT NULL,
    description text NOT NULL,
    employment_type text NOT NULL,
    location_text text,
    status recruitment_posting_status NOT NULL DEFAULT 'draft',
    open_positions integer NOT NULL DEFAULT 1 CHECK (open_positions >= 1),
    salary_min numeric(14,2),
    salary_max numeric(14,2),
    created_by_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
    published_at timestamptz,
    closes_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (legal_entity_id, posting_code)
);

CREATE TABLE candidates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id uuid NOT NULL REFERENCES legal_entities(id) ON DELETE CASCADE,
    first_name text NOT NULL,
    last_name text NOT NULL,
    email citext,
    phone text,
    city text,
    source text NOT NULL,
    current_company text,
    current_position text,
    notes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_candidates_lookup ON candidates (legal_entity_id, last_name, first_name);

CREATE TABLE candidate_pipeline_stages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id uuid NOT NULL REFERENCES legal_entities(id) ON DELETE CASCADE,
    code citext NOT NULL,
    name_en text NOT NULL,
    name_ka text NOT NULL,
    sort_order integer NOT NULL,
    is_terminal boolean NOT NULL DEFAULT false,
    is_hired boolean NOT NULL DEFAULT false,
    is_rejected boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (legal_entity_id, code),
    UNIQUE (legal_entity_id, sort_order)
);

CREATE TABLE candidate_applications (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_id uuid NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    job_posting_id uuid NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
    current_stage_id uuid NOT NULL REFERENCES candidate_pipeline_stages(id) ON DELETE RESTRICT,
    application_status pipeline_application_status NOT NULL DEFAULT 'active',
    owner_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
    applied_at timestamptz NOT NULL DEFAULT now(),
    decided_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (candidate_id, job_posting_id)
);
CREATE INDEX idx_candidate_applications_stage ON candidate_applications (current_stage_id, application_status);

CREATE TABLE candidate_pipeline (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id uuid NOT NULL REFERENCES candidate_applications(id) ON DELETE CASCADE,
    stage_id uuid NOT NULL REFERENCES candidate_pipeline_stages(id) ON DELETE RESTRICT,
    moved_by_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
    moved_at timestamptz NOT NULL DEFAULT now(),
    comment text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_candidate_pipeline_application ON candidate_pipeline (application_id, moved_at DESC);

CREATE TABLE hiring_checklist_templates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id uuid NOT NULL REFERENCES legal_entities(id) ON DELETE CASCADE,
    code citext NOT NULL,
    name_en text NOT NULL,
    name_ka text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (legal_entity_id, code)
);

CREATE TABLE hiring_checklist_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    template_id uuid NOT NULL REFERENCES hiring_checklist_templates(id) ON DELETE CASCADE,
    sort_order integer NOT NULL,
    item_code citext NOT NULL,
    label_en text NOT NULL,
    label_ka text NOT NULL,
    is_required boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (template_id, item_code),
    UNIQUE (template_id, sort_order)
);

CREATE TABLE candidate_hiring_checklists (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id uuid NOT NULL REFERENCES candidate_applications(id) ON DELETE CASCADE,
    template_id uuid NOT NULL REFERENCES hiring_checklist_templates(id) ON DELETE RESTRICT,
    status checklist_item_status NOT NULL DEFAULT 'pending',
    assigned_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (application_id, template_id)
);

CREATE TABLE candidate_hiring_checklist_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    checklist_id uuid NOT NULL REFERENCES candidate_hiring_checklists(id) ON DELETE CASCADE,
    checklist_item_id uuid NOT NULL REFERENCES hiring_checklist_items(id) ON DELETE RESTRICT,
    status checklist_item_status NOT NULL DEFAULT 'pending',
    completed_at timestamptz,
    completed_by_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
    note text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (checklist_id, checklist_item_id)
);

INSERT INTO access_roles (code, name_en, name_ka, description) VALUES
    ('ADMIN', 'System Administrator', 'სისტემის ადმინისტრატორი', 'Full administrative access to the HRMS'),
    ('HR', 'Human Resources', 'ადამიანური რესურსები', 'Full HR access including compensation and payroll export'),
    ('MANAGER', 'Manager', 'მენეჯერი', 'Department-limited attendance and team visibility'),
    ('EMPLOYEE', 'Employee', 'თანამშრომელი', 'Own profile and own attendance only'),
    ('RECRUITER', 'Recruiter', 'რეკრუტერი', 'Recruitment workflow access'),
    ('IT_ASSET', 'IT / Asset Controller', 'IT / აქტივების კონტროლერი', 'Device and inventory access')
ON CONFLICT (code) DO NOTHING;

INSERT INTO permissions (code, description) VALUES
    ('employee.read_self', 'Read own employee profile'),
    ('employee.read_department', 'Read employee profiles in own managed departments'),
    ('employee.manage', 'Create and update employee records'),
    ('attendance.read_self', 'Read own attendance and sessions'),
    ('attendance.read_department', 'Read attendance of direct department scope'),
    ('attendance.read_all', 'Read attendance of all employees'),
    ('attendance.review', 'Review and approve flagged attendance anomalies'),
    ('compensation.read_all', 'Read salary and compensation data'),
    ('payroll.export', 'Export payroll data'),
    ('device.manage', 'Manage biometric devices and command queue'),
    ('assets.read_self', 'Read assets assigned to self'),
    ('assets.read_all', 'Read all inventory items and assignments'),
    ('assets.manage', 'Assign and return company assets'),
    ('recruitment.read', 'Read recruitment pipeline'),
    ('recruitment.manage', 'Manage job postings and candidate pipeline')
ON CONFLICT (code) DO NOTHING;

INSERT INTO access_role_permissions (access_role_id, permission_code)
SELECT ar.id, rp.permission_code
FROM access_roles ar
JOIN (
    VALUES
        ('ADMIN', 'employee.read_self'),
        ('ADMIN', 'employee.read_department'),
        ('ADMIN', 'employee.manage'),
        ('ADMIN', 'attendance.read_self'),
        ('ADMIN', 'attendance.read_department'),
        ('ADMIN', 'attendance.read_all'),
        ('ADMIN', 'attendance.review'),
        ('ADMIN', 'compensation.read_all'),
        ('ADMIN', 'payroll.export'),
        ('ADMIN', 'device.manage'),
        ('ADMIN', 'assets.read_self'),
        ('ADMIN', 'assets.read_all'),
        ('ADMIN', 'assets.manage'),
        ('ADMIN', 'recruitment.read'),
        ('ADMIN', 'recruitment.manage'),
        ('HR', 'employee.read_self'),
        ('HR', 'employee.manage'),
        ('HR', 'attendance.read_self'),
        ('HR', 'attendance.read_all'),
        ('HR', 'attendance.review'),
        ('HR', 'compensation.read_all'),
        ('HR', 'payroll.export'),
        ('HR', 'recruitment.read'),
        ('HR', 'recruitment.manage'),
        ('MANAGER', 'employee.read_self'),
        ('MANAGER', 'employee.read_department'),
        ('MANAGER', 'attendance.read_self'),
        ('MANAGER', 'attendance.read_department'),
        ('MANAGER', 'attendance.review'),
        ('EMPLOYEE', 'employee.read_self'),
        ('EMPLOYEE', 'attendance.read_self'),
        ('EMPLOYEE', 'assets.read_self'),
        ('RECRUITER', 'employee.read_self'),
        ('RECRUITER', 'recruitment.read'),
        ('RECRUITER', 'recruitment.manage'),
        ('IT_ASSET', 'employee.read_self'),
        ('IT_ASSET', 'device.manage'),
        ('IT_ASSET', 'assets.read_all'),
        ('IT_ASSET', 'assets.manage')
) AS rp(role_code, permission_code)
    ON ar.code = rp.role_code
ON CONFLICT DO NOTHING;

CREATE OR REPLACE FUNCTION hrms.refresh_inventory_status()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE inventory_items
       SET current_status = CASE
            WHEN EXISTS (
                SELECT 1
                  FROM asset_assignments aa
                 WHERE aa.item_id = COALESCE(NEW.item_id, OLD.item_id)
                   AND aa.returned_at IS NULL
            ) THEN 'assigned'::asset_status
            ELSE 'in_stock'::asset_status
       END,
           updated_at = now()
     WHERE id = COALESCE(NEW.item_id, OLD.item_id);
    RETURN NULL;
END;
$$;

CREATE TRIGGER trg_asset_assignments_refresh_inventory_status
AFTER INSERT OR UPDATE OR DELETE ON asset_assignments
FOR EACH ROW EXECUTE FUNCTION hrms.refresh_inventory_status();

ALTER TABLE employee_compensation ENABLE ROW LEVEL SECURITY;
ALTER TABLE attendance_work_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE monthly_timesheets ENABLE ROW LEVEL SECURITY;
ALTER TABLE inventory_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE asset_assignments ENABLE ROW LEVEL SECURITY;

CREATE POLICY employee_compensation_hr_only ON employee_compensation
USING (coalesce(current_setting('app.is_hr', true), 'false')::boolean = true);

CREATE POLICY attendance_self_policy ON attendance_work_sessions
USING (employee_id = nullif(current_setting('app.current_employee_id', true), '')::uuid);

CREATE POLICY attendance_hr_all_policy ON attendance_work_sessions
USING (coalesce(current_setting('app.is_hr', true), 'false')::boolean = true);

CREATE POLICY attendance_manager_department_policy ON attendance_work_sessions
USING (
    employee_id IN (
        SELECT e.id
          FROM employees e
         WHERE e.department_id = ANY(hrms.uuid_array_setting('app.managed_department_ids'))
    )
);

CREATE POLICY monthly_timesheets_self_policy ON monthly_timesheets
USING (employee_id = nullif(current_setting('app.current_employee_id', true), '')::uuid);

CREATE POLICY monthly_timesheets_hr_policy ON monthly_timesheets
USING (coalesce(current_setting('app.is_hr', true), 'false')::boolean = true);

CREATE POLICY inventory_self_policy ON inventory_items
USING (
    EXISTS (
        SELECT 1
          FROM asset_assignments aa
         WHERE aa.item_id = inventory_items.id
           AND aa.employee_id = nullif(current_setting('app.current_employee_id', true), '')::uuid
           AND aa.returned_at IS NULL
    )
);

CREATE POLICY inventory_all_policy ON inventory_items
USING (coalesce(current_setting('app.can_read_assets_all', true), 'false')::boolean = true);

CREATE POLICY asset_assignments_self_policy ON asset_assignments
USING (employee_id = nullif(current_setting('app.current_employee_id', true), '')::uuid);

CREATE POLICY asset_assignments_all_policy ON asset_assignments
USING (coalesce(current_setting('app.can_read_assets_all', true), 'false')::boolean = true);

CREATE TRIGGER trg_legal_entities_updated_at BEFORE UPDATE ON legal_entities
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_departments_updated_at BEFORE UPDATE ON departments
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_job_roles_updated_at BEFORE UPDATE ON job_roles
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_access_roles_updated_at BEFORE UPDATE ON access_roles
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_pay_policies_updated_at BEFORE UPDATE ON pay_policies
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_employees_updated_at BEFORE UPDATE ON employees
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_employee_compensation_updated_at BEFORE UPDATE ON employee_compensation
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_device_registry_updated_at BEFORE UPDATE ON device_registry
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_employee_device_identities_updated_at BEFORE UPDATE ON employee_device_identities
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_device_command_queue_updated_at BEFORE UPDATE ON device_command_queue
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_shift_patterns_updated_at BEFORE UPDATE ON shift_patterns
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_assigned_shifts_updated_at BEFORE UPDATE ON assigned_shifts
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_attendance_work_sessions_updated_at BEFORE UPDATE ON attendance_work_sessions
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_monthly_timesheets_updated_at BEFORE UPDATE ON monthly_timesheets
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_asset_categories_updated_at BEFORE UPDATE ON asset_categories
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_inventory_items_updated_at BEFORE UPDATE ON inventory_items
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_asset_assignments_updated_at BEFORE UPDATE ON asset_assignments
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_job_postings_updated_at BEFORE UPDATE ON job_postings
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_candidates_updated_at BEFORE UPDATE ON candidates
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_candidate_pipeline_stages_updated_at BEFORE UPDATE ON candidate_pipeline_stages
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_candidate_applications_updated_at BEFORE UPDATE ON candidate_applications
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_hiring_checklist_templates_updated_at BEFORE UPDATE ON hiring_checklist_templates
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_hiring_checklist_items_updated_at BEFORE UPDATE ON hiring_checklist_items
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_candidate_hiring_checklists_updated_at BEFORE UPDATE ON candidate_hiring_checklists
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_candidate_hiring_checklist_items_updated_at BEFORE UPDATE ON candidate_hiring_checklist_items
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();

COMMIT;
