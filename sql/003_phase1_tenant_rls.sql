BEGIN;
SET search_path TO hrms, public;

CREATE OR REPLACE FUNCTION hrms.current_legal_entity_id()
RETURNS uuid
LANGUAGE sql
STABLE
AS $$
    SELECT nullif(current_setting('app.current_legal_entity_id', true), '')::uuid
$$;

CREATE OR REPLACE FUNCTION hrms.is_current_tenant(p_legal_entity_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
AS $$
    SELECT p_legal_entity_id IS NOT NULL
       AND p_legal_entity_id = hrms.current_legal_entity_id()
$$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hrms_app') THEN
        CREATE ROLE hrms_app NOLOGIN NOSUPERUSER NOBYPASSRLS;
    ELSE
        ALTER ROLE hrms_app NOSUPERUSER NOBYPASSRLS;
    END IF;
END $$;

GRANT USAGE ON SCHEMA hrms TO hrms_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA hrms TO hrms_app;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA hrms TO hrms_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA hrms GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO hrms_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA hrms GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO hrms_app;

CREATE TEMP TABLE _tenant_unique_constraints (
    table_name text NOT NULL,
    constraint_name text NOT NULL,
    constraint_sql text NOT NULL
) ON COMMIT DROP;

INSERT INTO _tenant_unique_constraints (table_name, constraint_name, constraint_sql) VALUES
    ('departments', 'uq_departments_id_legal_entity', 'UNIQUE (id, legal_entity_id)'),
    ('job_roles', 'uq_job_roles_id_legal_entity', 'UNIQUE (id, legal_entity_id)'),
    ('pay_policies', 'uq_pay_policies_id_legal_entity', 'UNIQUE (id, legal_entity_id)'),
    ('employees', 'uq_employees_id_legal_entity', 'UNIQUE (id, legal_entity_id)'),
    ('asset_categories', 'uq_asset_categories_id_legal_entity', 'UNIQUE (id, legal_entity_id)'),
    ('device_registry', 'uq_device_registry_id_legal_entity', 'UNIQUE (id, legal_entity_id)'),
    ('shift_patterns', 'uq_shift_patterns_id_legal_entity', 'UNIQUE (id, legal_entity_id)'),
    ('job_postings', 'uq_job_postings_id_legal_entity', 'UNIQUE (id, legal_entity_id)'),
    ('candidates', 'uq_candidates_id_legal_entity', 'UNIQUE (id, legal_entity_id)'),
    ('candidate_pipeline_stages', 'uq_candidate_pipeline_stages_id_legal_entity', 'UNIQUE (id, legal_entity_id)'),
    ('hiring_checklist_templates', 'uq_hiring_checklist_templates_id_legal_entity', 'UNIQUE (id, legal_entity_id)'),
    ('leave_types', 'uq_leave_types_id_legal_entity', 'UNIQUE (id, legal_entity_id)'),
    ('onboarding_courses', 'uq_onboarding_courses_id_legal_entity', 'UNIQUE (id, legal_entity_id)'),
    ('worksites', 'uq_worksites_id_legal_entity', 'UNIQUE (id, legal_entity_id)');

DO $$
DECLARE
    target record;
BEGIN
    FOR target IN SELECT * FROM _tenant_unique_constraints LOOP
        IF to_regclass(format('hrms.%I', target.table_name)) IS NULL THEN
            CONTINUE;
        END IF;
        IF NOT EXISTS (
            SELECT 1
              FROM pg_constraint
             WHERE connamespace = 'hrms'::regnamespace
               AND conname = target.constraint_name
        ) THEN
            EXECUTE format(
                'ALTER TABLE hrms.%I ADD CONSTRAINT %I %s',
                target.table_name,
                target.constraint_name,
                target.constraint_sql
            );
        END IF;
    END LOOP;
END $$;

CREATE TEMP TABLE _tenant_fk_constraints (
    table_name text NOT NULL,
    constraint_name text NOT NULL,
    constraint_sql text NOT NULL,
    required_columns text[] NOT NULL DEFAULT ARRAY[]::text[]
) ON COMMIT DROP;

INSERT INTO _tenant_fk_constraints (table_name, constraint_name, constraint_sql) VALUES
    ('departments', 'fk_departments_parent_same_tenant', 'FOREIGN KEY (parent_department_id, legal_entity_id) REFERENCES hrms.departments(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('departments', 'fk_departments_manager_same_tenant', 'FOREIGN KEY (manager_employee_id, legal_entity_id) REFERENCES hrms.employees(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('employees', 'fk_employees_department_same_tenant', 'FOREIGN KEY (department_id, legal_entity_id) REFERENCES hrms.departments(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('employees', 'fk_employees_job_role_same_tenant', 'FOREIGN KEY (job_role_id, legal_entity_id) REFERENCES hrms.job_roles(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('employees', 'fk_employees_manager_same_tenant', 'FOREIGN KEY (manager_employee_id, legal_entity_id) REFERENCES hrms.employees(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('employees', 'fk_employees_line_manager_same_tenant', 'FOREIGN KEY (line_manager_id, legal_entity_id) REFERENCES hrms.employees(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('inventory_items', 'fk_inventory_category_same_tenant', 'FOREIGN KEY (category_id, legal_entity_id) REFERENCES hrms.asset_categories(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('inventory_items', 'fk_inventory_department_same_tenant', 'FOREIGN KEY (assigned_department_id, legal_entity_id) REFERENCES hrms.departments(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('job_postings', 'fk_job_postings_department_same_tenant', 'FOREIGN KEY (department_id, legal_entity_id) REFERENCES hrms.departments(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('job_postings', 'fk_job_postings_job_role_same_tenant', 'FOREIGN KEY (job_role_id, legal_entity_id) REFERENCES hrms.job_roles(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('job_postings', 'fk_job_postings_creator_same_tenant', 'FOREIGN KEY (created_by_employee_id, legal_entity_id) REFERENCES hrms.employees(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('auth_invites', 'fk_auth_invites_employee_same_tenant', 'FOREIGN KEY (employee_id, legal_entity_id) REFERENCES hrms.employees(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('auth_invites', 'fk_auth_invites_creator_same_tenant', 'FOREIGN KEY (created_by_employee_id, legal_entity_id) REFERENCES hrms.employees(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('auth_refresh_sessions', 'fk_auth_refresh_sessions_employee_same_tenant', 'FOREIGN KEY (employee_id, legal_entity_id) REFERENCES hrms.employees(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('attendance_manual_adjustments', 'fk_attendance_manual_employee_same_tenant', 'FOREIGN KEY (employee_id, legal_entity_id) REFERENCES hrms.employees(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('attendance_manual_adjustments', 'fk_attendance_manual_creator_same_tenant', 'FOREIGN KEY (created_by_employee_id, legal_entity_id) REFERENCES hrms.employees(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('employee_file_uploads', 'fk_employee_file_uploads_employee_same_tenant', 'FOREIGN KEY (employee_id, legal_entity_id) REFERENCES hrms.employees(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('employee_file_uploads', 'fk_employee_file_uploads_creator_same_tenant', 'FOREIGN KEY (created_by_employee_id, legal_entity_id) REFERENCES hrms.employees(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('employee_google_calendar_connections', 'fk_google_calendar_employee_same_tenant', 'FOREIGN KEY (employee_id, legal_entity_id) REFERENCES hrms.employees(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('employee_message_dispatches', 'fk_message_sender_same_tenant', 'FOREIGN KEY (sender_employee_id, legal_entity_id) REFERENCES hrms.employees(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('employee_message_dispatches', 'fk_message_target_same_tenant', 'FOREIGN KEY (target_employee_id, legal_entity_id) REFERENCES hrms.employees(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('audit_logs', 'fk_audit_actor_same_tenant', 'FOREIGN KEY (actor_employee_id, legal_entity_id) REFERENCES hrms.employees(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('audit_logs', 'fk_audit_target_same_tenant', 'FOREIGN KEY (target_employee_id, legal_entity_id) REFERENCES hrms.employees(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('device_card_enrollment_sessions', 'fk_card_enrollment_employee_same_tenant', 'FOREIGN KEY (employee_id, legal_entity_id) REFERENCES hrms.employees(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('device_card_enrollment_sessions', 'fk_card_enrollment_device_same_tenant', 'FOREIGN KEY (device_id, legal_entity_id) REFERENCES hrms.device_registry(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('device_card_enrollment_sessions', 'fk_card_enrollment_creator_same_tenant', 'FOREIGN KEY (created_by_employee_id, legal_entity_id) REFERENCES hrms.employees(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('web_punch_events', 'fk_web_punch_employee_same_tenant', 'FOREIGN KEY (employee_id, legal_entity_id) REFERENCES hrms.employees(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('web_punch_events', 'fk_web_punch_worksite_same_tenant', 'FOREIGN KEY (worksite_id, legal_entity_id) REFERENCES hrms.worksites(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('worksites', 'fk_worksites_creator_same_tenant', 'FOREIGN KEY (created_by_employee_id, legal_entity_id) REFERENCES hrms.employees(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('department_schedule_managers', 'fk_dept_schedule_department_same_tenant', 'FOREIGN KEY (department_id, legal_entity_id) REFERENCES hrms.departments(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('department_schedule_managers', 'fk_dept_schedule_employee_same_tenant', 'FOREIGN KEY (employee_id, legal_entity_id) REFERENCES hrms.employees(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('department_schedule_managers', 'fk_dept_schedule_creator_same_tenant', 'FOREIGN KEY (created_by_employee_id, legal_entity_id) REFERENCES hrms.employees(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('department_employee_editors', 'fk_dept_editors_department_same_tenant', 'FOREIGN KEY (department_id, legal_entity_id) REFERENCES hrms.departments(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('department_employee_editors', 'fk_dept_editors_employee_same_tenant', 'FOREIGN KEY (employee_id, legal_entity_id) REFERENCES hrms.employees(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('department_employee_editors', 'fk_dept_editors_creator_same_tenant', 'FOREIGN KEY (created_by_employee_id, legal_entity_id) REFERENCES hrms.employees(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('department_leave_approvers', 'fk_dept_leave_department_same_tenant', 'FOREIGN KEY (department_id, legal_entity_id) REFERENCES hrms.departments(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('department_leave_approvers', 'fk_dept_leave_approver_same_tenant', 'FOREIGN KEY (approver_employee_id, legal_entity_id) REFERENCES hrms.employees(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('department_leave_approvers', 'fk_dept_leave_creator_same_tenant', 'FOREIGN KEY (created_by_employee_id, legal_entity_id) REFERENCES hrms.employees(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('entity_leave_policy_settings', 'fk_leave_policy_global_approver_same_tenant', 'FOREIGN KEY (global_leave_approver_employee_id, legal_entity_id) REFERENCES hrms.employees(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('entity_operation_settings', 'fk_entity_operation_onboarding_course_same_tenant', 'FOREIGN KEY (default_onboarding_course_id, legal_entity_id) REFERENCES hrms.onboarding_courses(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('tenant_role_permission_overrides', 'fk_role_overrides_creator_same_tenant', 'FOREIGN KEY (created_by_employee_id, legal_entity_id) REFERENCES hrms.employees(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('device_middleware_api_keys', 'fk_middleware_api_keys_creator_same_tenant', 'FOREIGN KEY (created_by_employee_id, legal_entity_id) REFERENCES hrms.employees(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE'),
    ('slack_workspace_connections', 'fk_slack_connected_by_same_tenant', 'FOREIGN KEY (connected_by_employee_id, legal_entity_id) REFERENCES hrms.employees(id, legal_entity_id) DEFERRABLE INITIALLY IMMEDIATE');

UPDATE _tenant_fk_constraints
   SET required_columns = ARRAY['line_manager_id', 'legal_entity_id']
 WHERE constraint_name = 'fk_employees_line_manager_same_tenant';

UPDATE _tenant_fk_constraints
   SET required_columns = ARRAY['default_onboarding_course_id', 'legal_entity_id']
 WHERE constraint_name = 'fk_entity_operation_onboarding_course_same_tenant';

DO $$
DECLARE
    target record;
BEGIN
    FOR target IN SELECT * FROM _tenant_fk_constraints LOOP
        IF to_regclass(format('hrms.%I', target.table_name)) IS NULL THEN
            CONTINUE;
        END IF;
        IF EXISTS (
            SELECT 1
              FROM unnest(target.required_columns) AS required_column(column_name)
             WHERE NOT EXISTS (
                SELECT 1
                  FROM information_schema.columns
                 WHERE table_schema = 'hrms'
                   AND table_name = target.table_name
                   AND column_name = required_column.column_name
             )
        ) THEN
            CONTINUE;
        END IF;
        IF NOT EXISTS (
            SELECT 1
              FROM pg_constraint
             WHERE connamespace = 'hrms'::regnamespace
               AND conname = target.constraint_name
        ) THEN
            EXECUTE format(
                'ALTER TABLE hrms.%I ADD CONSTRAINT %I %s',
                target.table_name,
                target.constraint_name,
                target.constraint_sql
            );
        END IF;
    END LOOP;
END $$;

CREATE OR REPLACE FUNCTION hrms.enforce_employee_compensation_tenant()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    employee_entity_id uuid;
    policy_entity_id uuid;
BEGIN
    SELECT legal_entity_id
      INTO employee_entity_id
      FROM hrms.employees
     WHERE id = NEW.employee_id;

    SELECT legal_entity_id
      INTO policy_entity_id
      FROM hrms.pay_policies
     WHERE id = NEW.policy_id;

    IF employee_entity_id IS NULL
       OR policy_entity_id IS NULL
       OR employee_entity_id <> policy_entity_id THEN
        RAISE EXCEPTION 'employee_compensation policy_id must belong to the employee tenant'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_employee_compensation_tenant ON hrms.employee_compensation;
CREATE CONSTRAINT TRIGGER trg_employee_compensation_tenant
AFTER INSERT OR UPDATE OF employee_id, policy_id ON hrms.employee_compensation
DEFERRABLE INITIALLY IMMEDIATE
FOR EACH ROW
EXECUTE FUNCTION hrms.enforce_employee_compensation_tenant();

CREATE TEMP TABLE _tenant_rls_policies (
    table_name text NOT NULL,
    using_sql text NOT NULL,
    check_sql text
) ON COMMIT DROP;

INSERT INTO _tenant_rls_policies (table_name, using_sql, check_sql) VALUES
    ('departments', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('job_roles', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('pay_policies', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('employees', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('device_registry', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('shift_patterns', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('asset_categories', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('inventory_items', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('job_postings', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('candidates', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('candidate_pipeline_stages', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('hiring_checklist_templates', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('leave_types', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('onboarding_courses', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('entity_operation_settings', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('offboarding_clearance_templates', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('okr_cycles', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('feedback_cycles', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('automation_dispatch_log', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('mattermost_integrations', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('legal_entity_deployments', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('worksites', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('web_punch_events', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('auth_invites', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('attendance_manual_adjustments', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('employee_file_uploads', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('employee_google_calendar_connections', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('slack_workspace_connections', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('employee_message_dispatches', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('audit_logs', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('device_middleware_api_keys', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('device_card_enrollment_sessions', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('auth_refresh_sessions', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('tenant_role_permission_overrides', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('entity_leave_policy_settings', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('department_schedule_managers', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('department_employee_editors', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('department_leave_approvers', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('tenant_subscriptions', 'hrms.is_current_tenant(legal_entity_id)', NULL),
    ('entity_system_config', 'hrms.is_current_tenant(legal_entity_id)', NULL),

    ('employee_access_roles', 'EXISTS (SELECT 1 FROM hrms.employees e WHERE e.id = employee_id AND hrms.is_current_tenant(e.legal_entity_id))', NULL),
    ('employee_compensation', 'EXISTS (SELECT 1 FROM hrms.employees e WHERE e.id = employee_id AND hrms.is_current_tenant(e.legal_entity_id))', NULL),
    ('employee_chat_accounts', 'EXISTS (SELECT 1 FROM hrms.employees e WHERE e.id = employee_id AND hrms.is_current_tenant(e.legal_entity_id))', NULL),
    ('auth_identities', 'EXISTS (SELECT 1 FROM hrms.employees e WHERE e.id = employee_id AND hrms.is_current_tenant(e.legal_entity_id))', NULL),
    ('password_reset_tokens', 'EXISTS (SELECT 1 FROM hrms.employees e WHERE e.id = employee_id AND hrms.is_current_tenant(e.legal_entity_id))', NULL),
    ('employee_dashboard_preferences', 'EXISTS (SELECT 1 FROM hrms.employees e WHERE e.id = employee_id AND hrms.is_current_tenant(e.legal_entity_id))', NULL),
    ('employee_separations', 'EXISTS (SELECT 1 FROM hrms.employees e WHERE e.id = employee_id AND hrms.is_current_tenant(e.legal_entity_id))', NULL),
    ('burnout_risk_alerts', 'EXISTS (SELECT 1 FROM hrms.employees e WHERE e.id = employee_id AND hrms.is_current_tenant(e.legal_entity_id))', NULL),
    ('final_payroll_holds', 'EXISTS (SELECT 1 FROM hrms.employees e WHERE e.id = employee_id AND hrms.is_current_tenant(e.legal_entity_id))', NULL),
    ('monthly_timesheets', 'EXISTS (SELECT 1 FROM hrms.employees e WHERE e.id = employee_id AND hrms.is_current_tenant(e.legal_entity_id))', NULL),
    ('attendance_work_sessions', 'EXISTS (SELECT 1 FROM hrms.employees e WHERE e.id = employee_id AND hrms.is_current_tenant(e.legal_entity_id))', NULL),
    ('attendance_review_flags', 'EXISTS (SELECT 1 FROM hrms.employees e WHERE e.id = employee_id AND hrms.is_current_tenant(e.legal_entity_id))', NULL),
    ('payroll_payment_records', 'EXISTS (SELECT 1 FROM hrms.employees e WHERE e.id = employee_id AND hrms.is_current_tenant(e.legal_entity_id))', NULL),
    ('leave_balances', 'EXISTS (SELECT 1 FROM hrms.employees e WHERE e.id = employee_id AND hrms.is_current_tenant(e.legal_entity_id))', NULL),
    ('leave_requests', 'EXISTS (SELECT 1 FROM hrms.employees e WHERE e.id = employee_id AND hrms.is_current_tenant(e.legal_entity_id))', NULL),
    ('expense_claims', 'EXISTS (SELECT 1 FROM hrms.employees e WHERE e.id = employee_id AND hrms.is_current_tenant(e.legal_entity_id))', NULL),
    ('employee_status_calendar', 'EXISTS (SELECT 1 FROM hrms.employees e WHERE e.id = employee_id AND hrms.is_current_tenant(e.legal_entity_id))', NULL),
    ('onboarding_course_assignments', 'EXISTS (SELECT 1 FROM hrms.employees e WHERE e.id = employee_id AND hrms.is_current_tenant(e.legal_entity_id))', NULL),
    ('offboarding_clearances', 'EXISTS (SELECT 1 FROM hrms.employees e WHERE e.id = employee_id AND hrms.is_current_tenant(e.legal_entity_id))', NULL),

    ('leave_request_approvals', 'EXISTS (SELECT 1 FROM hrms.leave_requests lr JOIN hrms.employees e ON e.id = lr.employee_id WHERE lr.id = leave_request_id AND hrms.is_current_tenant(e.legal_entity_id))', NULL),
    ('leave_request_files', 'EXISTS (SELECT 1 FROM hrms.leave_requests lr JOIN hrms.employees e ON e.id = lr.employee_id WHERE lr.id = leave_request_id AND hrms.is_current_tenant(e.legal_entity_id))', NULL),
    ('expense_claim_items', 'EXISTS (SELECT 1 FROM hrms.expense_claims ec JOIN hrms.employees e ON e.id = ec.employee_id WHERE ec.id = expense_claim_id AND hrms.is_current_tenant(e.legal_entity_id))', NULL),
    ('expense_claim_approvals', 'EXISTS (SELECT 1 FROM hrms.expense_claims ec JOIN hrms.employees e ON e.id = ec.employee_id WHERE ec.id = expense_claim_id AND hrms.is_current_tenant(e.legal_entity_id))', NULL),
    ('onboarding_assignment_modules', 'EXISTS (SELECT 1 FROM hrms.onboarding_course_assignments oca JOIN hrms.employees e ON e.id = oca.employee_id WHERE oca.id = assignment_id AND hrms.is_current_tenant(e.legal_entity_id))', NULL),
    ('onboarding_course_modules', 'EXISTS (SELECT 1 FROM hrms.onboarding_courses oc WHERE oc.id = course_id AND hrms.is_current_tenant(oc.legal_entity_id))', NULL),
    ('onboarding_quiz_questions', 'EXISTS (SELECT 1 FROM hrms.onboarding_course_modules ocm JOIN hrms.onboarding_courses oc ON oc.id = ocm.course_id WHERE ocm.id = module_id AND hrms.is_current_tenant(oc.legal_entity_id))', NULL),
    ('onboarding_quiz_options', 'EXISTS (SELECT 1 FROM hrms.onboarding_quiz_questions q JOIN hrms.onboarding_course_modules ocm ON ocm.id = q.module_id JOIN hrms.onboarding_courses oc ON oc.id = ocm.course_id WHERE q.id = question_id AND hrms.is_current_tenant(oc.legal_entity_id))', NULL),

    ('asset_assignments', 'EXISTS (SELECT 1 FROM hrms.inventory_items ii WHERE ii.id = item_id AND hrms.is_current_tenant(ii.legal_entity_id))', NULL),
    ('asset_condition_evidence', 'EXISTS (SELECT 1 FROM hrms.asset_assignments aa JOIN hrms.inventory_items ii ON ii.id = aa.item_id WHERE aa.id = assignment_id AND hrms.is_current_tenant(ii.legal_entity_id))', NULL),
    ('asset_handover_forms', 'EXISTS (SELECT 1 FROM hrms.asset_assignments aa JOIN hrms.inventory_items ii ON ii.id = aa.item_id WHERE aa.id = assignment_id AND hrms.is_current_tenant(ii.legal_entity_id))', NULL),

    ('assigned_shifts', 'EXISTS (SELECT 1 FROM hrms.shift_patterns sp WHERE sp.id = shift_pattern_id AND hrms.is_current_tenant(sp.legal_entity_id))', NULL),
    ('shift_pattern_segments', 'EXISTS (SELECT 1 FROM hrms.shift_patterns sp WHERE sp.id = shift_pattern_id AND hrms.is_current_tenant(sp.legal_entity_id))', NULL),
    ('employee_device_identities', 'EXISTS (SELECT 1 FROM hrms.device_registry dr WHERE dr.id = device_id AND hrms.is_current_tenant(dr.legal_entity_id))', NULL),
    ('biometric_templates', 'EXISTS (SELECT 1 FROM hrms.employees e WHERE e.id = employee_id AND hrms.is_current_tenant(e.legal_entity_id))', NULL),
    ('device_command_queue', 'EXISTS (SELECT 1 FROM hrms.device_registry dr WHERE dr.id = device_id AND hrms.is_current_tenant(dr.legal_entity_id))', NULL),
    ('device_push_batches', 'EXISTS (SELECT 1 FROM hrms.device_registry dr WHERE dr.id = device_id AND hrms.is_current_tenant(dr.legal_entity_id))', NULL),
    ('raw_attendance_logs', 'EXISTS (SELECT 1 FROM hrms.device_registry dr WHERE dr.id = device_id AND hrms.is_current_tenant(dr.legal_entity_id))', NULL),

    ('candidate_applications', 'EXISTS (SELECT 1 FROM hrms.candidates c WHERE c.id = candidate_id AND hrms.is_current_tenant(c.legal_entity_id))', NULL),
    ('candidate_pipeline', 'EXISTS (SELECT 1 FROM hrms.candidate_applications ca JOIN hrms.candidates c ON c.id = ca.candidate_id WHERE ca.id = application_id AND hrms.is_current_tenant(c.legal_entity_id))', NULL),
    ('candidate_hiring_checklists', 'EXISTS (SELECT 1 FROM hrms.candidate_applications ca JOIN hrms.candidates c ON c.id = ca.candidate_id WHERE ca.id = application_id AND hrms.is_current_tenant(c.legal_entity_id))', NULL),
    ('candidate_hiring_checklist_items', 'EXISTS (SELECT 1 FROM hrms.candidate_hiring_checklists chc JOIN hrms.candidate_applications ca ON ca.id = chc.application_id JOIN hrms.candidates c ON c.id = ca.candidate_id WHERE chc.id = checklist_id AND hrms.is_current_tenant(c.legal_entity_id))', NULL),
    ('hiring_checklist_items', 'EXISTS (SELECT 1 FROM hrms.hiring_checklist_templates hct WHERE hct.id = template_id AND hrms.is_current_tenant(hct.legal_entity_id))', NULL),

    ('offboarding_clearance_template_items', 'EXISTS (SELECT 1 FROM hrms.offboarding_clearance_templates oct WHERE oct.id = template_id AND hrms.is_current_tenant(oct.legal_entity_id))', NULL),
    ('offboarding_clearance_items', 'EXISTS (SELECT 1 FROM hrms.offboarding_clearances oc JOIN hrms.employees e ON e.id = oc.employee_id WHERE oc.id = clearance_id AND hrms.is_current_tenant(e.legal_entity_id))', NULL),
    ('okr_objectives', 'EXISTS (SELECT 1 FROM hrms.okr_cycles cycle WHERE cycle.id = cycle_id AND hrms.is_current_tenant(cycle.legal_entity_id))', NULL),
    ('okr_key_results', 'EXISTS (SELECT 1 FROM hrms.okr_objectives obj JOIN hrms.okr_cycles cycle ON cycle.id = obj.cycle_id WHERE obj.id = objective_id AND hrms.is_current_tenant(cycle.legal_entity_id))', NULL),
    ('feedback_entries', 'EXISTS (SELECT 1 FROM hrms.feedback_cycles fc WHERE fc.id = cycle_id AND hrms.is_current_tenant(fc.legal_entity_id))', NULL);

DO $$
DECLARE
    target record;
    existing_policy record;
BEGIN
    FOR target IN SELECT * FROM _tenant_rls_policies LOOP
        IF to_regclass(format('hrms.%I', target.table_name)) IS NULL THEN
            CONTINUE;
        END IF;

        FOR existing_policy IN
            SELECT policyname
              FROM pg_policies
             WHERE schemaname = 'hrms'
               AND tablename = target.table_name
        LOOP
            EXECUTE format('DROP POLICY IF EXISTS %I ON hrms.%I', existing_policy.policyname, target.table_name);
        END LOOP;

        EXECUTE format('ALTER TABLE hrms.%I ENABLE ROW LEVEL SECURITY', target.table_name);
        EXECUTE format('ALTER TABLE hrms.%I FORCE ROW LEVEL SECURITY', target.table_name);
        EXECUTE format(
            'CREATE POLICY tenant_access ON hrms.%I AS PERMISSIVE FOR ALL TO PUBLIC USING (true) WITH CHECK (true)',
            target.table_name
        );
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON hrms.%I AS RESTRICTIVE FOR ALL TO PUBLIC USING (%s) WITH CHECK (%s)',
            target.table_name,
            target.using_sql,
            coalesce(target.check_sql, target.using_sql)
        );
    END LOOP;
END $$;

COMMIT;
