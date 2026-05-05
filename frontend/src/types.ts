export type Summary = {
  scope?: 'company' | 'self'
  active_employees: number
  terminated_employees: number
  pending_approvals: number
  online_devices: number
  pending_leave_requests?: number
  last_punch_at?: string | null
  last_punch_direction?: string | null
  is_checked_in?: boolean
}

export type WeeklyAttendancePoint = {
  label: string
  count: number
}

export type WidgetData = {
  summary: Summary
  weekly_attendance: WeeklyAttendancePoint[]
  upcoming_schedule: UpcomingScheduleData
}

export type UpcomingMeetingItem = {
  id: string
  title: string
  organizer: string | null
  organizer_email?: string | null
  employee_id?: string | null
  employee_name?: string | null
  employee_email?: string | null
  start_at: string
  end_at: string | null
  location: string | null
  link: string | null
  is_all_day: boolean
}

export type UpcomingScheduleData = {
  provider: 'google_calendar'
  configured: boolean
  connected: boolean
  google_email: string | null
  calendar_id: string | null
  meetings: UpcomingMeetingItem[]
  error: string | null
}

export type IntegrationOverview = {
  google_calendar: {
    provider: 'google_calendar'
    configured: boolean
    connected: boolean
    account_email: string | null
    calendar_id: string | null
    error: string | null
  }
  slack: {
    provider: 'slack'
    configured: boolean
    connected: boolean
    team_id: string | null
    team_name: string | null
    connected_by_employee_id: string | null
    error: string | null
  }
  email: {
    provider: 'email'
    configured: boolean
    connected: boolean
    from_email: string | null
    error: string | null
  }
}

export type MessageChannel = 'slack' | 'email'

export type GridItem = {
  id: string
  employee_number: string
  first_name: string
  last_name: string
  email: string | null
  mobile_phone: string | null
  hire_date: string
  employment_status: string
  department_name: string | null
  job_title: string | null
  manager_name: string | null
  profile_photo_url: string | null
  base_salary: string | number | null
  hourly_rate_override: string | number | null
  has_login_access: boolean
  is_checked_in?: boolean
  last_attendance_at?: string | null
  last_attendance_direction?: string | null
  can_edit?: boolean
}

export type GridResponse = {
  items: GridItem[]
  total: number
  page: number
  page_size: number
  page_count: number
  permissions: {
    can_create: boolean
    can_create_department: boolean
    can_edit: boolean
    can_view_salary: boolean
    can_import: boolean
    can_export: boolean
    can_grant_access: boolean
    can_sync_devices: boolean
    can_view_attendance: boolean
    can_offboard: boolean
    can_delete: boolean
  }
}

export type OptionItem = {
  id: string
  name_en?: string
  name_ka?: string
  title_en?: string
  title_ka?: string
  code?: string
  name?: string
  full_name?: string
  device_name?: string
  brand?: string
  host?: string
  device_user_id?: string
  card_number?: string | null
  pin_code?: string | null
}

export type PermissionCatalogItem = {
  code: string
  description: string
}

export type EmployeeFormOptions = {
  legal_entity_id: string
  departments: OptionItem[]
  job_roles: OptionItem[]
  pay_policies: OptionItem[]
  managers: OptionItem[]
  devices: OptionItem[]
  permissions: {
    can_edit: boolean
    can_view_salary: boolean
    can_sync_devices: boolean
    can_create_department: boolean
  }
}

export type FeatureFlags = {
  attendance_enabled: boolean
  payroll_enabled: boolean
  ats_enabled: boolean
  chat_enabled: boolean
  device_management_enabled: boolean
  mobile_sync_enabled: boolean
  assets_enabled: boolean
  org_chart_enabled: boolean
  performance_enabled: boolean
}

export type BootstrapData = {
  tenant: {
    legal_entity_id: string | null
    trade_name: string
    logo_url: string | null
    logo_text: string
    primary_color: string
    standalone_chat_url: string | null
    feature_flags: FeatureFlags
    ui_policies: {
      gps_only_check_in: boolean
      company_dashboard_enabled: boolean
      payroll_dashboard_enabled: boolean
      dashboard_widget_visibility: Record<string, boolean>
    }
  }
}

export type FeedEvent = {
  event_type: 'attendance' | 'device' | 'web_punch'
  event_id: string
  ts: string
  direction: string
  employee_id: string | null
  first_name: string | null
  last_name: string | null
  employee_number: string | null
  device_name: string
  host: string
  device_status: string | null
}

export type TopPerformerRow = {
  employee_id: string
  full_name: string
  score: number
  status: 'present' | 'late' | 'absent'
}

