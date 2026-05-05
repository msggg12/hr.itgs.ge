import { useEffect, useMemo, useState } from 'react'

import { Building2, Globe2, MapPinned, MonitorCog, Palette, Shield, ShieldCheck, Users2 } from 'lucide-react'

import type { FeatureFlags, SystemConfigData } from '../types'

type SystemConfigPanelProps = {
  data: SystemConfigData | null
  onSaveConfig: (payload: {
    trade_name: string | null
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
    income_tax_rate: number | null
    employee_pension_rate: number | null
    late_arrival_threshold_minutes: number
    require_asset_clearance_for_final_payroll: boolean
    default_onboarding_course_id: string | null
  }) => Promise<void>
  onSaveRoles: (employeeId: string, roleCodes: string[]) => Promise<void>
  onSaveRolePermissions: (roleCode: string, permissionCodes: string[]) => Promise<void>
  onSaveScheduleManagers: (payload: { assignments: Array<{ department_id: string; employee_ids: string[] }> }) => Promise<void>
  onSaveEmployeeEditors: (payload: { assignments: Array<{ department_id: string; employee_ids: string[] }> }) => Promise<void>
  onSaveLeavePolicies: (payload: {
    paid_leave_allowance_days: number
    unpaid_leave_allowance_days: number
    eligibility_months: number
    enable_birthday_off: boolean
    enable_day_off: boolean
    global_leave_approver_employee_id: string | null
    department_approvers: Array<{ department_id: string; approver_employee_id: string | null }>
  }) => Promise<void>
  onSaveSubscriptions: (payload: FeatureFlags) => Promise<void>
  onSaveWorksites: (payload: { worksites: Array<{ id?: string | null; name: string; latitude: number; longitude: number; radius_meters: number; address_text: string | null; is_active: boolean }> }) => Promise<void>
  onCreateMiddlewareKey: (payload: { key_name: string }) => Promise<{ api_key: string; key_name: string }>
  onRevokeMiddlewareKey: (keyId: string) => Promise<void>
  onCreateTenant: (payload: {
    legal_name: string
    trade_name: string
    tax_id: string
    host: string | null
    subdomain: string | null
    admin_username: string
    admin_email: string
    admin_password: string
    admin_first_name: string
    admin_last_name: string
  }) => Promise<void>
  onSaveDomain: (domainId: string | null, payload: { host: string; subdomain: string | null; is_primary: boolean; is_active: boolean }) => Promise<void>
}

const emptyTenantForm = {
  legal_name: '',
  trade_name: '',
  tax_id: '',
  host: '',
  subdomain: '',
  admin_username: '',
  admin_email: '',
  admin_password: '',
  admin_first_name: 'Company',
  admin_last_name: 'Administrator'
}

const emptyDomainForm = {
  host: '',
  subdomain: '',
  is_primary: false,
  is_active: true
}

const defaultWidgets = {
  summary_cards: true,
  analytics: true,
  live_feed: true,
  action_center: true,
  upcoming_schedule: true,
  celebrations: true
}

const moduleLabels: Record<keyof FeatureFlags, string> = {
  attendance_enabled: 'Attendance',
  payroll_enabled: 'Payroll',
  ats_enabled: 'Recruitment',
  chat_enabled: 'Chat',
  device_management_enabled: 'Device Management',
  mobile_sync_enabled: 'Mobile App Sync',
  assets_enabled: 'Assets',
  org_chart_enabled: 'Org Chart',
  performance_enabled: 'Performance'
}

const permissionModuleLabels: Record<string, string> = {
  assets: 'Assets',
  attendance: 'Attendance',
  compensation: 'Compensation',
  device: 'Devices',
  employee: 'Employees',
  leave: 'Leave',
  payroll: 'Payroll',
  recruitment: 'Recruitment',
  settings: 'Settings'
}

