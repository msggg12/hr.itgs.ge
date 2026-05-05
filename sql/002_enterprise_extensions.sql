BEGIN;
SET search_path TO hrms, public;

DO $$ BEGIN
    CREATE TYPE approval_status AS ENUM ('draft', 'submitted', 'approved', 'rejected', 'cancelled');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TYPE work_mode AS ENUM ('office', 'remote', 'leave', 'business_trip', 'off');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TYPE evidence_phase AS ENUM ('issue', 'return');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TYPE onboarding_module_type AS ENUM ('video', 'quiz');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TYPE onboarding_assignment_status AS ENUM ('assigned', 'in_progress', 'completed', 'overdue');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TYPE clearance_status AS ENUM ('open', 'blocked', 'cleared');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TYPE okr_scope AS ENUM ('department', 'employee');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TYPE feedback_relation AS ENUM ('self', 'peer', 'manager');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TYPE theme_preference AS ENUM ('system', 'light', 'dark');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS employee_chat_accounts (
    employee_id uuid PRIMARY KEY REFERENCES employees(id) ON DELETE CASCADE,
    mattermost_user_id text UNIQUE,
    mattermost_username citext UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS auth_identities (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    username citext NOT NULL UNIQUE,
    password_hash text NOT NULL,
    is_active boolean NOT NULL DEFAULT true,
    last_login_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mattermost_integrations (
    legal_entity_id uuid PRIMARY KEY REFERENCES legal_entities(id) ON DELETE CASCADE,
    enabled boolean NOT NULL DEFAULT false,
    server_base_url text,
    incoming_webhook_url text,
    hr_webhook_url text,
    general_webhook_url text,
    it_webhook_url text,
    bot_access_token text,
    command_token text UNIQUE,
    action_secret text,
    default_team text,
    hr_channel text,
    general_channel text,
    it_channel text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS leave_types (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id uuid NOT NULL REFERENCES legal_entities(id) ON DELETE CASCADE,
    code citext NOT NULL,
    name_en text NOT NULL,
    name_ka text NOT NULL,
    is_paid boolean NOT NULL DEFAULT true,
    annual_allowance_days numeric(8,2) NOT NULL DEFAULT 0,
    carryover_limit_days numeric(8,2) NOT NULL DEFAULT 0,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (legal_entity_id, code)
);

CREATE TABLE IF NOT EXISTS leave_balances (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    leave_type_id uuid NOT NULL REFERENCES leave_types(id) ON DELETE CASCADE,
    balance_year smallint NOT NULL CHECK (balance_year >= 2000),
    opening_days numeric(8,2) NOT NULL DEFAULT 0,
    earned_days numeric(8,2) NOT NULL DEFAULT 0,
    used_days numeric(8,2) NOT NULL DEFAULT 0,
    adjusted_days numeric(8,2) NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (employee_id, leave_type_id, balance_year)
);

CREATE TABLE IF NOT EXISTS leave_requests (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    leave_type_id uuid NOT NULL REFERENCES leave_types(id) ON DELETE RESTRICT,
    manager_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    requested_days numeric(8,2) NOT NULL CHECK (requested_days >= 0),
    reason text NOT NULL,
    status approval_status NOT NULL DEFAULT 'submitted',
    approved_at timestamptz,
    rejected_at timestamptz,
    cancelled_at timestamptz,
    approved_by_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
    rejection_reason text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (end_date >= start_date)
);
CREATE INDEX IF NOT EXISTS idx_leave_requests_employee_dates ON leave_requests (employee_id, start_date, end_date);
CREATE INDEX IF NOT EXISTS idx_leave_requests_status ON leave_requests (status, start_date);

CREATE TABLE IF NOT EXISTS leave_request_approvals (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    leave_request_id uuid NOT NULL REFERENCES leave_requests(id) ON DELETE CASCADE,
    approver_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
    decision approval_status NOT NULL,
    decision_note text,
    decided_via text NOT NULL DEFAULT 'system',
    decided_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_leave_request_approvals_request ON leave_request_approvals (leave_request_id, decided_at DESC);

CREATE TABLE IF NOT EXISTS expense_claims (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    manager_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
    claim_date date NOT NULL DEFAULT current_date,
    currency_code char(3) NOT NULL DEFAULT 'GEL',
    total_amount numeric(14,2) NOT NULL DEFAULT 0 CHECK (total_amount >= 0),
    status approval_status NOT NULL DEFAULT 'submitted',
    approved_by_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
    approved_at timestamptz,
    rejection_reason text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_expense_claims_employee_status ON expense_claims (employee_id, status, claim_date DESC);

CREATE TABLE IF NOT EXISTS expense_claim_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    expense_claim_id uuid NOT NULL REFERENCES expense_claims(id) ON DELETE CASCADE,
    expense_date date NOT NULL,
    category_code text NOT NULL,
    description text NOT NULL,
    amount numeric(14,2) NOT NULL CHECK (amount >= 0),
    attachment_url text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS expense_claim_approvals (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    expense_claim_id uuid NOT NULL REFERENCES expense_claims(id) ON DELETE CASCADE,
    approver_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
    decision approval_status NOT NULL,
    decision_note text,
    decided_via text NOT NULL DEFAULT 'system',
    decided_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_expense_claim_approvals_claim ON expense_claim_approvals (expense_claim_id, decided_at DESC);

CREATE TABLE IF NOT EXISTS employee_status_calendar (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    status_date date NOT NULL,
    work_mode work_mode NOT NULL,
    note text,
    created_by_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (employee_id, status_date)
);
CREATE INDEX IF NOT EXISTS idx_employee_status_calendar_date ON employee_status_calendar (status_date, work_mode);

CREATE TABLE IF NOT EXISTS onboarding_courses (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id uuid NOT NULL REFERENCES legal_entities(id) ON DELETE CASCADE,
    code citext NOT NULL,
    name_en text NOT NULL,
    name_ka text NOT NULL,
    description text,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (legal_entity_id, code)
);

CREATE TABLE IF NOT EXISTS onboarding_course_modules (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id uuid NOT NULL REFERENCES onboarding_courses(id) ON DELETE CASCADE,
    sort_order integer NOT NULL CHECK (sort_order >= 1),
    module_type onboarding_module_type NOT NULL,
    title text NOT NULL,
    description text,
    media_url text,
    duration_seconds integer,
    passing_score integer CHECK (passing_score IS NULL OR (passing_score BETWEEN 0 AND 100)),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (course_id, sort_order)
);

CREATE TABLE IF NOT EXISTS onboarding_quiz_questions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    module_id uuid NOT NULL REFERENCES onboarding_course_modules(id) ON DELETE CASCADE,
    sort_order integer NOT NULL CHECK (sort_order >= 1),
    question_text text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (module_id, sort_order)
);

CREATE TABLE IF NOT EXISTS onboarding_quiz_options (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    question_id uuid NOT NULL REFERENCES onboarding_quiz_questions(id) ON DELETE CASCADE,
    option_key text NOT NULL,
    option_text text NOT NULL,
    is_correct boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (question_id, option_key)
);

CREATE TABLE IF NOT EXISTS onboarding_course_assignments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    course_id uuid NOT NULL REFERENCES onboarding_courses(id) ON DELETE RESTRICT,
    assigned_by_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
    assigned_at timestamptz NOT NULL DEFAULT now(),
    due_at timestamptz,
    status onboarding_assignment_status NOT NULL DEFAULT 'assigned',
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (employee_id, course_id, assigned_at)
);
CREATE INDEX IF NOT EXISTS idx_onboarding_course_assignments_employee_status ON onboarding_course_assignments (employee_id, status);

CREATE TABLE IF NOT EXISTS onboarding_assignment_modules (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    assignment_id uuid NOT NULL REFERENCES onboarding_course_assignments(id) ON DELETE CASCADE,
    module_id uuid NOT NULL REFERENCES onboarding_course_modules(id) ON DELETE RESTRICT,
    status onboarding_assignment_status NOT NULL DEFAULT 'assigned',
    watched_seconds integer NOT NULL DEFAULT 0,
    score_percent integer CHECK (score_percent IS NULL OR (score_percent BETWEEN 0 AND 100)),
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (assignment_id, module_id)
);

CREATE TABLE IF NOT EXISTS entity_operation_settings (
    legal_entity_id uuid PRIMARY KEY REFERENCES legal_entities(id) ON DELETE CASCADE,
    late_arrival_threshold_minutes integer NOT NULL DEFAULT 15 CHECK (late_arrival_threshold_minutes BETWEEN 1 AND 240),
    require_asset_clearance_for_final_payroll boolean NOT NULL DEFAULT true,
    default_onboarding_course_id uuid REFERENCES onboarding_courses(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS asset_condition_evidence (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    assignment_id uuid NOT NULL REFERENCES asset_assignments(id) ON DELETE CASCADE,
    evidence_phase evidence_phase NOT NULL,
    file_url text NOT NULL,
    note text,
    captured_by_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
    captured_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_asset_condition_evidence_assignment ON asset_condition_evidence (assignment_id, evidence_phase);

CREATE TABLE IF NOT EXISTS offboarding_clearance_templates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id uuid NOT NULL REFERENCES legal_entities(id) ON DELETE CASCADE,
    code citext NOT NULL,
    name_en text NOT NULL,
    name_ka text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (legal_entity_id, code)
);

CREATE TABLE IF NOT EXISTS offboarding_clearance_template_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    template_id uuid NOT NULL REFERENCES offboarding_clearance_templates(id) ON DELETE CASCADE,
    sort_order integer NOT NULL CHECK (sort_order >= 1),
    item_code citext NOT NULL,
    label_en text NOT NULL,
    label_ka text NOT NULL,
    item_type text NOT NULL,
    is_required boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (template_id, item_code),
    UNIQUE (template_id, sort_order)
);

CREATE TABLE IF NOT EXISTS offboarding_clearances (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    manager_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
    status clearance_status NOT NULL DEFAULT 'open',
    started_at timestamptz NOT NULL DEFAULT now(),
    cleared_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_offboarding_clearances_employee_status ON offboarding_clearances (employee_id, status);

CREATE TABLE IF NOT EXISTS offboarding_clearance_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    clearance_id uuid NOT NULL REFERENCES offboarding_clearances(id) ON DELETE CASCADE,
    template_item_id uuid REFERENCES offboarding_clearance_template_items(id) ON DELETE SET NULL,
    asset_assignment_id uuid REFERENCES asset_assignments(id) ON DELETE SET NULL,
    item_label text NOT NULL,
    required boolean NOT NULL DEFAULT true,
    completed boolean NOT NULL DEFAULT false,
    completed_at timestamptz,
    completed_by_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
    note text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_offboarding_clearance_items_clearance ON offboarding_clearance_items (clearance_id, completed);

CREATE TABLE IF NOT EXISTS final_payroll_holds (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    hold_reason text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    resolved_by_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
    resolution_note text
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_final_payroll_holds_active_unique ON final_payroll_holds (employee_id) WHERE resolved_at IS NULL;

CREATE TABLE IF NOT EXISTS okr_cycles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id uuid NOT NULL REFERENCES legal_entities(id) ON DELETE CASCADE,
    code citext NOT NULL,
    title text NOT NULL,
    year smallint NOT NULL CHECK (year >= 2000),
    quarter smallint NOT NULL CHECK (quarter BETWEEN 1 AND 4),
    start_date date NOT NULL,
    end_date date NOT NULL,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (legal_entity_id, code),
    CHECK (end_date >= start_date)
);

CREATE TABLE IF NOT EXISTS okr_objectives (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cycle_id uuid NOT NULL REFERENCES okr_cycles(id) ON DELETE CASCADE,
    scope okr_scope NOT NULL,
    department_id uuid REFERENCES departments(id) ON DELETE CASCADE,
    employee_id uuid REFERENCES employees(id) ON DELETE CASCADE,
    owner_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
    title text NOT NULL,
    description text,
    weight numeric(8,2) NOT NULL DEFAULT 1.00 CHECK (weight > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
        (scope = 'department' AND department_id IS NOT NULL AND employee_id IS NULL)
        OR (scope = 'employee' AND employee_id IS NOT NULL)
    )
);
CREATE INDEX IF NOT EXISTS idx_okr_objectives_cycle_scope ON okr_objectives (cycle_id, scope);

CREATE TABLE IF NOT EXISTS okr_key_results (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    objective_id uuid NOT NULL REFERENCES okr_objectives(id) ON DELETE CASCADE,
    title text NOT NULL,
    metric_unit text NOT NULL,
    start_value numeric(14,2) NOT NULL DEFAULT 0,
    target_value numeric(14,2) NOT NULL,
    current_value numeric(14,2) NOT NULL DEFAULT 0,
    last_check_in_note text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (target_value <> start_value)
);

CREATE TABLE IF NOT EXISTS feedback_cycles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id uuid NOT NULL REFERENCES legal_entities(id) ON DELETE CASCADE,
    code citext NOT NULL,
    title text NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    is_open boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (legal_entity_id, code),
    CHECK (end_date >= start_date)
);

CREATE TABLE IF NOT EXISTS feedback_entries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cycle_id uuid NOT NULL REFERENCES feedback_cycles(id) ON DELETE CASCADE,
    subject_employee_id uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    reviewer_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
    relation feedback_relation NOT NULL,
    overall_rating integer NOT NULL CHECK (overall_rating BETWEEN 1 AND 5),
    strengths text NOT NULL,
    improvements text NOT NULL,
    is_anonymous boolean NOT NULL DEFAULT false,
    submitted_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_feedback_entries_subject_cycle ON feedback_entries (subject_employee_id, cycle_id);

CREATE TABLE IF NOT EXISTS employee_separations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid NOT NULL UNIQUE REFERENCES employees(id) ON DELETE CASCADE,
    separation_date date NOT NULL,
    reason_category text NOT NULL,
    reason_details text,
    eligible_rehire boolean NOT NULL DEFAULT true,
    created_by_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_employee_separations_date ON employee_separations (separation_date, reason_category);

CREATE TABLE IF NOT EXISTS burnout_risk_alerts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    as_of_date date NOT NULL,
    risk_score integer NOT NULL CHECK (risk_score BETWEEN 0 AND 100),
    weekly_overtime_streak boolean NOT NULL DEFAULT false,
    no_leave_six_months boolean NOT NULL DEFAULT false,
    recommended_action text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    UNIQUE (employee_id, as_of_date)
);
CREATE INDEX IF NOT EXISTS idx_burnout_risk_alerts_open ON burnout_risk_alerts (employee_id, risk_score DESC) WHERE resolved_at IS NULL;

CREATE TABLE IF NOT EXISTS automation_dispatch_log (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_id uuid NOT NULL REFERENCES legal_entities(id) ON DELETE CASCADE,
    event_type text NOT NULL,
    event_key text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    dispatched_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (event_type, event_key)
);

CREATE TABLE IF NOT EXISTS employee_dashboard_preferences (
    employee_id uuid PRIMARY KEY REFERENCES employees(id) ON DELETE CASCADE,
    theme_preference theme_preference NOT NULL DEFAULT 'system',
    pinned_widgets text[] NOT NULL DEFAULT ARRAY[]::text[],
    layout_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    mobile_layout_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dashboard_widget_catalog (
    widget_code citext PRIMARY KEY,
    name_en text NOT NULL,
    name_ka text NOT NULL,
    description text NOT NULL,
    default_w integer NOT NULL CHECK (default_w >= 1),
    default_h integer NOT NULL CHECK (default_h >= 1),
    is_mobile_supported boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS deployment_nodes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    node_code citext NOT NULL UNIQUE,
    node_role text NOT NULL,
    base_url text,
    region text,
    is_active boolean NOT NULL DEFAULT true,
    last_heartbeat_at timestamptz,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS legal_entity_deployments (
    legal_entity_id uuid NOT NULL REFERENCES legal_entities(id) ON DELETE CASCADE,
    node_id uuid NOT NULL REFERENCES deployment_nodes(id) ON DELETE CASCADE,
    is_primary boolean NOT NULL DEFAULT true,
    active_since timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (legal_entity_id, node_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_legal_entity_deployments_primary ON legal_entity_deployments (legal_entity_id) WHERE is_primary = true;

CREATE TABLE IF NOT EXISTS service_heartbeats (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    node_id uuid NOT NULL REFERENCES deployment_nodes(id) ON DELETE CASCADE,
    service_name text NOT NULL,
    last_ok_at timestamptz,
    status text NOT NULL CHECK (status IN ('ok', 'degraded', 'down')),
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (node_id, service_name)
);

INSERT INTO dashboard_widget_catalog (widget_code, name_en, name_ka, description, default_w, default_h, is_mobile_supported)
VALUES
    ('TEAM_CALENDAR', 'Team Calendar', 'გუნდის კალენდარი', 'Upcoming leave, meetings and shifts for the team.', 4, 2, true),
    ('PENDING_APPROVALS', 'Pending Approvals', 'მოლოდინში მყოფი დამტკიცებები', 'Leave and expense approvals waiting for action.', 3, 2, true),
    ('MY_KPI_PROGRESS', 'My KPI Progress', 'ჩემი KPI პროგრესი', 'Current OKR and KPI completion percentages.', 3, 2, true),
    ('WHO_IS_IN', 'Who Is In', 'ვინ არის ოფისში', 'Live attendance snapshot based on latest device logs.', 3, 2, true),
    ('BURNOUT_RISK', 'Burnout Risk', 'გადაღლის რისკი', 'HR analytics showing employees at burnout risk.', 4, 2, false),
    ('ASSETS_DUE_BACK', 'Assets Due Back', 'დასაბრუნებელი აქტივები', 'Open assignments and offboarding clearances.', 3, 2, true),
    ('RECRUITMENT_KANBAN', 'Recruitment Kanban', 'რეკრუტინგის კანბანი', 'Vacancy pipeline from draft to hire.', 4, 2, false)
ON CONFLICT (widget_code) DO NOTHING;

CREATE OR REPLACE FUNCTION hrms.seed_default_candidate_pipeline_stages(p_legal_entity_id uuid)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO candidate_pipeline_stages (legal_entity_id, code, name_en, name_ka, sort_order, is_terminal, is_hired, is_rejected)
    VALUES
        (p_legal_entity_id, 'APPLIED', 'Applied', 'განაცხადი მიღებულია', 10, false, false, false),
        (p_legal_entity_id, 'SCREEN', 'Screening', 'პირველადი გადარჩევა', 20, false, false, false),
        (p_legal_entity_id, 'INTERVIEW', 'Interview', 'გასაუბრება', 30, false, false, false),
        (p_legal_entity_id, 'OFFER', 'Offer', 'შეთავაზება', 40, false, false, false),
        (p_legal_entity_id, 'HIRED', 'Hired', 'დაქირავებული', 50, true, true, false),
        (p_legal_entity_id, 'REJECTED', 'Rejected', 'უარყოფილი', 60, true, false, true)
    ON CONFLICT (legal_entity_id, code) DO UPDATE
       SET name_en = EXCLUDED.name_en,
           name_ka = EXCLUDED.name_ka,
           sort_order = EXCLUDED.sort_order,
           is_terminal = EXCLUDED.is_terminal,
           is_hired = EXCLUDED.is_hired,
           is_rejected = EXCLUDED.is_rejected,
           updated_at = now();
END;
$$;

CREATE OR REPLACE VIEW v_ats_kanban_board AS
SELECT
    jp.id AS job_posting_id,
    jp.legal_entity_id,
    jp.posting_code,
    jp.title_en,
    jp.title_ka,
    jp.status::text AS posting_status,
    CASE
        WHEN jp.status = 'draft' THEN 'Draft'
        WHEN EXISTS (
            SELECT 1
              FROM candidate_applications ca
              JOIN candidate_pipeline_stages cps ON cps.id = ca.current_stage_id
             WHERE ca.job_posting_id = jp.id
               AND cps.is_hired = true
        ) THEN 'Hired'
        WHEN EXISTS (
            SELECT 1
              FROM candidate_applications ca
              JOIN candidate_pipeline_stages cps ON cps.id = ca.current_stage_id
             WHERE ca.job_posting_id = jp.id
               AND upper(cps.code::text) = 'OFFER'
        ) THEN 'Offer'
        WHEN EXISTS (
            SELECT 1
              FROM candidate_applications ca
              JOIN candidate_pipeline_stages cps ON cps.id = ca.current_stage_id
             WHERE ca.job_posting_id = jp.id
               AND upper(cps.code::text) = 'INTERVIEW'
        ) THEN 'Interview'
        ELSE 'Published'
    END AS board_column,
    (
        SELECT count(*)
          FROM candidate_applications ca
         WHERE ca.job_posting_id = jp.id
    ) AS total_candidates,
    (
        SELECT count(*)
          FROM candidate_applications ca
          JOIN candidate_pipeline_stages cps ON cps.id = ca.current_stage_id
         WHERE ca.job_posting_id = jp.id
           AND cps.is_hired = true
    ) AS hired_candidates
FROM job_postings jp;

CREATE OR REPLACE FUNCTION hrms.resolve_public_base_url(p_legal_entity_id uuid, p_fallback text)
RETURNS text
LANGUAGE sql
STABLE
AS $$
    SELECT coalesce(
        (
            SELECT dn.base_url
              FROM legal_entity_deployments led
              JOIN deployment_nodes dn ON dn.id = led.node_id
             WHERE led.legal_entity_id = p_legal_entity_id
               AND led.is_primary = true
               AND dn.is_active = true
             LIMIT 1
        ),
        p_fallback
    );
$$;

CREATE TRIGGER trg_employee_chat_accounts_updated_at BEFORE UPDATE ON employee_chat_accounts
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_mattermost_integrations_updated_at BEFORE UPDATE ON mattermost_integrations
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_leave_types_updated_at BEFORE UPDATE ON leave_types
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_leave_balances_updated_at BEFORE UPDATE ON leave_balances
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_leave_requests_updated_at BEFORE UPDATE ON leave_requests
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_employee_status_calendar_updated_at BEFORE UPDATE ON employee_status_calendar
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_onboarding_courses_updated_at BEFORE UPDATE ON onboarding_courses
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_onboarding_course_modules_updated_at BEFORE UPDATE ON onboarding_course_modules
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_onboarding_quiz_questions_updated_at BEFORE UPDATE ON onboarding_quiz_questions
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_onboarding_course_assignments_updated_at BEFORE UPDATE ON onboarding_course_assignments
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_onboarding_assignment_modules_updated_at BEFORE UPDATE ON onboarding_assignment_modules
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_entity_operation_settings_updated_at BEFORE UPDATE ON entity_operation_settings
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_offboarding_clearance_templates_updated_at BEFORE UPDATE ON offboarding_clearance_templates
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_offboarding_clearance_template_items_updated_at BEFORE UPDATE ON offboarding_clearance_template_items
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_offboarding_clearances_updated_at BEFORE UPDATE ON offboarding_clearances
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_offboarding_clearance_items_updated_at BEFORE UPDATE ON offboarding_clearance_items
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_okr_cycles_updated_at BEFORE UPDATE ON okr_cycles
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_okr_objectives_updated_at BEFORE UPDATE ON okr_objectives
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_okr_key_results_updated_at BEFORE UPDATE ON okr_key_results
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_feedback_cycles_updated_at BEFORE UPDATE ON feedback_cycles
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_burnout_risk_alerts_updated_at BEFORE UPDATE ON burnout_risk_alerts
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_employee_dashboard_preferences_updated_at BEFORE UPDATE ON employee_dashboard_preferences
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_deployment_nodes_updated_at BEFORE UPDATE ON deployment_nodes
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();
CREATE TRIGGER trg_service_heartbeats_updated_at BEFORE UPDATE ON service_heartbeats
FOR EACH ROW EXECUTE FUNCTION hrms.touch_updated_at();

COMMIT;