export type AnalyticsOverview = {
  weekly_hours_trend: Array<{ label: string; worked_hours: number }>
  staff_presence_ratio: {
    present: number
    away: number
    total: number
  }
  dashboard_series?: {
    labels: string[]
    this_week: {
      attendance: number[]
      late: number[]
      leave: number[]
      absences: number[]
    }
    last_week: {
      attendance: number[]
      late: number[]
      leave: number[]
      absences: number[]
    }
  }
  top_performers: TopPerformerRow[]
}

export type DashboardSummary = {
  legal_entity_id: string
  active_employees: number
  terminated_employees: number
  total_employees: number
  open_attendance_flags: number
  pending_leave_approvals: number
  devices_online: number
  offline_device_alerts: number
  open_offboarding_clearances: number
}

export type NodeItem = {
  node_code: string
  node_role: string
  base_url: string | null
  region: string | null
  last_heartbeat_at: string | null
  metadata?: Record<string, unknown>
  service_name: string | null
  status: string | null
  details?: Record<string, unknown>
}

export type MonitoringData = {
  devices: Array<{
    id: string
    device_name: string
    brand: string
    host: string
    port: number
    last_seen_at: string | null
    transport?: string
    connectivity: string
  }>
  nodes: NodeItem[]
}

export type AtsColumn = {
  code: string
  name_en: string
  name_ka: string
}

export type AtsCard = {
  id: string
  stage_code: string
  actual_stage_code: string
  first_name: string
  last_name: string
  email: string | null
  phone: string | null
  city: string | null
  posting_code: string
  job_title: string
  department_name: string | null
  applied_at: string | null
  owner_name: string
  salary_min: number | null
  salary_max: number | null
  compatibility_score?: number | null
  compatibility_summary?: string | null
  interview_scheduled_at?: string | null
  interview_duration_minutes?: number | null
  interview_notes?: string | null
  interview_calendar_url?: string | null
}

export type AtsBoardData = {
  legal_entity_id: string
  columns: AtsColumn[]
  cards: Record<string, AtsCard[]>
}

export type ShiftPatternSegment = {
  day_index: number
  start_time: string
  planned_minutes: number
  break_minutes: number
  crosses_midnight: boolean
  label: string | null
}

export type ShiftPattern = {
  id: string
  code: string
  name: string
  pattern_type: string
  cycle_length_days: number
  standard_weekly_hours: number
  segments: ShiftPatternSegment[]
}

export type ShiftEmployee = {
  id: string
  employee_number: string
  first_name: string
  last_name: string
  department_name: string | null
  job_title: string | null
  weekly_minutes: number
  weekly_minutes_map: Record<string, number>
  can_edit?: boolean
}

export type ShiftAssignment = {
  assignment_id: string
  employee_id: string
  shift_date: string
  shift_pattern_id: string
  pattern_name: string
  pattern_code: string
  planned_minutes: number
  start_time: string
  end_time?: string
  break_minutes: number
  crosses_midnight: boolean
  label: string
  is_custom?: boolean
}

export type ShiftPlannerData = {
  month_start: string
  month_end: string
  calendar_title: string
  selected_department_id?: string | null
  days: Array<{ date: string; label: string; day_index: number }>
  patterns: ShiftPattern[]
  employees: ShiftEmployee[]
  assignments: ShiftAssignment[]
  total: number
  page: number
  page_size: number
  page_count: number
  user_can_edit_shifts?: boolean
}

export type AttendanceHubDayStatus = {
  date: string
  status: 'present' | 'absent' | 'leave' | 'sick' | 'scheduled' | 'upcoming'
  icon: string
  label: string | null
  shift_label: string | null
  check_in_ts: string | null
  check_out_ts: string | null
  check_in_label: string | null
  check_out_label: string | null
  total_minutes: number
  late_minutes: number
  overtime_minutes: number
  exception_code?: string | null
  exception_label?: string | null
  punch_count?: number
}

export type AttendanceHubTeamRow = {
  employee_id: string
  employee_number: string
  employee_name: string
  first_name: string
  last_name: string
  job_title: string | null
  department_name: string | null
  day_statuses: AttendanceHubDayStatus[]
}

export type AttendanceHubReportRow = {
  employee_id: string
  employee_name: string
  employee_number: string
  job_title: string | null
  department_name: string | null
  total_minutes: number
  late_days: number
  overtime_minutes: number
  present_days: number
  absent_days: number
  leave_days: number
  sick_days: number
  exception_days?: number
}