function permissionModuleLabel(code: string): string {
  const prefix = code.split('.')[0] ?? code
  return permissionModuleLabels[prefix] ?? prefix.replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function permissionDisplayLabel(code: string, description: string): string {
  if (description.trim()) {
    return description
  }
  return code.split('.').slice(1).join('.').replace(/[._]/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}

export function SystemConfigPanel(props: SystemConfigPanelProps) {
  const [busy, setBusy] = useState(false)
  const [selectedEmployeeId, setSelectedEmployeeId] = useState('')
  const [selectedRoleCode, setSelectedRoleCode] = useState('ADMIN')
  const [editingDomainId, setEditingDomainId] = useState<string | null>(null)
  const [domainForm, setDomainForm] = useState(emptyDomainForm)
  const [tenantForm, setTenantForm] = useState(emptyTenantForm)
  const [issuedMiddlewareKey, setIssuedMiddlewareKey] = useState<{ key_name: string; api_key: string } | null>(null)
  const [middlewareKeyName, setMiddlewareKeyName] = useState('Branch Bridge')

  const [configForm, setConfigForm] = useState({
    trade_name: '',
    logo_url: '',
    logo_text: '',
    primary_color: '#1A2238',
    standalone_chat_url: '',
    linkedin_url: '',
    facebook_url: '',
    instagram_url: '',
    allowed_web_punch_ips: '',
    geofence_latitude: '',
    geofence_longitude: '',
    geofence_radius_meters: '',
    gps_only_check_in: false,
    company_dashboard_enabled: true,
    payroll_dashboard_enabled: true,
    dashboard_widget_visibility: { ...defaultWidgets },
    income_tax_rate: '',
    employee_pension_rate: '',
    late_arrival_threshold_minutes: '15',
    require_asset_clearance_for_final_payroll: true,
    default_onboarding_course_id: ''
  })
  const [subscriptionForm, setSubscriptionForm] = useState<FeatureFlags>({
    attendance_enabled: true,
    payroll_enabled: true,
    ats_enabled: true,
    chat_enabled: true,
    device_management_enabled: true,
    mobile_sync_enabled: true,
    assets_enabled: true,
    org_chart_enabled: true,
    performance_enabled: true
  })
  const [scheduleManagerForm, setScheduleManagerForm] = useState<Record<string, string[]>>({})
  const [employeeEditorForm, setEmployeeEditorForm] = useState<Record<string, string[]>>({})
  const [leaveApproverForm, setLeaveApproverForm] = useState<Record<string, string>>({})
  const [leavePolicyForm, setLeavePolicyForm] = useState({
    paid_leave_allowance_days: '24',
    unpaid_leave_allowance_days: '15',
    eligibility_months: '11',
    enable_birthday_off: false,
    enable_day_off: false,
    global_leave_approver_employee_id: ''
  })
  const [worksitesForm, setWorksitesForm] = useState<Array<{ id?: string | null; name: string; latitude: string; longitude: string; radius_meters: string; address_text: string; is_active: boolean }>>([])
  const [rolePermissionMatrix, setRolePermissionMatrix] = useState<Record<string, string[]>>({})

  useEffect(() => {
    if (!props.data) {
      return
    }
    const primaryPayPolicy = props.data.pay_policies[0]
    setConfigForm({
      trade_name: props.data.legal_entity?.trade_name ?? '',
      logo_url: props.data.config.logo_url ?? '',
      logo_text: props.data.config.logo_text ?? '',
      primary_color: props.data.config.primary_color,
      standalone_chat_url: props.data.config.standalone_chat_url ?? '',
      linkedin_url: props.data.config.linkedin_url ?? '',
      facebook_url: props.data.config.facebook_url ?? '',
      instagram_url: props.data.config.instagram_url ?? '',
      allowed_web_punch_ips: props.data.config.allowed_web_punch_ips.join(', '),
      geofence_latitude: props.data.config.geofence_latitude != null ? String(props.data.config.geofence_latitude) : '',
      geofence_longitude: props.data.config.geofence_longitude != null ? String(props.data.config.geofence_longitude) : '',
      geofence_radius_meters: props.data.config.geofence_radius_meters != null ? String(props.data.config.geofence_radius_meters) : '',
      gps_only_check_in: props.data.config.gps_only_check_in,
      company_dashboard_enabled: props.data.config.company_dashboard_enabled,
      payroll_dashboard_enabled: props.data.config.payroll_dashboard_enabled,
      dashboard_widget_visibility: { ...defaultWidgets, ...props.data.config.dashboard_widget_visibility },
      income_tax_rate: primaryPayPolicy ? String(primaryPayPolicy.income_tax_rate) : '',
      employee_pension_rate: primaryPayPolicy ? String(primaryPayPolicy.employee_pension_rate) : '',
      late_arrival_threshold_minutes: String(props.data.config.late_arrival_threshold_minutes),
      require_asset_clearance_for_final_payroll: props.data.config.require_asset_clearance_for_final_payroll,
      default_onboarding_course_id: props.data.config.default_onboarding_course_id ?? ''
    })
    setSubscriptionForm(props.data.subscriptions)
    setScheduleManagerForm(
      props.data.schedule_manager_assignments.reduce<Record<string, string[]>>((acc, item) => {
        acc[item.department_id] = [...(acc[item.department_id] ?? []), item.employee_id]
        return acc
      }, {})
    )
    setEmployeeEditorForm(
      props.data.department_employee_editors.reduce<Record<string, string[]>>((acc, item) => {
        acc[item.department_id] = [...(acc[item.department_id] ?? []), item.employee_id]
        return acc
      }, {})
    )
    setLeaveApproverForm(
      props.data.department_leave_approvers.reduce<Record<string, string>>((acc, item) => {
        acc[item.department_id] = item.approver_employee_id ?? ''
        return acc
      }, {})
    )
    setLeavePolicyForm({
      paid_leave_allowance_days: String(props.data.leave_policy.paid_leave_allowance_days),
      unpaid_leave_allowance_days: String(props.data.leave_policy.unpaid_leave_allowance_days),
      eligibility_months: String(props.data.leave_policy.eligibility_months),
      enable_birthday_off: props.data.leave_policy.enable_birthday_off,
      enable_day_off: props.data.leave_policy.enable_day_off,
      global_leave_approver_employee_id: props.data.leave_policy.global_leave_approver_employee_id ?? ''
    })
    setWorksitesForm(
      props.data.worksites.map((worksite) => ({
        id: worksite.id,
        name: worksite.name,
        latitude: String(worksite.latitude),
        longitude: String(worksite.longitude),
        radius_meters: String(worksite.radius_meters),
        address_text: worksite.address_text ?? '',
        is_active: worksite.is_active
      }))
    )
    setRolePermissionMatrix(props.data.role_permissions ?? {})
    setSelectedRoleCode((current) => props.data.roles.some((role) => role.code === current) ? current : (props.data.roles[0]?.code ?? 'ADMIN'))
  }, [props.data])

  const selectedEmployee = props.data?.employees.find((item) => item.id === selectedEmployeeId) ?? null
  const selectedRole = props.data?.roles.find((role) => role.code === selectedRoleCode) ?? null
  const canManageTenants = (props.data?.tenants.length ?? 0) > 0
  const canManageMasterModules = props.data?.policy_access.can_manage_master_modules ?? false
  const visibleRoles = useMemo(() => props.data?.roles ?? [], [props.data?.roles])
  const permissionMatrixRows = useMemo(
    () => (props.data?.permission_catalog ?? []).map((item) => ({
      module: permissionModuleLabel(item.code),
      label: permissionDisplayLabel(item.code, item.description),
      permissionCode: item.code
    })),
    [props.data?.permission_catalog],
  )
  const matrixGridStyle = useMemo(
    () => ({ gridTemplateColumns: `minmax(220px,1.15fr) repeat(${Math.max(visibleRoles.length, 1)}, minmax(0,0.7fr))` }),
    [visibleRoles.length],
  )

  async function run(action: () => Promise<void>) {
    setBusy(true)
    try {
      await action()
    } finally {
      setBusy(false)
    }
  }

  async function handleSaveConfig() {
    await run(async () => {
      await props.onSaveConfig({
        trade_name: configForm.trade_name || null,
        logo_url: configForm.logo_url || null,
        logo_text: configForm.logo_text || null,
        primary_color: configForm.primary_color,
        standalone_chat_url: configForm.standalone_chat_url || null,
        linkedin_url: configForm.linkedin_url || null,
        facebook_url: configForm.facebook_url || null,
        instagram_url: configForm.instagram_url || null,
        allowed_web_punch_ips: configForm.allowed_web_punch_ips.split(',').map((item) => item.trim()).filter(Boolean),
        geofence_latitude: configForm.geofence_latitude ? Number(configForm.geofence_latitude) : null,
        geofence_longitude: configForm.geofence_longitude ? Number(configForm.geofence_longitude) : null,
        geofence_radius_meters: configForm.geofence_radius_meters ? Number(configForm.geofence_radius_meters) : null,
        gps_only_check_in: configForm.gps_only_check_in,
        company_dashboard_enabled: configForm.company_dashboard_enabled,
        payroll_dashboard_enabled: configForm.payroll_dashboard_enabled,
        dashboard_widget_visibility: configForm.dashboard_widget_visibility,
        income_tax_rate: configForm.income_tax_rate ? Number(configForm.income_tax_rate) : null,
        employee_pension_rate: configForm.employee_pension_rate ? Number(configForm.employee_pension_rate) : null,
        late_arrival_threshold_minutes: Number(configForm.late_arrival_threshold_minutes || '15'),
        require_asset_clearance_for_final_payroll: configForm.require_asset_clearance_for_final_payroll,
        default_onboarding_course_id: configForm.default_onboarding_course_id || null
      })
    })
  }

  async function handleSaveSubscriptions() {
    await run(async () => props.onSaveSubscriptions(subscriptionForm))
  }

  async function handleSaveScheduleManagers() {
    await run(async () => {
      await props.onSaveScheduleManagers({
        assignments: (props.data?.departments ?? []).map((department) => ({
          department_id: department.id,
          employee_ids: scheduleManagerForm[department.id] ?? []
        }))
      })
    })
  }

  async function handleSaveEmployeeEditors() {
    await run(async () => {
      await props.onSaveEmployeeEditors({
        assignments: (props.data?.departments ?? []).map((department) => ({
          department_id: department.id,
          employee_ids: employeeEditorForm[department.id] ?? []
        }))
      })
    })
  }

  async function handleSaveLeavePolicies() {
    await run(async () => {
      await props.onSaveLeavePolicies({
        paid_leave_allowance_days: Number(leavePolicyForm.paid_leave_allowance_days || '0'),
        unpaid_leave_allowance_days: Number(leavePolicyForm.unpaid_leave_allowance_days || '0'),
        eligibility_months: Number(leavePolicyForm.eligibility_months || '0'),
        enable_birthday_off: leavePolicyForm.enable_birthday_off,
        enable_day_off: leavePolicyForm.enable_day_off,
        global_leave_approver_employee_id: leavePolicyForm.global_leave_approver_employee_id || null,
        department_approvers: (props.data?.departments ?? []).map((department) => ({
          department_id: department.id,
          approver_employee_id: leaveApproverForm[department.id] || null
        }))
      })
    })
  }

  async function handleSaveWorksites() {
    await run(async () => {
      await props.onSaveWorksites({
        worksites: worksitesForm
          .filter((item) => item.name.trim())
          .map((item) => ({
            id: item.id ?? null,
            name: item.name.trim(),
            latitude: Number(item.latitude),
            longitude: Number(item.longitude),
            radius_meters: Number(item.radius_meters || '150'),
            address_text: item.address_text.trim() || null,
            is_active: item.is_active
          }))
      })
    })
  }

  async function handleCreateMiddlewareKey() {
    await run(async () => {
      setIssuedMiddlewareKey(await props.onCreateMiddlewareKey({ key_name: middlewareKeyName.trim() || 'Branch Bridge' }))
    })
  }

  async function handleSaveDomain() {
    await run(async () => {
      await props.onSaveDomain(editingDomainId, {
        host: domainForm.host.trim(),
        subdomain: domainForm.subdomain.trim() || null,
        is_primary: domainForm.is_primary,
        is_active: domainForm.is_active
      })
      setEditingDomainId(null)
      setDomainForm(emptyDomainForm)
    })
  }

  async function handleCreateTenant() {
    await run(async () => {
      await props.onCreateTenant({
        legal_name: tenantForm.legal_name.trim(),
        trade_name: tenantForm.trade_name.trim(),
        tax_id: tenantForm.tax_id.trim(),
        host: tenantForm.host.trim() || null,
        subdomain: tenantForm.subdomain.trim() || null,
        admin_username: tenantForm.admin_username.trim(),
        admin_email: tenantForm.admin_email.trim(),
        admin_password: tenantForm.admin_password,
        admin_first_name: tenantForm.admin_first_name.trim(),
        admin_last_name: tenantForm.admin_last_name.trim()
      })
      setTenantForm(emptyTenantForm)
    })
  }

  async function toggleEmployeeRole(roleCode: string) {
    if (!selectedEmployee) {
      return
    }
    const nextRoles = selectedEmployee.role_codes.includes(roleCode)
      ? selectedEmployee.role_codes.filter((item) => item !== roleCode)
      : [...selectedEmployee.role_codes, roleCode]
    await run(async () => props.onSaveRoles(selectedEmployee.id, nextRoles))
  }

  function toggleRolePermission(roleCode: string, permissionCode: string) {
    setRolePermissionMatrix((current) => {
      const next = new Set(current[roleCode] ?? [])
      if (next.has(permissionCode)) {
        next.delete(permissionCode)
      } else {
        next.add(permissionCode)
      }
      return {
        ...current,
        [roleCode]: Array.from(next).sort()
      }
    })
  }

  async function handleSaveRolePermissions() {
    await run(async () => props.onSaveRolePermissions(selectedRoleCode, rolePermissionMatrix[selectedRoleCode] ?? []))
  }

  async function handleSavePrimaryRoleMatrix() {
    await run(async () => {
      for (const role of visibleRoles) {
        await props.onSaveRolePermissions(role.code, rolePermissionMatrix[role.code] ?? [])
      }
    })
  }

  function worksiteMapUrl(latitude: string, longitude: string) {
    const lat = Number(latitude)
    const lng = Number(longitude)
    if (Number.isNaN(lat) || Number.isNaN(lng)) {
      return null
    }
    const delta = 0.01
    const bbox = `${lng - delta}%2C${lat - delta}%2C${lng + delta}%2C${lat + delta}`
    return `https://www.openstreetmap.org/export/embed.html?bbox=${bbox}&layer=mapnik&marker=${lat}%2C${lng}`
  }

  return (
    <section className="space-y-6">
      <section id="settings-platform" className="panel-card scroll-mt-6">
        <div className="mb-5 flex items-center gap-3">
          <Building2 className="h-5 w-5 text-slate-700" />
          <div>
            <p className="section-kicker">Deployment</p>
            <h2 className="section-title">Tenant Containers & Domains</h2>
          </div>
        </div>
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(360px,0.85fr)]">
          <div className="rounded-2xl border border-slate-200 bg-white p-5">
            <div className={`rounded-2xl border px-4 py-4 text-sm ${props.data?.access_context.tenant_isolation_active ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-amber-200 bg-amber-50 text-amber-800'}`}>
              <p className="font-semibold">{props.data?.access_context.tenant_isolation_active ? 'Tenant isolation is active' : 'Shared platform host is active'}</p>
              <p className="mt-2 break-all">Request host: {props.data?.access_context.request_host ?? 'unknown'}</p>
            </div>
            {canManageTenants ? (
              <div className="mt-5 grid gap-4 xl:grid-cols-2">
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                  <p className="text-sm font-semibold text-slate-900">Create Tenant</p>
                  <div className="mt-4 grid gap-3">
                    <input className="input-shell" placeholder="Legal name" value={tenantForm.legal_name} onChange={(event) => setTenantForm((current) => ({ ...current, legal_name: event.target.value }))} />
                    <input className="input-shell" placeholder="Trade name" value={tenantForm.trade_name} onChange={(event) => setTenantForm((current) => ({ ...current, trade_name: event.target.value }))} />
                    <input className="input-shell" placeholder="Tax ID" value={tenantForm.tax_id} onChange={(event) => setTenantForm((current) => ({ ...current, tax_id: event.target.value }))} />
                    <input className="input-shell" placeholder="Primary host" value={tenantForm.host} onChange={(event) => setTenantForm((current) => ({ ...current, host: event.target.value }))} />
                    <input className="input-shell" placeholder="Subdomain" value={tenantForm.subdomain} onChange={(event) => setTenantForm((current) => ({ ...current, subdomain: event.target.value }))} />
                    <input className="input-shell" placeholder="Admin username" value={tenantForm.admin_username} onChange={(event) => setTenantForm((current) => ({ ...current, admin_username: event.target.value }))} />
                    <input className="input-shell" placeholder="Admin email" value={tenantForm.admin_email} onChange={(event) => setTenantForm((current) => ({ ...current, admin_email: event.target.value }))} />
                    <button type="button" className="primary-btn" onClick={() => void handleCreateTenant()} disabled={busy}>
                      Create Tenant
                    </button>
                  </div>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                  <p className="text-sm font-semibold text-slate-900">Existing Domains</p>
                  <div className="mt-4 space-y-2">
                    {(props.data?.domains ?? []).map((domain) => (
                      <button
                        key={domain.id}
                        type="button"
                        className="flex w-full items-center justify-between rounded-xl border border-slate-200 bg-white px-4 py-3 text-left text-sm"
                        onClick={() => {
                          setEditingDomainId(domain.id)
                          setDomainForm({
                            host: domain.host,
                            subdomain: domain.subdomain ?? '',
                            is_primary: domain.is_primary,
                            is_active: domain.is_active
                          })
                        }}
                      >
                        <div>
                          <div className="font-semibold text-slate-900">{domain.host}</div>
                          <div className="mt-1 text-xs text-slate-500">{domain.subdomain || 'No subdomain'}</div>
                        </div>
                        <span className={`rounded-full px-2 py-1 text-[11px] font-semibold ${domain.is_primary ? 'bg-slate-900 text-white' : 'bg-slate-200 text-slate-700'}`}>{domain.is_primary ? 'Primary' : 'Secondary'}</span>
                      </button>
                    ))}
                  </div>
                  <div className="mt-4 grid gap-3">
                    <input className="input-shell" placeholder="Host" value={domainForm.host} onChange={(event) => setDomainForm((current) => ({ ...current, host: event.target.value }))} />
                    <input className="input-shell" placeholder="Subdomain" value={domainForm.subdomain} onChange={(event) => setDomainForm((current) => ({ ...current, subdomain: event.target.value }))} />
                    <label className="flex items-center gap-2 text-sm text-slate-600">
                      <input type="checkbox" checked={domainForm.is_primary} onChange={(event) => setDomainForm((current) => ({ ...current, is_primary: event.target.checked }))} />
                      Primary domain
                    </label>
                    <label className="flex items-center gap-2 text-sm text-slate-600">
                      <input type="checkbox" checked={domainForm.is_active} onChange={(event) => setDomainForm((current) => ({ ...current, is_active: event.target.checked }))} />
                      Active
                    </label>
                    <button type="button" className="muted-btn" onClick={() => void handleSaveDomain()} disabled={busy}>
                      Save Domain
                    </button>
                  </div>
                </div>
              </div>
            ) : null}
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-5">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
              <Globe2 className="h-4 w-4 text-slate-600" />
              Tenant Snapshot
            </div>
            <div className="mt-4 space-y-3">
              {(props.data?.tenants ?? []).map((tenant) => (
                <div key={tenant.id} className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
                  <div className="font-semibold text-slate-900">{tenant.trade_name}</div>
                  <div className="mt-1 text-xs text-slate-500">{tenant.primary_host ?? 'No primary host'}</div>
                  <div className="mt-2 text-xs text-slate-500">{tenant.employee_count} employees • {tenant.login_count} active logins</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section id="settings-branding" className="panel-card scroll-mt-6">
        <div className="mb-5 flex items-center gap-3">
          <Palette className="h-5 w-5 text-slate-700" />
          <div>
            <p className="section-kicker">Branding & Policies</p>
            <h2 className="section-title">Company Settings</h2>
          </div>
        </div>
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <div className="rounded-2xl border border-slate-200 bg-white p-5">
            <div className="grid gap-4">
              <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                <div className="text-sm font-semibold text-slate-900">Brand identity</div>
                <p className="mt-1 text-sm text-slate-500">These values drive the tenant name, logo badge, careers page, and top-level branding.</p>
                <div className="mt-4 grid gap-3 md:grid-cols-2">
                  <input className="input-shell" placeholder="Trade name shown to employees" value={configForm.trade_name} onChange={(event) => setConfigForm((current) => ({ ...current, trade_name: event.target.value }))} />
                  <input className="input-shell" placeholder="Logo text fallback (for example: GE)" value={configForm.logo_text} onChange={(event) => setConfigForm((current) => ({ ...current, logo_text: event.target.value }))} />
                  <input className="input-shell md:col-span-2" placeholder="Logo image URL" value={configForm.logo_url} onChange={(event) => setConfigForm((current) => ({ ...current, logo_url: event.target.value }))} />
                  <input className="input-shell" placeholder="Primary brand color" value={configForm.primary_color} onChange={(event) => setConfigForm((current) => ({ ...current, primary_color: event.target.value }))} />
                  <input className="input-shell" placeholder="Public chat / Mattermost URL (optional)" value={configForm.standalone_chat_url} onChange={(event) => setConfigForm((current) => ({ ...current, standalone_chat_url: event.target.value }))} />
                </div>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                <div className="text-sm font-semibold text-slate-900">Careers page & social links</div>
                <p className="mt-1 text-sm text-slate-500">These links are displayed on the public careers page for this company.</p>
                <div className="mt-4 grid gap-3 md:grid-cols-3">
                  <input className="input-shell" placeholder="LinkedIn URL" value={configForm.linkedin_url} onChange={(event) => setConfigForm((current) => ({ ...current, linkedin_url: event.target.value }))} />
                  <input className="input-shell" placeholder="Facebook URL" value={configForm.facebook_url} onChange={(event) => setConfigForm((current) => ({ ...current, facebook_url: event.target.value }))} />
                  <input className="input-shell" placeholder="Instagram URL" value={configForm.instagram_url} onChange={(event) => setConfigForm((current) => ({ ...current, instagram_url: event.target.value }))} />
                </div>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                <div className="text-sm font-semibold text-slate-900">Attendance & security policy</div>
                <p className="mt-1 text-sm text-slate-500">Use these rules for allowed check-in sources, geofence defaults, and payroll clearance policy.</p>
                <div className="mt-4 grid gap-3 md:grid-cols-2">
                  <input className="input-shell md:col-span-2" placeholder="Allowed web punch IPs (comma separated)" value={configForm.allowed_web_punch_ips} onChange={(event) => setConfigForm((current) => ({ ...current, allowed_web_punch_ips: event.target.value }))} />
                  <input className="input-shell" placeholder="Default geofence latitude" value={configForm.geofence_latitude} onChange={(event) => setConfigForm((current) => ({ ...current, geofence_latitude: event.target.value }))} />
                  <input className="input-shell" placeholder="Default geofence longitude" value={configForm.geofence_longitude} onChange={(event) => setConfigForm((current) => ({ ...current, geofence_longitude: event.target.value }))} />
                  <input className="input-shell" placeholder="Default geofence radius (m)" value={configForm.geofence_radius_meters} onChange={(event) => setConfigForm((current) => ({ ...current, geofence_radius_meters: event.target.value }))} />
                  <input className="input-shell" placeholder="Late threshold (minutes)" value={configForm.late_arrival_threshold_minutes} onChange={(event) => setConfigForm((current) => ({ ...current, late_arrival_threshold_minutes: event.target.value }))} />
                </div>
                <div className="mt-4 grid gap-3 md:grid-cols-2">
                  <label className="flex items-center gap-2 text-sm text-slate-700">
                    <input type="checkbox" checked={configForm.gps_only_check_in} onChange={(event) => setConfigForm((current) => ({ ...current, gps_only_check_in: event.target.checked }))} />
                    GPS-only check-in
                  </label>
                  <label className="flex items-center gap-2 text-sm text-slate-700">
                    <input type="checkbox" checked={configForm.require_asset_clearance_for_final_payroll} onChange={(event) => setConfigForm((current) => ({ ...current, require_asset_clearance_for_final_payroll: event.target.checked }))} />
                    Require asset clearance for payroll
                  </label>
                </div>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                <div className="text-sm font-semibold text-slate-900">Dashboard visibility</div>
                <p className="mt-1 text-sm text-slate-500">Control whether company-wide analytics and payroll widgets are visible inside this tenant.</p>
                <div className="mt-4 grid gap-3 md:grid-cols-2">
                  <label className="flex items-center gap-2 text-sm text-slate-700">
                    <input type="checkbox" checked={configForm.company_dashboard_enabled} onChange={(event) => setConfigForm((current) => ({ ...current, company_dashboard_enabled: event.target.checked }))} />
                    Company dashboard enabled
                  </label>
                  <label className="flex items-center gap-2 text-sm text-slate-700">
                    <input type="checkbox" checked={configForm.payroll_dashboard_enabled} onChange={(event) => setConfigForm((current) => ({ ...current, payroll_dashboard_enabled: event.target.checked }))} />
                    Payroll dashboard enabled
                  </label>
                </div>
              </div>
            </div>
            <div className="mt-4 grid gap-3 md:grid-cols-2">
              {Object.entries(configForm.dashboard_widget_visibility).map(([key, value]) => (
                <label key={key} className="flex items-center justify-between rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
                  <span>{key}</span>
                  <input
                    type="checkbox"
                    checked={value}
                    onChange={(event) => setConfigForm((current) => ({
                      ...current,
                      dashboard_widget_visibility: {
                        ...current.dashboard_widget_visibility,
                        [key]: event.target.checked
                      }
                    }))}
                  />
                </label>
              ))}
            </div>
            <button type="button" className="primary-btn mt-4" onClick={() => void handleSaveConfig()} disabled={busy}>
              Save Company Policies
            </button>
          </div>

          <div className="space-y-6">
            {canManageMasterModules ? (
              <div className="rounded-2xl border border-slate-200 bg-white p-5">
                <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                  <MonitorCog className="h-4 w-4 text-slate-600" />
                  Master Module Toggles
                </div>
                <p className="mt-2 text-sm text-slate-500">
                  Only the platform superadmin can enable or disable entire modules for this tenant.
                </p>
                <div className="mt-4 grid gap-3 md:grid-cols-2">
                  {Object.entries(subscriptionForm).map(([key, value]) => (
                    <label key={key} className="flex items-center justify-between rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
                      <span>{moduleLabels[key as keyof FeatureFlags]}</span>
                      <input
                        type="checkbox"
                        checked={value}
                        onChange={(event) => setSubscriptionForm((current) => ({ ...current, [key]: event.target.checked }))}
                      />
                    </label>
                  ))}
                </div>
                <button type="button" className="muted-btn mt-4" onClick={() => void handleSaveSubscriptions()} disabled={busy}>
                  Save Master Module Access
                </button>
              </div>
            ) : (
              <div className="rounded-2xl border border-slate-200 bg-white p-5">
                <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                  <MonitorCog className="h-4 w-4 text-slate-600" />
                  Master Module Access
                </div>
                <p className="mt-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
                  Module availability is controlled by the platform superadmin. Tenant admins can manage policies only for modules already enabled for their company.
                </p>
              </div>
            )}

            <div className="rounded-2xl border border-slate-200 bg-white p-5">
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                <Users2 className="h-4 w-4 text-slate-600" />
                Attendance & Leave Policies
              </div>
              <div className="mt-4 grid gap-4">
                {(props.data?.departments ?? []).map((department) => (
                  <div key={department.id} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                    <div className="font-semibold text-slate-900">{department.name}</div>
                    <div className="mt-3 grid gap-3 md:grid-cols-3">
                      <div className="space-y-2">
                        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Schedule managers</p>
                        <select
                          multiple
                          className="input-shell min-h-[132px]"
                          value={scheduleManagerForm[department.id] ?? []}
                          onChange={(event) =>
                            setScheduleManagerForm((current) => ({
                              ...current,
                              [department.id]: Array.from(event.target.selectedOptions, (option) => option.value)
                            }))
                          }
                        >
                          {(props.data?.employees ?? []).map((employee) => (
                            <option key={employee.id} value={employee.id}>
                              {employee.employee_number} - {employee.full_name}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className="space-y-2">
                        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Employee editors</p>
                        <select
                          multiple
                          className="input-shell min-h-[132px]"
                          value={employeeEditorForm[department.id] ?? []}
                          onChange={(event) =>
                            setEmployeeEditorForm((current) => ({
                              ...current,
                              [department.id]: Array.from(event.target.selectedOptions, (option) => option.value)
                            }))
                          }
                        >
                          {(props.data?.employees ?? []).map((employee) => (
                            <option key={employee.id} value={employee.id}>
                              {employee.employee_number} - {employee.full_name}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className="space-y-2">
                        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Leave approver</p>
                        <select
                          className="input-shell"
                          value={leaveApproverForm[department.id] ?? ''}
                          onChange={(event) => setLeaveApproverForm((current) => ({ ...current, [department.id]: event.target.value }))}
                        >
                          <option value="">Fallback approver</option>
                          {(props.data?.employees ?? []).map((employee) => (
                            <option key={employee.id} value={employee.id}>
                              {employee.employee_number} - {employee.full_name}
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>
                  </div>
                ))}
                <div className="grid gap-3 md:grid-cols-2">
                  <input className="input-shell" placeholder="Paid leave allowance" value={leavePolicyForm.paid_leave_allowance_days} onChange={(event) => setLeavePolicyForm((current) => ({ ...current, paid_leave_allowance_days: event.target.value }))} />
                  <input className="input-shell" placeholder="Unpaid leave allowance" value={leavePolicyForm.unpaid_leave_allowance_days} onChange={(event) => setLeavePolicyForm((current) => ({ ...current, unpaid_leave_allowance_days: event.target.value }))} />
                  <input className="input-shell" placeholder="Months before eligible" value={leavePolicyForm.eligibility_months} onChange={(event) => setLeavePolicyForm((current) => ({ ...current, eligibility_months: event.target.value }))} />
                  <select className="input-shell" value={leavePolicyForm.global_leave_approver_employee_id} onChange={(event) => setLeavePolicyForm((current) => ({ ...current, global_leave_approver_employee_id: event.target.value }))}>
                    <option value="">Global approver</option>
                    {(props.data?.employees ?? []).map((employee) => (
                      <option key={employee.id} value={employee.id}>
                        {employee.employee_number} - {employee.full_name}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  <label className="flex items-center gap-2 text-sm text-slate-700">
                    <input type="checkbox" checked={leavePolicyForm.enable_birthday_off} onChange={(event) => setLeavePolicyForm((current) => ({ ...current, enable_birthday_off: event.target.checked }))} />
                    Birthday off
                  </label>
                  <label className="flex items-center gap-2 text-sm text-slate-700">
                    <input type="checkbox" checked={leavePolicyForm.enable_day_off} onChange={(event) => setLeavePolicyForm((current) => ({ ...current, enable_day_off: event.target.checked }))} />
                    Day off
                  </label>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button type="button" className="muted-btn" onClick={() => void handleSaveScheduleManagers()} disabled={busy}>
                    Save Schedule Managers
                  </button>
                  <button type="button" className="muted-btn" onClick={() => void handleSaveEmployeeEditors()} disabled={busy}>
                    Save Employee Editors
                  </button>
                  <button type="button" className="primary-btn" onClick={() => void handleSaveLeavePolicies()} disabled={busy}>
                    Save Leave Policies
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="settings-geo" className="panel-card scroll-mt-6">
        <div className="mb-5 flex items-center gap-3">
          <MapPinned className="h-5 w-5 text-slate-700" />
          <div>
            <p className="section-kicker">Geolocation</p>
            <h2 className="section-title">Worksites & Middleware Keys</h2>
          </div>
        </div>
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(360px,0.8fr)]">
          <div className="rounded-2xl border border-slate-200 bg-white p-5">
            <div className="space-y-3">
              {worksitesForm.map((worksite, index) => (
                <div key={worksite.id ?? `worksite-${index}`} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                  <div className="grid gap-3 md:grid-cols-2">
                    <input className="input-shell" placeholder="Worksite name" value={worksite.name} onChange={(event) => setWorksitesForm((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, name: event.target.value } : item))} />
                    <input className="input-shell" placeholder="Address" value={worksite.address_text} onChange={(event) => setWorksitesForm((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, address_text: event.target.value } : item))} />
                    <input className="input-shell" placeholder="Latitude" value={worksite.latitude} onChange={(event) => setWorksitesForm((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, latitude: event.target.value } : item))} />
                    <input className="input-shell" placeholder="Longitude" value={worksite.longitude} onChange={(event) => setWorksitesForm((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, longitude: event.target.value } : item))} />
                    <input className="input-shell" placeholder="Radius (m)" value={worksite.radius_meters} onChange={(event) => setWorksitesForm((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, radius_meters: event.target.value } : item))} />
                    <label className="flex items-center gap-2 text-sm text-slate-700">
                      <input type="checkbox" checked={worksite.is_active} onChange={(event) => setWorksitesForm((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, is_active: event.target.checked } : item))} />
                      Active
                    </label>
                  </div>
                  {worksiteMapUrl(worksite.latitude, worksite.longitude) ? (
                    <div className="mt-4 overflow-hidden rounded-xl border border-slate-200 bg-white">
                      <iframe
                        title={`Map preview for ${worksite.name || `Worksite ${index + 1}`}`}
                        src={worksiteMapUrl(worksite.latitude, worksite.longitude) ?? undefined}
                        className="h-48 w-full"
                        loading="lazy"
                      />
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <button type="button" className="muted-btn" onClick={() => setWorksitesForm((current) => [...current, { name: '', latitude: '', longitude: '', radius_meters: '150', address_text: '', is_active: true }])}>
                Add Worksite
              </button>
              <button type="button" className="primary-btn" onClick={() => void handleSaveWorksites()} disabled={busy}>
                Save Worksites
              </button>
            </div>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-5">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
              <MonitorCog className="h-4 w-4 text-slate-600" />
              Middleware API Keys
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <input className="input-shell flex-1 min-w-[220px]" value={middlewareKeyName} onChange={(event) => setMiddlewareKeyName(event.target.value)} placeholder="Key name" />
              <button type="button" className="muted-btn" onClick={() => void handleCreateMiddlewareKey()} disabled={busy}>
                Create Key
              </button>
            </div>
            {issuedMiddlewareKey ? (
              <div className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
                <p className="font-semibold">Copy this key now</p>
                <code className="mt-2 block break-all">{issuedMiddlewareKey.api_key}</code>
              </div>
            ) : null}
            <div className="mt-4 space-y-2">
              {(props.data?.middleware_api_keys ?? []).map((item) => (
                <div key={item.id} className="flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
                  <div>
                    <p className="font-semibold text-slate-900">{item.key_name}</p>
                    <p className="text-xs text-slate-500">Last used: {item.last_used_at ?? 'Never'}</p>
                  </div>
                  <button type="button" className="text-xs font-semibold text-rose-600" onClick={() => void props.onRevokeMiddlewareKey(item.id)}>
                    Revoke
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section id="settings-permissions" className="panel-card scroll-mt-6">
        <div className="mb-5 flex items-center gap-3">
          <Shield className="h-5 w-5 text-slate-700" />
          <div>
            <p className="section-kicker">RBAC</p>
            <h2 className="section-title">Access Management</h2>
          </div>
        </div>
        <div className="grid gap-6 xl:grid-cols-[minmax(340px,0.72fr)_minmax(0,1.28fr)]">
          <div className="space-y-6">
            <div className="rounded-2xl border border-slate-200 bg-white p-4">
              <p className="text-xs uppercase tracking-[0.18em] text-slate-400">Roles</p>
              <div className="mt-4 space-y-2">
                {visibleRoles.map((role) => {
                  const active = selectedRoleCode === role.code
                  return (
                    <button
                      key={role.id}
                      type="button"
                      className={`flex w-full items-center justify-between rounded-xl border px-4 py-3 text-left transition ${active ? 'border-slate-900 bg-slate-900 text-white' : 'border-slate-200 bg-slate-50 text-slate-700 hover:bg-slate-100'}`}
                      onClick={() => setSelectedRoleCode(role.code)}
                    >
                      <div>
                        <div className="font-semibold">{role.name_ka || role.name_en}</div>
                        <div className="mt-1 text-xs uppercase tracking-[0.18em] opacity-80">{role.code}</div>
                      </div>
                      <ShieldCheck className="h-4 w-4" />
                    </button>
                  )
                })}
              </div>
            </div>

            <div className="rounded-2xl border border-slate-200 bg-white p-4">
              <p className="text-xs uppercase tracking-[0.18em] text-slate-400">Assign Roles To Employees</p>
              <select className="input-shell mt-4 w-full" value={selectedEmployeeId} onChange={(event) => setSelectedEmployeeId(event.target.value)}>
                <option value="">Select employee</option>
                {(props.data?.employees ?? []).map((employee) => (
                  <option key={employee.id} value={employee.id}>
                    {employee.employee_number} - {employee.full_name}
                  </option>
                ))}
              </select>
              {selectedEmployee ? (
                <div className="mt-4 space-y-3">
                  <p className="font-semibold text-slate-900">{selectedEmployee.full_name}</p>
                  <div className="grid gap-3 md:grid-cols-2">
                    {visibleRoles.map((role) => {
                      const active = selectedEmployee.role_codes.includes(role.code)
                      return (
                        <button key={role.id} type="button" className={`rounded-xl border px-4 py-3 text-left text-sm font-semibold transition ${active ? 'border-slate-900 bg-slate-900 text-white' : 'border-slate-200 bg-slate-50 text-slate-700'}`} onClick={() => void toggleEmployeeRole(role.code)} disabled={busy}>
                          <div>{role.name_ka || role.name_en}</div>
                          <div className="mt-1 text-xs uppercase tracking-[0.18em] opacity-80">{role.code}</div>
                        </button>
                      )
                    })}
                  </div>
                </div>
              ) : (
                <p className="mt-4 text-sm text-slate-500">Pick an employee to assign database roles.</p>
              )}
            </div>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <p className="text-xs uppercase tracking-[0.18em] text-slate-400">Permissions Matrix</p>
                <h3 className="mt-2 text-lg font-semibold text-slate-900">Database Roles</h3>
                <p className="mt-1 text-sm text-slate-500">These checkboxes override role permissions for this tenant and define exactly what each role can do across the enabled modules.</p>
              </div>
              <button type="button" className="primary-btn" onClick={() => void handleSavePrimaryRoleMatrix()} disabled={busy}>
                Save Permissions Matrix
              </button>
            </div>
            <div className="mt-6 overflow-hidden rounded-2xl border border-slate-200">
              <div className="grid bg-slate-900 text-sm font-semibold text-white" style={matrixGridStyle}>
                <div className="px-4 py-3">Permission</div>
                {visibleRoles.map((role) => (
                  <div key={role.code} className="border-l border-white/10 px-4 py-3 text-center">
                    {role.name_ka || role.name_en}
                  </div>
                ))}
              </div>
              <div className="divide-y divide-slate-200 bg-white">
                {permissionMatrixRows.length === 0 ? (
                  <div className="px-4 py-6 text-sm text-slate-500">No data available.</div>
                ) : permissionMatrixRows.map((row) => (
                  <div key={row.permissionCode} className="grid items-center" style={matrixGridStyle}>
                    <div className="px-4 py-3">
                      <div className="text-sm font-semibold text-slate-900">{row.label}</div>
                      <div className="mt-1 text-xs uppercase tracking-[0.16em] text-slate-500">{row.module}</div>
                    </div>
                    {visibleRoles.map((role) => (
                      <label key={`${row.permissionCode}-${role.code}`} className="flex items-center justify-center border-l border-slate-200 px-4 py-3">
                        <input
                          type="checkbox"
                          checked={(rolePermissionMatrix[role.code] ?? []).includes(row.permissionCode)}
                          onChange={() => toggleRolePermission(role.code, row.permissionCode)}
                        />
                      </label>
                    ))}
                  </div>
                ))}
              </div>
            </div>
            {selectedRole ? (
              <div className="mt-5 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
                Focus role: <span className="font-semibold text-slate-900">{selectedRole.name_ka || selectedRole.name_en}</span>
              </div>
            ) : null}
          </div>
        </div>
      </section>
    </section>
  )
}