export type AttendanceHubData = {
  mode: 'employee' | 'manager' | 'admin'
  grace_period_minutes: number
  can_manage_schedule: boolean
  can_manage_templates: boolean
  can_select_department: boolean
  selected_department_id: string | null
  selected_department_name: string | null
  departments: Array<{ id: string; name: string }>
  month_start: string
  month_end: string
  calendar_title: string
  days: Array<{ date: string; label: string; day_index: number }>
  team_rows: AttendanceHubTeamRow[]
  reports: AttendanceHubReportRow[]
  personal_summary: {
    employee_id: string
    employee_name: string
    total_minutes: number
    late_days: number
    overtime_minutes: number
    present_days: number
    absent_days: number
    leave_days: number
    sick_days: number
    exception_days?: number
  }
  personal_days: AttendanceHubDayStatus[]
}

export type AttendancePersonalReportData = {
  start_date: string
  end_date: string
  summary: AttendanceHubData['personal_summary']
  days: AttendanceHubDayStatus[]
}

export type AttendanceHistoryItem = {
  id: string | number
  event_ts: string
  direction: string
  verify_mode: string | null
  device_name: string | null
  work_date?: string
  weekly_minutes?: number
  overtime_minutes?: number
  late_minutes?: number
  is_late?: boolean
  is_overtime?: boolean
  highlight_tags?: string[]
}

export type CelebrationItem = {
  id: string
  first_name: string
  last_name: string
  date: string | null
  day_of_month: number
  years_completed?: number
}

export type CelebrationHubData = {
  month: number
  birthdays: CelebrationItem[]
  anniversaries: CelebrationItem[]
}

export type TeamChatConfig = {
  linked: boolean
  mattermost_user_id: string | null
  mattermost_username: string | null
  server_base_url: string | null
  default_team: string | null
  preferred_channel: string | null
  channel_url: string | null
}

export type LeaveTypeOption = {
  id: string
  code: string
  name_en: string
  name_ka: string
  is_paid: boolean
  annual_allowance_days: number
}

export type LeaveRequestHistoryItem = {
  id: string
  start_date: string
  end_date: string
  requested_days: number
  status: string
  reason: string
  leave_type_name: string
}

export type LeaveSelfServiceData = {
  employee_id: string
  employee_name: string
  hire_date: string
  current_year: number
  months_worked: number
  eligible_for_paid_leave: boolean
  eligibility_months: number
  statutory_earned_days: number
  earned_days: number
  used_days: number
  available_days: number
  unpaid_available_days: number
  opening_days: number
  adjusted_days: number
  policy: {
    paid_leave_allowance_days: number
    unpaid_leave_allowance_days: number
    eligibility_months: number
    enable_birthday_off: boolean
    enable_day_off: boolean
  }
  primary_leave_type: {
    id: string
    code: string
    name_en: string
    name_ka: string
    annual_allowance_days: number
  } | null
  leave_types: LeaveTypeOption[]
  requests: LeaveRequestHistoryItem[]
}

export type EmployeeDraft = {
  id?: string
  legal_entity_id: string
  employee_number: string
  personal_number: string
  first_name: string
  last_name: string
  email: string
  mobile_phone: string
  department_id: string
  job_role_id: string
  manager_employee_id: string
  hire_date: string
  salary_type: string
  base_salary: string
  pay_policy_id: string
  hourly_rate_override: string
  is_pension_participant: boolean
  default_device_user_id: string
  manager_name?: string
  profile_photo_url?: string
  new_job_role_title_ka: string
  new_job_role_title_en: string
  new_job_role_is_managerial: boolean
}

export type ShiftBuilderSegment = {
  day_index: number
  start_time: string
  end_time: string
  planned_minutes: number
  break_minutes: number
  crosses_midnight: boolean
  label: string | null
}

export type ShiftBuilderPattern = {
  id: string
  code: string
  name: string
  pattern_type: string
  cycle_length_days: number
  timezone: string
  standard_weekly_hours: number
  early_check_in_grace_minutes: number
  late_check_out_grace_minutes: number
  grace_period_minutes: number
  assignment_count: number
  segments: ShiftBuilderSegment[]
}

export type ShiftBuilderData = {
  patterns: ShiftBuilderPattern[]
}

export type WebPunchRecord = {
  id: string
  punch_ts: string
  direction: string
  source_ip: string | null
  latitude: number | null
  longitude: number | null
  location_name?: string | null
  location_source?: string | null
  is_location_suspicious?: boolean
  location_risk_reason?: string | null
  is_valid: boolean
  validation_reason: string | null
  source_type?: 'web' | 'device' | string
  device_name?: string | null
}

export type WebPunchConfigData = {
  config: {
    allowed_web_punch_ips: string[]
    geofence_latitude: number | null
    geofence_longitude: number | null
    geofence_radius_meters: number | null
  }
  status_summary: {
    is_checked_in: boolean
    current_direction: string
    current_segment_started_at: string | null
    completed_work_seconds_today: number
    current_segment_seconds: number
    worked_seconds_today: number
    today_punch_count: number
  }
  recent_punches: WebPunchRecord[]
}

export type AttendanceOverrideItem = {
  id: string
  employee_id: string
  employee_number: string
  first_name: string
  last_name: string
  session_id: string | null
  work_date: string
  flag_type: string
  severity: string
  details: string
  check_in_ts: string | null
  check_out_ts: string | null
  review_status: string | null
}

export type VacancyFieldOption = {
  label: string
  value: string
}

export type VacancyFieldDefinition = {
  key: string
  label: string
  field_type: string
  required: boolean
  options: VacancyFieldOption[]
}

export type VacancyItem = {
  id: string
  posting_code: string
  title_en: string
  title_ka: string
  description: string
  public_description: string | null
  employment_type: string
  status: string
  open_positions: number
  location_text: string | null
  public_slug: string | null
  external_form_url: string | null
  is_public: boolean
  application_form_schema: VacancyFieldDefinition[]
  salary_min: number
  salary_max: number
  closes_at: string | null
  department_name: string | null
  job_role_name: string | null
  application_count: number
  public_url: string | null
}

export type VacancyData = {
  items: VacancyItem[]
  departments: OptionItem[]
  job_roles: OptionItem[]
}

export type WarehouseItem = {
  id: string
  asset_tag: string
  asset_name: string
  brand: string | null
  model: string | null
  serial_number: string | null
  current_condition: string
  current_status: string
  purchase_date: string | null
  purchase_cost: number
  currency_code: string
  notes: string | null
  category_name: string | null
  assigned_employee_name: string | null
  active_assignment_id: string | null
}

export type WarehouseData = {
  categories: OptionItem[]
  employees: OptionItem[]
  items: WarehouseItem[]
}

export type PerformanceCycle = {
  id: string
  code: string
  title: string
  year: number
  quarter: number
  start_date: string
  end_date: string
}

export type PerformanceObjective = {
  id: string
  title: string
  scope: string
  weight: number
  department_name: string | null
  employee_name: string | null
  owner_name: string | null
  cycle_title: string
  key_result_count: number
  progress_percent: number
}

export type CapacityItem = {
  employee_id: string
  employee_name: string
  employee_number: string
  planned_hours: number
  objective_count: number
  utilization_score: number
  risk_band: string
}

export type PerformanceHubData = {
  cycles: PerformanceCycle[]
  objectives: PerformanceObjective[]
  heatmap: CapacityItem[]
  employees: OptionItem[]
}

export type PayrollHubItem = {
  id: string
  employee_id: string
  employee_number: string
  employee_name: string
  department_id: string | null
  department_name: string | null
  salary_type: string
  status: string
  base_salary: number
  gross_pay: number
  net_pay: number
  worked_hours: number
  overtime_hours: number
  payment_id: string | null
  paid_at: string | null
  payment_method: string | null
  payment_reference: string | null
  payslip_file_name: string | null
  payslip_url: string | null
}

export type PayrollHubData = {
  year: number
  month: number
  selected_department_id: string | null
  departments: OptionItem[]
  permissions: {
    can_generate_draft: boolean
    can_export: boolean
  }
  items: PayrollHubItem[]
}

export type DeviceRegistryItem = {
  id: string
  legal_entity_id: string
  tenant_name: string | null
  brand: string
  transport: string
  device_type: string
  device_name: string
  model: string
  serial_number: string
  host: string
  port: number
  api_base_url: string | null
  username: string | null
  password_ciphertext: string | null
  device_timezone: string
  is_active: boolean
  poll_interval_seconds: number
  metadata: Record<string, unknown>
  last_seen_at: string | null
  /** online | offline for bridge-monitored transports; unknown otherwise */
  connectivity?: string
}

export type DeviceRegistryData = {
  tenants: Array<{
    id: string
    trade_name: string
  }>
  items: DeviceRegistryItem[]
}

export type OrgChartNode = {
  id: string
  employee_number: string
  full_name: string
  manager_id: string | null
  manager_name: string | null
  department_name: string | null
  role_title: string | null
}

export type OrgChartData = {
  nodes: OrgChartNode[]
}

export type PersonalReportMovementItem = {
  id: string
  event_ts: string
  direction: string
  device_name: string
  source_type: string
}

export type PersonalReportsData = {
  movement_log: PersonalReportMovementItem[]
  summary: {
    month_start: string
    late_days: number
    overtime_hours: number
  }
  lateness_overtime_report: AttendanceHistoryItem[]
}

export type SystemConfigData = {
  legal_entity: {
    id: string
    legal_name: string
    trade_name: string
    tax_id: string
    timezone: string
    currency_code: string
  } | null
  access_context: {
    request_host: string | null
    tenant_isolation_active: boolean
  }
  tenants: Array<{
    id: string
    legal_name: string
    trade_name: string
    tax_id: string
    timezone: string
    currency_code: string
    primary_host: string | null
    employee_count: number
    login_count: number
  }>
  config: {
    logo_url: string | null
    logo_text: string | null
    primary_color: string
    standalone_chat_url: string | null
    linkedin_url: string | null
    facebook_url: string | null
    instagram_url: string | null
    allowed_web_punch_ips: string[]
    geofence_latitude: number | null
    geofence_longitude: number | null
    geofence_radius_meters: number | null
    gps_only_check_in: boolean
    company_dashboard_enabled: boolean
    payroll_dashboard_enabled: boolean
    dashboard_widget_visibility: Record<string, boolean>
    late_arrival_threshold_minutes: number
    require_asset_clearance_for_final_payroll: boolean
    default_onboarding_course_id: string | null
  }
  pay_policies: Array<{
    id: string
    code: string
    name: string
    income_tax_rate: number
    employee_pension_rate: number
  }>
  roles: Array<{
    id: string
    code: string
    name_en: string
    name_ka: string
  }>
  permission_catalog: PermissionCatalogItem[]
  role_permissions: Record<string, string[]>
  employees: Array<{
    id: string
    employee_number: string
    full_name: string
    role_codes: string[]
  }>
  departments: Array<{
    id: string
    name: string
  }>
  policy_access: {
    is_super_admin: boolean
    is_platform_super_admin: boolean
    can_manage_master_modules: boolean
  }
  leave_policy: {
    paid_leave_allowance_days: number
    unpaid_leave_allowance_days: number
    eligibility_months: number
    enable_birthday_off: boolean
    enable_day_off: boolean
    global_leave_approver_employee_id: string | null
  }
  schedule_manager_assignments: Array<{
    department_id: string
    employee_id: string
  }>
  department_employee_editors: Array<{
    department_id: string
    employee_id: string
  }>
  department_leave_approvers: Array<{
    department_id: string
    approver_employee_id: string | null
  }>
  mattermost: {
    enabled: boolean
    server_base_url: string | null
    default_team: string | null
    hr_channel: string | null
    general_channel: string | null
    it_channel: string | null
  } | null
  subscriptions: FeatureFlags
  domains: Array<{
    id: string
    host: string
    subdomain: string | null
    is_primary: boolean
    is_active: boolean
  }>
  worksites: Array<{
    id: string
    name: string
    latitude: number
    longitude: number
    radius_meters: number
    address_text: string | null
    is_active: boolean
  }>
  middleware_api_keys: Array<{
    id: string
    key_name: string
    last_used_at: string | null
    revoked_at: string | null
    created_at: string | null
  }>
  smtp: {
    configured: boolean
    host: string | null
    port: number
    username: string | null
    from_email: string | null
    use_tls: boolean
    managed_in: string
  }
  edge_middleware: {
    compose_file: string
    public_base_url: string
    device_workers_enabled: boolean
    ops_workers_enabled: boolean
  }
}

export type PublicCareersTenant = {
  legal_name: string
  trade_name: string
  logo_url: string | null
  logo_text: string | null
  primary_color: string
}

export type PublicCareersListItem = {
  id: string
  posting_code: string
  title_en: string
  title_ka: string | null
  summary: string
  employment_type: string
  location_text: string | null
  department_name: string | null
  open_positions: number
  salary_min: string | null
  salary_max: string | null
  detail_url: string
}

export type PublicCareersData = {
  tenant: PublicCareersTenant
  filters: {
    departments: string[]
    locations: string[]
  }
  items: PublicCareersListItem[]
  total: number
  page: number
  page_size: number
  page_count: number
}

export type PublicVacancyDetail = {
  id: string
  tenant_name: string | null
  primary_color: string | null
  posting_code: string
  title_en: string
  title_ka: string | null
  description: string
  public_description: string | null
  employment_type: string
  location_text: string | null
  status: string
  open_positions: number
  salary_min: string | null
  salary_max: string | null
  closes_at: string | null
  public_slug: string
  external_form_url: string | null
  is_public: boolean
  application_form_schema: VacancyFieldDefinition[]
  department_name: string | null
  job_role_name: string | null
}
