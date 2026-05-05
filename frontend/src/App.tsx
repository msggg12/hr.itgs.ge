import type { CSSProperties } from 'react'
import { useDeferredValue, useEffect, useMemo, useState } from 'react'

import { Fingerprint, Menu } from 'lucide-react'

import { deleteJson, downloadFile, getJson, login, logout, postForm, postJson, putJson, readToken, type LoginResponse, writeTokens } from './api'
import { AtsBoard } from './components/AtsBoard'
import { AttendanceModal } from './components/AttendanceModal'
import { AttendanceHub } from './components/AttendanceHub'
import { CelebrationWidget } from './components/CelebrationWidget'
import { ConfirmActionModal } from './components/ConfirmActionModal'
import { DashboardActionPanel } from './components/DashboardActionPanel'
import { DeviceRegistryPanel } from './components/DeviceRegistryPanel'
import { EmployeeDrawer } from './components/EmployeeDrawer'
import { EmployeeGrid } from './components/EmployeeGrid'
import { HardwareSyncModal } from './components/HardwareSyncModal'
import { IntegrationsPanel } from './components/IntegrationsPanel'
import { LeaveCalculator } from './components/LeaveCalculator'
import { LiveFeed } from './components/LiveFeed'
import { MessageComposerModal } from './components/MessageComposerModal'
import { MetricCards } from './components/MetricCards'
import { OrgChartPanel } from './components/OrgChartPanel'
import { PayrollHub } from './components/PayrollHub'
import { PersonalReportsPanel } from './components/PersonalReportsPanel'
import { PerformanceHub } from './components/PerformanceHub'
import { PublicCareers } from './components/PublicCareers'
import { SettingsCategorizedLayout } from './components/SettingsCategorizedLayout'
import { Sidebar } from './components/Sidebar'
import { ToastStack, type ToastItem } from './components/ToastStack'
import { SystemConfigPanel } from './components/SystemConfigPanel'
import { SupportPanel } from './components/SupportPanel'
import { UpcomingSchedulePanel } from './components/UpcomingSchedulePanel'
import { TeamChat } from './components/TeamChat'
import { VacancyManager } from './components/VacancyManager'
import { WarehousePanel } from './components/WarehousePanel'
import { ka } from './i18n/ka'
import { resolveTenantBranding } from './tenantBranding'
import type {
  AnalyticsOverview,
  AtsCard,
  AtsBoardData,
  AttendanceHubData,
  AttendanceHistoryItem,
  AttendanceMultiPointEntry,
  BootstrapData,
  CelebrationHubData,
  DashboardSummary,
  DeviceRegistryData,
  EmployeeDraft,
  EmployeeFormOptions,
  FeatureFlags,
  FeedEvent,
  GridItem,
  GridResponse,
  IntegrationOverview,
  LeaveSelfServiceData,
  MessageChannel,
  OptionItem,
  OrgChartData,
  PayrollHubData,
  PersonalReportsData,
  PerformanceHubData,
  ShiftAssignment,
  ShiftPlannerData,
  SystemConfigData,
  TeamChatConfig,
  UpcomingScheduleData,
  VacancyData,
  WebPunchConfigData,
  WarehouseData,
  WeeklyAttendancePoint,
  WidgetData
} from './types'
import { classNames, defaultDraft, findShiftSegment } from './utils'

function formatDuration(seconds: number): string {
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const secs = seconds % 60
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`
}

type LoginState = {
  username: string
  password: string
}

type InvitePreview = {
  status: string
  username: string
  email: string | null
  full_name: string
  department_name: string | null
  job_role_title: string | null
  manager_name: string | null
  expires_at: string | null
}

type PasswordResetPreview = {
  status: string
  email: string | null
  full_name: string
  expires_at: string | null
}

type EmployeeInviteResult = {
  employee_id: string
  username: string
  invite_link: string
  invite_email_status: 'sent' | 'failed' | 'not_configured'
  invite_email_error?: string | null
}

type EmployeeDetail = {
  id: string
  legal_entity_id: string
  employee_number: string
  personal_number: string | null
  first_name: string
  last_name: string
  email: string | null
  mobile_phone: string | null
  hire_date: string
  department_id: string | null
  job_role_id: string | null
  manager_employee_id: string | null
  manager_name: string | null
  profile_photo_url: string | null
  default_device_user_id: string | null
  pay_policy_id: string | null
  salary_type: string | null
  base_salary: string | null
  hourly_rate_override: string | null
  is_pension_participant: boolean
  synced_devices?: OptionItem[]
  permissions?: {
    can_edit: boolean
    can_view_salary: boolean
  }
}

type PendingEmployeeAction = {
  kind: 'deactivate' | 'delete'
  employee: GridItem
}

type AuthMe = {
  employee_id: string
  legal_entity_id: string
  department_id: string | null
  role_codes: string[]
  permissions: string[]
  managed_department_ids: string[]
}

type AppSection = 'dashboard' | 'employees' | 'attendance' | 'leave' | 'payroll' | 'ats' | 'assets' | 'org_chart' | 'okrs' | 'team_chat' | 'settings' | 'integrations' | 'support'

const sectionCopy: Record<AppSection, { title: string; subtitle: string }> = {
  dashboard: { title: ka.dashboard, subtitle: ka.employeeHub },
  employees: { title: ka.employeeManagement, subtitle: ka.employeeHub },
  attendance: { title: ka.attendance, subtitle: ka.sectionAttendance },
  leave: { title: ka.leaveHub, subtitle: ka.requestLeave },
  payroll: { title: ka.payroll, subtitle: ka.sectionPayroll },
  ats: { title: ka.ats, subtitle: ka.sectionAts },
  assets: { title: ka.assets, subtitle: ka.sectionAssets },
  org_chart: { title: 'ორგსტრუქტურა', subtitle: 'უშუალო მენეჯერები და დამტკიცების იერარქია' },
  okrs: { title: ka.okrs, subtitle: ka.sectionOkrs },
  team_chat: { title: ka.teamChat, subtitle: ka.linkedAs },
  settings: { title: ka.settings, subtitle: ka.sectionSettings },
  integrations: { title: 'Apps & Integrations', subtitle: 'Connected work apps, calendar, messaging, and delivery channels' },
  support: { title: 'Help & Support', subtitle: 'Support tools, rollout notes, and admin guidance' }
}

function readAuthQueryToken(key: 'invite_token' | 'reset_token'): string {
  if (typeof window === 'undefined') {
    return ''
  }
  return new URLSearchParams(window.location.search).get(key) ?? ''
}

function clearAuthQueryTokens(): void {
  if (typeof window === 'undefined') {
    return
  }
  const url = new URL(window.location.href)
  url.searchParams.delete('invite_token')
  url.searchParams.delete('reset_token')
  window.history.replaceState({}, '', `${url.pathname}${url.search}`)
}

function shiftDateByMonths(baseDate: string, delta: number): string {
  const value = new Date(`${baseDate}T00:00:00`)
  value.setMonth(value.getMonth() + delta, 1)
  return value.toISOString().slice(0, 10)
}

function weekBucketKey(shiftDate: string): string {
  const value = new Date(`${shiftDate}T00:00:00`)
  const offset = (value.getDay() + 6) % 7
  value.setDate(value.getDate() - offset)
  return value.toISOString().slice(0, 10)
}

function manualShiftDuration(startTime: string, endTime: string): { plannedMinutes: number; crossesMidnight: boolean } | null {
  if (!startTime || !endTime) {
    return null
  }
  const [startHour, startMinute] = startTime.split(':').map((value) => Number.parseInt(value, 10))
  const [endHour, endMinute] = endTime.split(':').map((value) => Number.parseInt(value, 10))
  if ([startHour, startMinute, endHour, endMinute].some((value) => Number.isNaN(value))) {
    return null
  }
  let startTotal = startHour * 60 + startMinute
  let endTotal = endHour * 60 + endMinute
  let crossesMidnight = false
  if (endTotal <= startTotal) {
    endTotal += 24 * 60
    crossesMidnight = true
  }
  const plannedMinutes = endTotal - startTotal
  if (plannedMinutes <= 0 || plannedMinutes > 24 * 60) {
    return null
  }
  return { plannedMinutes, crossesMidnight }
}

function endTimeFromStartAndMinutes(startTime: string, plannedMinutes: number): string {
  const [startHour, startMinute] = startTime.split(':').map((value) => Number.parseInt(value, 10))
  if ([startHour, startMinute].some((value) => Number.isNaN(value))) {
    return startTime
  }
  const totalMinutes = (startHour * 60 + startMinute + plannedMinutes) % (24 * 60)
  const hour = Math.floor(totalMinutes / 60)
  const minute = totalMinutes % 60
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`
}

function summarizeWeeklyMinutes(assignments: ShiftAssignment[], employeeId: string): {
  weeklyMinutesMap: Record<string, number>
  maxWeeklyMinutes: number
} {
  const weeklyMinutesMap = assignments
    .filter((item) => item.employee_id === employeeId)
    .reduce<Record<string, number>>((acc, item) => {
      const key = weekBucketKey(item.shift_date)
      acc[key] = (acc[key] ?? 0) + item.planned_minutes
      return acc
    }, {})
  const maxWeeklyMinutes = Math.max(0, ...Object.values(weeklyMinutesMap))
  return { weeklyMinutesMap, maxWeeklyMinutes }
}

function rgbFromHex(hex: string): string {
  const normalized = hex.replace('#', '')
  if (normalized.length !== 6) {
    return '26 34 56'
  }
  const red = Number.parseInt(normalized.slice(0, 2), 16)
  const green = Number.parseInt(normalized.slice(2, 4), 16)
  const blue = Number.parseInt(normalized.slice(4, 6), 16)
  return `${red} ${green} ${blue}`
}

function moveCandidateLocally(current: AtsBoardData | null, applicationId: string, targetStage: string): AtsBoardData | null {
  if (!current) {
    return current
  }
  let movedCard: AtsCard | null = null
  const nextCards: AtsBoardData['cards'] = {}
  for (const column of current.columns) {
    nextCards[column.code] = (current.cards[column.code] ?? []).filter((card) => {
      if (card.id === applicationId) {
        movedCard = { ...card, stage_code: targetStage }
        return false
      }
      return true
    })
  }
  if (!movedCard) {
    return current
  }
  nextCards[targetStage] = [
    { ...movedCard, stage_code: targetStage },
    ...(nextCards[targetStage] ?? [])
  ]
  return { ...current, cards: nextCards }
}

function updateShiftPlannerLocally(
  current: ShiftPlannerData | null,
  employeeId: string,
  payload: {
    shiftPatternId?: string | null
    shiftDate: string
    startTime?: string
    endTime?: string
  }
): ShiftPlannerData | null {
  if (!current) {
    return current
  }
  const nextAssignments = current.assignments.filter((item) => !(item.employee_id === employeeId && item.shift_date === payload.shiftDate))
  let assignment: ShiftAssignment | null = null
  if (payload.startTime && payload.endTime) {
    const manualTiming = manualShiftDuration(payload.startTime, payload.endTime)
    if (!manualTiming) {
      return current
    }
    assignment = {
      assignment_id: `${employeeId}-${payload.shiftDate}-custom`,
      employee_id: employeeId,
      shift_date: payload.shiftDate,
      shift_pattern_id: payload.shiftPatternId ?? 'custom',
      pattern_name: `Custom ${payload.startTime}-${payload.endTime}`,
      pattern_code: 'CUSTOM',
      planned_minutes: manualTiming.plannedMinutes,
      start_time: payload.startTime,
      end_time: payload.endTime,
      break_minutes: 0,
      crosses_midnight: manualTiming.crossesMidnight,
      label: 'Custom shift',
      is_custom: true,
    }
  } else {
    const pattern = current.patterns.find((item) => item.id === payload.shiftPatternId)
    const segment = findShiftSegment(pattern, payload.shiftDate)
    if (!pattern || !segment) {
      return current
    }
    assignment = {
      assignment_id: `${employeeId}-${payload.shiftDate}-${payload.shiftPatternId}`,
      employee_id: employeeId,
      shift_date: payload.shiftDate,
      shift_pattern_id: payload.shiftPatternId ?? '',
      pattern_name: pattern.name,
      pattern_code: pattern.code,
      planned_minutes: segment.planned_minutes,
      start_time: segment.start_time,
      end_time: endTimeFromStartAndMinutes(segment.start_time, segment.planned_minutes),
      break_minutes: segment.break_minutes,
      crosses_midnight: segment.crosses_midnight,
      label: segment.label ?? pattern.name,
      is_custom: false,
    }
  }
  nextAssignments.push(assignment)
  const nextEmployees = current.employees.map((employee) => {
    if (employee.id !== employeeId) {
      return employee
    }
    const { weeklyMinutesMap, maxWeeklyMinutes } = summarizeWeeklyMinutes(nextAssignments, employeeId)
    return { ...employee, weekly_minutes: maxWeeklyMinutes, weekly_minutes_map: weeklyMinutesMap }
  })
  return { ...current, assignments: nextAssignments, employees: nextEmployees }
}

function clearShiftLocally(current: ShiftPlannerData | null, employeeId: string, shiftDate: string): ShiftPlannerData | null {
  if (!current) {
    return current
  }
  const nextAssignments = current.assignments.filter((item) => !(item.employee_id === employeeId && item.shift_date === shiftDate))
  const nextEmployees = current.employees.map((employee) => {
    if (employee.id !== employeeId) {
      return employee
    }
    const { weeklyMinutesMap, maxWeeklyMinutes } = summarizeWeeklyMinutes(nextAssignments, employeeId)
    return { ...employee, weekly_minutes: maxWeeklyMinutes, weekly_minutes_map: weeklyMinutesMap }
  })
  return { ...current, assignments: nextAssignments, employees: nextEmployees }
}

export function App() {
  const fallbackBranding = resolveTenantBranding()
  const [token, setToken] = useState(readToken())
  const [activeSection, setActiveSection] = useState<AppSection>('dashboard')
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const [emailFilter, setEmailFilter] = useState('')
  const [phoneFilter, setPhoneFilter] = useState('')
  const [departmentFilter, setDepartmentFilter] = useState('')
  const [loginState, setLoginState] = useState<LoginState>({ username: '', password: '' })
  const [forgotUsernameOrEmail, setForgotUsernameOrEmail] = useState('')
  const [inviteToken, setInviteToken] = useState(() => readAuthQueryToken('invite_token'))
  const [resetToken, setResetToken] = useState(() => readAuthQueryToken('reset_token'))
  const [authScreen, setAuthScreen] = useState<'login' | 'forgot' | 'invite' | 'reset'>(() => {
    if (readAuthQueryToken('invite_token')) {
      return 'invite'
    }
    if (readAuthQueryToken('reset_token')) {
      return 'reset'
    }
    return 'login'
  })
  const [authBusy, setAuthBusy] = useState(false)
  const [authError, setAuthError] = useState('')
  const [authNotice, setAuthNotice] = useState('')
  const [invitePreview, setInvitePreview] = useState<InvitePreview | null>(null)
  const [resetPreview, setResetPreview] = useState<PasswordResetPreview | null>(null)
  const [inviteRegistration, setInviteRegistration] = useState({
    personalNumber: '',
    mobilePhone: '',
    password: '',
    confirmPassword: '',
    profilePhoto: null as File | null
  })
  const [resetPasswordState, setResetPasswordState] = useState({
    password: '',
    confirmPassword: ''
  })
  const [bootstrap, setBootstrap] = useState<BootstrapData | null>(null)
  const [currentUser, setCurrentUser] = useState<AuthMe | null>(null)
  const [summary, setSummary] = useState<WidgetData['summary'] | null>(null)
  const [grid, setGrid] = useState<GridResponse | null>(null)
  const [options, setOptions] = useState<EmployeeFormOptions | null>(null)
  const [feed, setFeed] = useState<FeedEvent[]>([])
  const [multiPointSummary, setMultiPointSummary] = useState<AttendanceMultiPointEntry[]>([])
  const [analytics, setAnalytics] = useState<AnalyticsOverview | null>(null)
  const [atsBoard, setAtsBoard] = useState<AtsBoardData | null>(null)
  const [shiftPlanner, setShiftPlanner] = useState<ShiftPlannerData | null>(null)
  const [attendanceHub, setAttendanceHub] = useState<AttendanceHubData | null>(null)
  const [celebrationData, setCelebrationData] = useState<CelebrationHubData | null>(null)
  const [leaveData, setLeaveData] = useState<LeaveSelfServiceData | null>(null)
  const [teamChatConfig, setTeamChatConfig] = useState<TeamChatConfig | null>(null)
  const [webPunchData, setWebPunchData] = useState<WebPunchConfigData | null>(null)
  const [vacancyData, setVacancyData] = useState<VacancyData | null>(null)
  const [warehouseData, setWarehouseData] = useState<WarehouseData | null>(null)
  const [weeklyAttendance, setWeeklyAttendance] = useState<WeeklyAttendancePoint[]>([])
  const [upcomingSchedule, setUpcomingSchedule] = useState<UpcomingScheduleData | null>(null)
  const [dashboardSummary, setDashboardSummary] = useState<DashboardSummary | null>(null)
  const [integrationsOverview, setIntegrationsOverview] = useState<IntegrationOverview | null>(null)
  const [integrationBusy, setIntegrationBusy] = useState(false)
  const [messageTarget, setMessageTarget] = useState<{ employeeId: string; employeeName: string } | null>(null)
  const [messageSending, setMessageSending] = useState(false)
  const [topElapsedSeconds, setTopElapsedSeconds] = useState(0)
  const topPunchSummary = webPunchData?.status_summary ?? null
  const isTopCheckedIn = topPunchSummary?.is_checked_in ?? false
  const topCheckInTime = useMemo(
    () => (isTopCheckedIn && topPunchSummary?.current_segment_started_at ? new Date(topPunchSummary.current_segment_started_at) : null),
    [isTopCheckedIn, topPunchSummary?.current_segment_started_at],
  )
  const topWebPunchButtonLabel = isTopCheckedIn ? 'Web Check-Out' : 'Web Check-In'
  const [performanceHub, setPerformanceHub] = useState<PerformanceHubData | null>(null)

  useEffect(() => {
    if (!topCheckInTime) {
      setTopElapsedSeconds(0)
      return undefined
    }

    const updateTopElapsed = () => {
      setTopElapsedSeconds(Math.max(0, Math.floor((Date.now() - topCheckInTime.getTime()) / 1000)))
    }

    updateTopElapsed()
    const timer = window.setInterval(updateTopElapsed, 1000)
    return () => window.clearInterval(timer)
  }, [topCheckInTime])
  const [payrollHub, setPayrollHub] = useState<PayrollHubData | null>(null)
  const [payrollMonth, setPayrollMonth] = useState(() => {
    const today = new Date()
    return `${today.getFullYear()}-${`${today.getMonth() + 1}`.padStart(2, '0')}`
  })
  const [payrollDepartmentId, setPayrollDepartmentId] = useState('')
  const [systemConfig, setSystemConfig] = useState<SystemConfigData | null>(null)
  const [deviceRegistry, setDeviceRegistry] = useState<DeviceRegistryData | null>(null)
  const [orgChart, setOrgChart] = useState<OrgChartData | null>(null)
  const [personalReports, setPersonalReports] = useState<PersonalReportsData | null>(null)
  const [search, setSearch] = useState('')
  const deferredSearch = useDeferredValue(search)
  const [statusFilter, setStatusFilter] = useState('')
  const [sortBy, setSortBy] = useState<'employee_number' | 'full_name' | 'department_name' | 'job_title' | 'employment_status' | 'hire_date'>('employee_number')
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('asc')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(12)
  const [attendanceDepartmentId, setAttendanceDepartmentId] = useState('')
  const [shiftMonthStart, setShiftMonthStart] = useState(() => {
    const today = new Date()
    today.setDate(1)
    return today.toISOString().slice(0, 10)
  })
  const [busy, setBusy] = useState(false)
  const [atsBusy, setAtsBusy] = useState(false)
  const [attendanceImportBusy, setAttendanceImportBusy] = useState(false)
  const [importBusy, setImportBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [drawerMode, setDrawerMode] = useState<'create' | 'edit'>('create')
  const [drawerTab, setDrawerTab] = useState<'personal' | 'salary' | 'device'>('personal')
  const [draft, setDraft] = useState<EmployeeDraft>(defaultDraft(null))
  const [draftPhoto, setDraftPhoto] = useState<File | null>(null)
  const [drawerSyncedDevices, setDrawerSyncedDevices] = useState<OptionItem[]>([])
  const [employeeInviteResult, setEmployeeInviteResult] = useState<EmployeeInviteResult | null>(null)
  const [attendanceOpen, setAttendanceOpen] = useState(false)
  const [attendanceEmployeeName, setAttendanceEmployeeName] = useState('')
  const [attendanceRows, setAttendanceRows] = useState<AttendanceHistoryItem[]>([])
  const [syncOpen, setSyncOpen] = useState(false)
  const [syncEmployee, setSyncEmployee] = useState<GridItem | null>(null)
  const [selectedDeviceIds, setSelectedDeviceIds] = useState<string[]>([])
  const [pendingEmployeeAction, setPendingEmployeeAction] = useState<PendingEmployeeAction | null>(null)
  const [employeeActionBusy, setEmployeeActionBusy] = useState(false)
  const featureFlags: FeatureFlags = bootstrap?.tenant.feature_flags ?? {
    attendance_enabled: true,
    payroll_enabled: true,
    ats_enabled: true,
    chat_enabled: true,
    device_management_enabled: true,
    mobile_sync_enabled: true,
    assets_enabled: true,
    org_chart_enabled: true,
    performance_enabled: true
  }
  const uiPolicies = bootstrap?.tenant.ui_policies ?? {
    gps_only_check_in: false,
    company_dashboard_enabled: true,
    payroll_dashboard_enabled: true,
    dashboard_widget_visibility: {
      summary_cards: true,
      analytics: true,
      live_feed: true,
      action_center: true,
      upcoming_schedule: true,
      celebrations: true
    }
  }
  const branding = {
    companyName: bootstrap?.tenant.trade_name ?? fallbackBranding.companyName,
    logoText: bootstrap?.tenant.logo_text ?? fallbackBranding.logoText,
    primaryColor: bootstrap?.tenant.primary_color ?? fallbackBranding.primaryColor,
    primaryRgb: rgbFromHex(bootstrap?.tenant.primary_color ?? fallbackBranding.primaryColor)
  }
  const employeePermissions = currentUser?.permissions ?? []
  const adminMode = Boolean(currentUser?.permissions?.includes('employee.manage') || currentUser?.role_codes?.includes('ADMIN'))
  const canAccessEmployees = Boolean(
    employeePermissions.includes('employee.directory.read')
      || employeePermissions.includes('employee.read_department')
      || employeePermissions.includes('employee.edit')
      || employeePermissions.includes('employee.manage')
      || currentUser?.role_codes?.includes('ADMIN')
  )
  const canEditEmployees = Boolean(
    employeePermissions.includes('employee.edit')
      || employeePermissions.includes('employee.manage')
      || currentUser?.role_codes?.includes('ADMIN')
  )
  const canAccessAttendance = Boolean(
    employeePermissions.includes('attendance.read_self')
      || employeePermissions.includes('attendance.read_department')
      || employeePermissions.includes('attendance.read_all')
      || employeePermissions.includes('attendance.review')
      || employeePermissions.includes('employee.manage')
      || currentUser?.role_codes?.includes('ADMIN')
  )
  const canAccessPayroll = Boolean(
    uiPolicies.payroll_dashboard_enabled && (
      employeePermissions.includes('payroll.export')
      || currentUser?.role_codes?.includes('ADMIN')
    )
  )
  const canAccessRecruitment = Boolean(
    employeePermissions.includes('recruitment.read')
      || employeePermissions.includes('recruitment.manage')
      || currentUser?.role_codes?.includes('ADMIN')
  )
  const canAccessSettings = Boolean(
    employeePermissions.includes('settings.manage')
      || currentUser?.role_codes?.includes('ADMIN')
  )
  const canAccessAssets = Boolean(
    employeePermissions.includes('assets.read_all')
      || employeePermissions.includes('assets.manage')
      || currentUser?.role_codes?.includes('ADMIN')
  )
  const canAccessCompanyDashboard = Boolean(
    uiPolicies.company_dashboard_enabled && (
      employeePermissions.includes('attendance.read_department')
      || employeePermissions.includes('attendance.read_all')
      || employeePermissions.includes('attendance.review')
      || employeePermissions.includes('employee.manage')
      || (currentUser?.managed_department_ids?.length ?? 0) > 0
      || currentUser?.role_codes?.includes('ADMIN')
    )
  )
  const canManageRecruitment = Boolean(
    employeePermissions.includes('recruitment.manage')
      || currentUser?.role_codes?.includes('ADMIN')
  )
  const canManageAttendance = Boolean(
    employeePermissions.includes('attendance.review')
      || employeePermissions.includes('employee.manage')
      || (currentUser?.managed_department_ids?.length ?? 0) > 0
      || currentUser?.role_codes?.includes('ADMIN')
  )
  const selfServiceOnly =
    !adminMode
    && !canAccessEmployees
    && !employeePermissions.includes('attendance.read_department')
    && !employeePermissions.includes('attendance.read_all')
    && !canAccessRecruitment
  const allowedSections: AppSection[] = adminMode
    ? [
        'dashboard',
        'employees',
        'attendance',
        'leave',
        ...(canAccessPayroll ? ['payroll' as const] : []),
        ...(canAccessRecruitment ? ['ats' as const] : []),
        ...(canAccessAssets ? ['assets' as const] : []),
        'org_chart',
        'okrs',
        'team_chat',
        ...(canAccessSettings ? ['settings' as const] : []),
        'integrations',
        'support'
      ]
    : selfServiceOnly
      ? [...(canAccessAttendance ? ['attendance' as const] : []), 'leave', ...(featureFlags.chat_enabled ? ['team_chat' as const] : [])]
      : ['dashboard', ...(canAccessEmployees ? ['employees' as const] : []), ...(canAccessAttendance ? ['attendance' as const] : []), ...(canAccessPayroll ? ['payroll' as const] : []), ...(canAccessRecruitment ? ['ats' as const] : []), 'leave', 'integrations', 'support', ...(featureFlags.chat_enabled ? ['team_chat' as const] : [])]
  const visibleSections = allowedSections.filter((section) => {
    const featureMap: Partial<Record<AppSection, boolean>> = {
      attendance: featureFlags.attendance_enabled,
      payroll: featureFlags.payroll_enabled,
      ats: featureFlags.ats_enabled,
      assets: featureFlags.assets_enabled,
      org_chart: featureFlags.org_chart_enabled,
      okrs: featureFlags.performance_enabled,
      team_chat: featureFlags.chat_enabled
    }
    return featureMap[section] ?? true
  })
  useEffect(() => {
    if (visibleSections.length === 0) {
      return
    }
    if (!visibleSections.includes(activeSection)) {
      setActiveSection(visibleSections[0])
    }
  }, [activeSection, visibleSections])

  const employeeGridPermissions = grid?.permissions ?? {
    can_create: adminMode,
    can_create_department: adminMode,
    can_edit: canEditEmployees,
    can_view_salary: employeePermissions.includes('compensation.read_all') || adminMode,
    can_import: employeePermissions.includes('employee.import') || adminMode,
    can_export: employeePermissions.includes('employee.export') || adminMode,
    can_grant_access: adminMode,
    can_sync_devices: featureFlags.device_management_enabled && (employeePermissions.includes('device.manage') || adminMode),
    can_view_attendance: employeePermissions.includes('attendance.read_all') || employeePermissions.includes('attendance.read_department') || adminMode,
    can_offboard: adminMode,
    can_delete: adminMode,
  }
  const employeeFormPermissions = options?.permissions ?? {
    can_edit: canEditEmployees,
    can_view_salary: employeeGridPermissions.can_view_salary,
    can_sync_devices: employeeGridPermissions.can_sync_devices,
    can_create_department: employeeGridPermissions.can_create_department,
  }
  const availableMessageChannels = useMemo<MessageChannel[]>(() => {
    const channels: MessageChannel[] = []
    if (integrationsOverview?.slack.connected) {
      channels.push('slack')
    }
    if (integrationsOverview?.email.connected) {
      channels.push('email')
    }
    return channels
  }, [integrationsOverview])
  const topBarDate = new Intl.DateTimeFormat('ka-GE', {
    weekday: 'short',
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  }).format(new Date())
  const topBarRole = currentUser?.role_codes?.[0] ?? 'EMPLOYEE'
  const pendingEmployeeName = pendingEmployeeAction ? `${pendingEmployeeAction.employee.first_name} ${pendingEmployeeAction.employee.last_name}`.trim() : ''
  const employeeActionCopy = pendingEmployeeAction?.kind === 'delete'
    ? {
        title: 'Confirm Delete',
        body: `Are you sure you want to delete/archive ${pendingEmployeeName}? This will remove the employee from active lists, revoke web access immediately, and keep all historical records.`,
        confirmLabel: 'Delete',
        tone: 'danger' as const,
      }
    : {
        title: 'Confirm Deactivation',
        body: `Are you sure you want to deactivate/offboard ${pendingEmployeeName}? This will revoke web access immediately and keep all historical records.`,
        confirmLabel: 'Deactivate',
        tone: 'warning' as const,
      }

  async function loadBootstrap() {
    setBootstrap(await getJson<BootstrapData>('/ux/bootstrap'))
  }

  async function loadEmployeeFormOptions() {
    const formOptions = await getJson<EmployeeFormOptions>('/ux/employee-form-options')
    setOptions(formOptions)
    return formOptions
  }

  async function loadWebPunchData() {
    const webPunch = await getJson<WebPunchConfigData>('/ux/web-punch-config')
    setWebPunchData(webPunch)
    return webPunch
  }

  function applyHomeData(homeData: WidgetData) {
    setSummary(homeData.summary)
    setWeeklyAttendance(homeData.weekly_attendance)
    setUpcomingSchedule(homeData.upcoming_schedule)
  }

  async function loadHomePanels() {
    const homeData = await getJson<WidgetData>('/ux/home-data')
    applyHomeData(homeData)
    return homeData
  }

  async function loadIntegrationOverview() {
    const overview = await getJson<IntegrationOverview>('/integrations/overview')
    setIntegrationsOverview(overview)
    return overview
  }

  async function loadDashboardSummary() {
    if (!canAccessCompanyDashboard) {
      setDashboardSummary(null)
      return null
    }
    const summaryData = await getJson<DashboardSummary>('/dashboard/summary')
    setDashboardSummary(summaryData)
    return summaryData
  }

  async function loadStaticPanels(config?: {
    includePayroll?: boolean
    canAccessRecruitment?: boolean
    canAccessAssets?: boolean
    canAccessSettings?: boolean
    canAccessCompanyDashboard?: boolean
    canManageDevices?: boolean
  }) {
    const includePayroll = config?.includePayroll ?? canAccessPayroll
    const includeRecruitment = config?.canAccessRecruitment ?? canAccessRecruitment
    const includeAssets = config?.canAccessAssets ?? canAccessAssets
    const includeSettingsPanel = config?.canAccessSettings ?? canAccessSettings
    const includeCompanyDashboard = config?.canAccessCompanyDashboard ?? canAccessCompanyDashboard
    const includeDeviceRegistry = config?.canManageDevices ?? (featureFlags.device_management_enabled && (canAccessSettings || employeePermissions.includes('device.manage')))
    const [
      bootstrapData,
      _homeData,
      formOptions,
      analyticsData,
      atsData,
      celebrationHub,
      leaveSelfService,
      teamChat,
      webPunch,
      vacancies,
      warehouse,
      performanceData,
      payrollData,
      systemConfigData,
      deviceRegistryData,
      orgChartData,
      personalReportsData,
      overview,
      dashboardSummaryData
    ] = await Promise.all([
      getJson<BootstrapData>('/ux/bootstrap'),
      loadHomePanels(),
      loadEmployeeFormOptions(),
      includeCompanyDashboard ? getJson<AnalyticsOverview>('/ux/analytics-overview') : Promise.resolve(null),
      includeRecruitment ? getJson<AtsBoardData>('/ux/ats-board') : Promise.resolve(null),
      getJson<CelebrationHubData>('/ux/celebration-hub'),
      getJson<LeaveSelfServiceData>('/ux/leave-self-service'),
      getJson<TeamChatConfig>('/ux/team-chat-config'),
      getJson<WebPunchConfigData>('/ux/web-punch-config'),
      includeRecruitment ? getJson<VacancyData>('/ux/vacancies') : Promise.resolve(null),
      includeAssets ? getJson<WarehouseData>('/ux/warehouse') : Promise.resolve(null),
      getJson<PerformanceHubData>('/ux/performance-hub'),
      includePayroll ? getJson<PayrollHubData>('/ux/payroll-hub') : Promise.resolve(null),
      includeSettingsPanel ? getJson<SystemConfigData>('/ux/system-config') : Promise.resolve(null),
      includeDeviceRegistry
        ? getJson<DeviceRegistryData>('/ux/device-registry')
        : Promise.resolve(null),
      getJson<OrgChartData>('/ux/org-chart'),
      getJson<PersonalReportsData>('/ux/personal-reports'),
      loadIntegrationOverview(),
      includeCompanyDashboard ? getJson<DashboardSummary>('/dashboard/summary') : Promise.resolve(null)
    ])
    setBootstrap(bootstrapData)
    setAnalytics(analyticsData)
    setAtsBoard(atsData)
    setCelebrationData(celebrationHub)
    setLeaveData(leaveSelfService)
    setTeamChatConfig(teamChat)
    setWebPunchData(webPunch)
    setVacancyData(vacancies)
    setWarehouseData(warehouse)
    setPerformanceHub(performanceData)
    setPayrollHub(payrollData)
    setSystemConfig(systemConfigData)
    setDeviceRegistry(deviceRegistryData)
    setOrgChart(orgChartData)
    setPersonalReports(personalReportsData)
    setIntegrationsOverview(overview)
    setDashboardSummary(dashboardSummaryData)
    setDraft((current) => (current.legal_entity_id ? current : defaultDraft(formOptions)))
  }

  async function loadSelfServicePanels() {
    const [bootstrapData, _homeData, leaveSelfService, teamChat, personalReportsData, overview, webPunch] = await Promise.all([
      getJson<BootstrapData>('/ux/bootstrap'),
      loadHomePanels(),
      getJson<LeaveSelfServiceData>('/ux/leave-self-service'),
      getJson<TeamChatConfig>('/ux/team-chat-config'),
      getJson<PersonalReportsData>('/ux/personal-reports'),
      loadIntegrationOverview(),
      loadWebPunchData()
    ])
    setBootstrap(bootstrapData)
    setLeaveData(leaveSelfService)
    setTeamChatConfig(teamChat)
    setPersonalReports(personalReportsData)
    setIntegrationsOverview(overview)
    setWebPunchData(webPunch)
    setGrid(null)
    setOptions(null)
    setFeed([])
  }

  async function loadLivePanels(force = false) {
    if (!force && !canAccessCompanyDashboard) {
      setFeed([])
      setMultiPointSummary([])
      return
    }
    const [liveFeed, multiPoint] = await Promise.all([
      getJson<FeedEvent[]>('/ux/attendance-live-feed'),
      getJson<AttendanceMultiPointEntry[]>('/ux/attendance-multi-point-summary').catch(() => [] as AttendanceMultiPointEntry[]),
    ])
    setFeed(liveFeed)
    setMultiPointSummary(multiPoint)
  }

  async function loadAtsBoard() {
    setAtsBusy(true)
    try {
      setAtsBoard(await getJson<AtsBoardData>('/ux/ats-board'))
    } finally {
      setAtsBusy(false)
    }
  }

  async function loadShiftPlanner() {
    setShiftPlanner(await getJson<ShiftPlannerData>('/ux/shift-planner', {
      month_start: shiftMonthStart,
      department_id: attendanceDepartmentId || null,
      page_size: 8
    }))
  }

  async function loadAttendanceHubData(selectedDepartmentId?: string | null) {
    const hub = await getJson<AttendanceHubData>('/ux/attendance-hub', {
      month_start: shiftMonthStart,
      department_id: selectedDepartmentId || attendanceDepartmentId || null,
    })
    setAttendanceHub(hub)
    const resolvedDepartmentId = hub.selected_department_id ?? ''
    if (resolvedDepartmentId !== attendanceDepartmentId) {
      setAttendanceDepartmentId(resolvedDepartmentId)
    }
    return hub
  }

  async function loadVacancyData() {
    setVacancyData(await getJson<VacancyData>('/ux/vacancies'))
  }

  async function loadWarehouseData() {
    setWarehouseData(await getJson<WarehouseData>('/ux/warehouse'))
  }

  async function loadPerformanceData() {
    setPerformanceHub(await getJson<PerformanceHubData>('/ux/performance-hub'))
  }

  async function loadPayrollData() {
    const [yearText, monthText] = payrollMonth.split('-')
    setPayrollHub(
      await getJson<PayrollHubData>('/ux/payroll-hub', {
        year: Number(yearText),
        month: Number(monthText),
        department_id: payrollDepartmentId || null
      })
    )
  }

  async function loadSystemConfigData() {
    if (!canAccessSettings) {
      setSystemConfig(null)
      return
    }
    setSystemConfig(await getJson<SystemConfigData>('/ux/system-config'))
  }

  useEffect(() => {
    void loadBootstrap().catch(() => undefined)
  }, [])

  useEffect(() => {
    if (!token) {
      return
    }

    async function bootstrap() {
      let me: AuthMe
      try {
        me = await getJson<AuthMe>('/auth/me')
      } catch (err) {
        logout()
        setToken('')
        setCurrentUser(null)
        setError((err as Error).message)
        return
      }

      try {
        setCurrentUser(me)
        const bootstrapData = await getJson<BootstrapData>('/ux/bootstrap')
        setBootstrap(bootstrapData)
        const bootstrapPolicies = bootstrapData.tenant.ui_policies ?? {
          gps_only_check_in: false,
          company_dashboard_enabled: true,
          payroll_dashboard_enabled: true,
          dashboard_widget_visibility: {
            summary_cards: true,
            analytics: true,
            live_feed: true,
            action_center: true,
            upcoming_schedule: true,
            celebrations: true
          }
        }
        const meCanAccessEmployees = (
          me.permissions.includes('employee.directory.read')
          || me.permissions.includes('employee.read_department')
          || me.permissions.includes('employee.manage')
          || me.permissions.includes('employee.edit')
          || me.role_codes.includes('ADMIN')
        )
        const meCanAccessAttendance = (
          me.permissions.includes('attendance.read_self')
          || me.permissions.includes('attendance.read_department')
          || me.permissions.includes('attendance.read_all')
          || me.permissions.includes('attendance.review')
          || me.permissions.includes('employee.manage')
          || (me.managed_department_ids?.length ?? 0) > 0
          || me.role_codes.includes('ADMIN')
        )
        if (meCanAccessEmployees || meCanAccessAttendance || me.permissions.includes('recruitment.read') || me.permissions.includes('recruitment.manage') || me.permissions.includes('payroll.export') || me.permissions.includes('assets.read_all') || me.permissions.includes('assets.manage') || me.permissions.includes('settings.manage') || me.role_codes.includes('ADMIN')) {
          const meCanAccessRecruitment = me.permissions.includes('recruitment.read') || me.permissions.includes('recruitment.manage') || me.role_codes.includes('ADMIN')
          const meCanAccessAssets = me.permissions.includes('assets.read_all') || me.permissions.includes('assets.manage') || me.role_codes.includes('ADMIN')
          const meCanAccessSettings = me.permissions.includes('settings.manage') || me.role_codes.includes('ADMIN')
          const meCanAccessCompanyDashboard = (
            bootstrapPolicies.company_dashboard_enabled && (
              me.permissions.includes('attendance.read_department')
              || me.permissions.includes('attendance.read_all')
              || me.permissions.includes('attendance.review')
              || me.permissions.includes('employee.manage')
              || (me.managed_department_ids?.length ?? 0) > 0
              || me.role_codes.includes('ADMIN')
            )
          )
          const meCanAccessPayroll = bootstrapPolicies.payroll_dashboard_enabled && (me.permissions.includes('payroll.export') || me.role_codes.includes('ADMIN'))
          const meCanManageDevices = meCanAccessSettings || me.permissions.includes('device.manage') || me.role_codes.includes('ADMIN')
          await Promise.all([
            loadStaticPanels({
              includePayroll: meCanAccessPayroll,
              canAccessRecruitment: meCanAccessRecruitment,
              canAccessAssets: meCanAccessAssets,
              canAccessSettings: meCanAccessSettings,
              canAccessCompanyDashboard: meCanAccessCompanyDashboard,
              canManageDevices: meCanManageDevices,
            }),
            loadLivePanels(meCanAccessCompanyDashboard),
            ...(meCanAccessAttendance ? [loadShiftPlanner()] : [])
          ])
        } else {
          setActiveSection('dashboard')
          await loadSelfServicePanels()
          if (
            me.permissions.includes('employee.directory.read')
            || me.permissions.includes('employee.read_department')
            || me.permissions.includes('employee.edit')
          ) {
            await loadEmployeeFormOptions()
          }
        }
        setError('')
      } catch (err) {
        setError((err as Error).message)
      }
    }

    void bootstrap()
    let feedInterval = 0
    let panelInterval = 0
    if (canAccessCompanyDashboard) {
      feedInterval = window.setInterval(() => {
        void loadLivePanels().catch((err: Error) => setError(err.message))
      }, 5000)
      panelInterval = window.setInterval(() => {
        void Promise.all([
          loadHomePanels(),
          loadDashboardSummary(),
          loadWebPunchData(),
          getJson<AnalyticsOverview>('/ux/analytics-overview').then(setAnalytics),
        ]).catch((err: Error) => setError(err.message))
      }, 15000)
    } else {
      panelInterval = window.setInterval(() => {
        void Promise.all([
          loadWebPunchData(),
          loadHomePanels(),
          ...(canAccessAttendance ? [loadAttendanceHubData()] : [])
        ]).catch((err: Error) => setError(err.message))
      }, 15000)
    }
    return () => {
      if (feedInterval) {
        window.clearInterval(feedInterval)
      }
      if (panelInterval) {
        window.clearInterval(panelInterval)
      }
    }
  }, [token, canAccessCompanyDashboard, canAccessAttendance])

  useEffect(() => {
    if (!token || !canAccessEmployees) {
      return
    }

    async function loadGrid() {
      setBusy(true)
      try {
        const payload = await getJson<GridResponse>('/ux/employees-grid', {
          search: deferredSearch,
          status_filter: statusFilter,
          department_id: departmentFilter || null,
          email_contains: emailFilter || null,
          phone_contains: phoneFilter || null,
          sort_by: sortBy,
          sort_direction: sortDirection,
          page,
          page_size: pageSize
        })
        setGrid(payload)
        setError('')
      } catch (err) {
        setError((err as Error).message)
      } finally {
        setBusy(false)
      }
    }

    void loadGrid()
  }, [
    token,
    canAccessEmployees,
    deferredSearch,
    statusFilter,
    departmentFilter,
    emailFilter,
    phoneFilter,
    sortBy,
    sortDirection,
    page,
    pageSize
  ])

  useEffect(() => {
    if (!token || !notice) {
      return
    }
    setToasts((rows) => [...rows, { id: `ok-${Date.now()}`, tone: 'success', message: notice }])
    setNotice('')
  }, [token, notice])

  useEffect(() => {
    if (!token || !error) {
      return
    }
    setToasts((rows) => [...rows, { id: `err-${Date.now()}`, tone: 'error', message: error }])
    setError('')
  }, [token, error])

  useEffect(() => {
    if (!token) {
      return
    }
    const handleIntegrationMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) {
        return
      }
      const payload = event.data as { type?: string; status?: string; message?: string } | null
      if (payload?.type !== 'google-calendar-oauth' && payload?.type !== 'slack-oauth') {
        return
      }
      if (payload.status === 'success') {
        void Promise.all([loadHomePanels(), loadIntegrationOverview()])
          .then(() => setNotice(payload.message ?? 'Integration connected.'))
          .catch((err) => setError((err as Error).message))
      } else {
        setError(payload.message ?? 'Integration could not be connected.')
      }
    }
    window.addEventListener('message', handleIntegrationMessage)
    return () => window.removeEventListener('message', handleIntegrationMessage)
  }, [token])

  useEffect(() => {
    setError('')
  }, [activeSection])

  useEffect(() => {
    if (!token || !featureFlags.attendance_enabled || !canAccessAttendance) {
      return
    }
    void loadAttendanceHubData().catch((err: Error) => setError(err.message))
  }, [token, featureFlags.attendance_enabled, canAccessAttendance, shiftMonthStart, attendanceDepartmentId])

  useEffect(() => {
    if (!token || !featureFlags.attendance_enabled || !canManageAttendance) {
      return
    }
    void loadShiftPlanner().catch((err: Error) => setError(err.message))
  }, [token, featureFlags.attendance_enabled, canManageAttendance, shiftMonthStart, attendanceDepartmentId])

  useEffect(() => {
    if (!token || !featureFlags.payroll_enabled || !canAccessPayroll) {
      return
    }
    void loadPayrollData().catch((err: Error) => setError(err.message))
  }, [token, featureFlags.payroll_enabled, canAccessPayroll, payrollMonth, payrollDepartmentId])

  useEffect(() => {
    if (!token || !featureFlags.ats_enabled || !canAccessRecruitment) {
      return
    }
    void Promise.all([loadVacancyData(), loadAtsBoard()]).catch((err: Error) => setError(err.message))
  }, [token, featureFlags.ats_enabled, canAccessRecruitment])

  useEffect(() => {
    if (!token) {
      return
    }

    const refreshHomePanels = () => {
      void loadHomePanels().catch((err: Error) => setError(err.message))
    }

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        refreshHomePanels()
      }
    }

    window.addEventListener('focus', refreshHomePanels)
    document.addEventListener('visibilitychange', handleVisibilityChange)
    const timer = window.setInterval(refreshHomePanels, 60000)

    return () => {
      window.removeEventListener('focus', refreshHomePanels)
      document.removeEventListener('visibilitychange', handleVisibilityChange)
      window.clearInterval(timer)
    }
  }, [token])

  useEffect(() => {
    const featureSectionMap: Array<[AppSection, boolean]> = [
      ['attendance', featureFlags.attendance_enabled],
      ['payroll', featureFlags.payroll_enabled],
      ['ats', featureFlags.ats_enabled],
      ['assets', featureFlags.assets_enabled],
      ['org_chart', featureFlags.org_chart_enabled],
      ['okrs', featureFlags.performance_enabled],
      ['team_chat', featureFlags.chat_enabled]
    ]
    const hiddenCurrentSection = featureSectionMap.find(([section, enabled]) => section === activeSection && !enabled)
    if (hiddenCurrentSection) {
      setActiveSection('dashboard')
    }
  }, [activeSection, featureFlags])

  useEffect(() => {
    if (token || !inviteToken) {
      return
    }
    setAuthBusy(true)
    setAuthError('')
    void getJson<InvitePreview>('/auth/invite/resolve', { invite_token: inviteToken })
      .then((payload) => {
        setInvitePreview(payload)
        setAuthScreen('invite')
      })
      .catch((err: Error) => {
        setAuthError(err.message)
        setInvitePreview(null)
      })
      .finally(() => setAuthBusy(false))
  }, [token, inviteToken])

  useEffect(() => {
    if (token || !resetToken) {
      return
    }
    setAuthBusy(true)
    setAuthError('')
    void getJson<PasswordResetPreview>('/auth/password-reset/resolve', { reset_token: resetToken })
      .then((payload) => {
        setResetPreview(payload)
        setAuthScreen('reset')
      })
      .catch((err: Error) => {
        setAuthError(err.message)
        setResetPreview(null)
      })
      .finally(() => setAuthBusy(false))
  }, [token, resetToken])

  async function handleLogin() {
    try {
      const response = await login(loginState.username, loginState.password)
      clearAuthQueryTokens()
      setInviteToken('')
      setResetToken('')
      setAuthScreen('login')
      setAuthError('')
      setAuthNotice('')
      setToken(response.access_token)
      setNotice('')
      setError('')
    } catch (err) {
      setAuthError((err as Error).message)
    }
  }

  async function handleForgotPassword() {
    if (!forgotUsernameOrEmail.trim()) {
      setAuthError('Enter your work email or username')
      return
    }
    setAuthBusy(true)
    setAuthError('')
    try {
      await postJson('/auth/password-reset/request', { username_or_email: forgotUsernameOrEmail.trim() })
      setAuthNotice('If the account exists, a password reset email has been sent.')
    } catch (err) {
      setAuthError((err as Error).message)
    } finally {
      setAuthBusy(false)
    }
  }

  async function handleResetPassword() {
    if (!resetToken) {
      setAuthError('Password reset link is missing')
      return
    }
    if (resetPasswordState.password.length < 10) {
      setAuthError('Password must be at least 10 characters long')
      return
    }
    if (resetPasswordState.password !== resetPasswordState.confirmPassword) {
      setAuthError('Passwords do not match')
      return
    }
    setAuthBusy(true)
    setAuthError('')
    try {
      await postJson('/auth/password-reset/confirm', {
        reset_token: resetToken,
        new_password: resetPasswordState.password
      })
      clearAuthQueryTokens()
      setResetToken('')
      setResetPreview(null)
      setResetPasswordState({ password: '', confirmPassword: '' })
      setAuthScreen('login')
      setAuthNotice('Password updated successfully. You can now sign in.')
    } catch (err) {
      setAuthError((err as Error).message)
    } finally {
      setAuthBusy(false)
    }
  }

  async function handleInviteCompletion() {
    if (!inviteToken) {
      setAuthError('Invite link is missing')
      return
    }
    if (inviteRegistration.password.length < 10) {
      setAuthError('Password must be at least 10 characters long')
      return
    }
    if (inviteRegistration.password !== inviteRegistration.confirmPassword) {
      setAuthError('Passwords do not match')
      return
    }
    if (inviteRegistration.personalNumber.replace(/\D/g, '').length !== 11) {
      setAuthError('Personal ID must contain exactly 11 digits')
      return
    }
    const phoneDigits = inviteRegistration.mobilePhone.replace(/\D/g, '')
    if (phoneDigits.length < 9 || phoneDigits.length > 15) {
      setAuthError('Phone number must contain 9 to 15 digits')
      return
    }
    setAuthBusy(true)
    setAuthError('')
    try {
      const form = new FormData()
      form.append('invite_token', inviteToken)
      form.append('personal_number', inviteRegistration.personalNumber)
      form.append('mobile_phone', inviteRegistration.mobilePhone)
      form.append('password', inviteRegistration.password)
      if (inviteRegistration.profilePhoto) {
        form.append('profile_photo', inviteRegistration.profilePhoto)
      }
      const response = await postForm<LoginResponse>('/auth/invite/complete', form)
      writeTokens(response.access_token, response.refresh_token)
      clearAuthQueryTokens()
      setInviteToken('')
      setInvitePreview(null)
      setAuthScreen('login')
      setAuthNotice('')
      setToken(response.access_token)
      setError('')
      setNotice('')
    } catch (err) {
      setAuthError((err as Error).message)
    } finally {
      setAuthBusy(false)
    }
  }

  function openCreateDrawer() {
    setDrawerMode('create')
    setDrawerTab('personal')
    setDraft(defaultDraft(options))
    setDraftPhoto(null)
    setDrawerSyncedDevices([])
    setDrawerOpen(true)
  }

  function populateDraftFromDetail(detail: EmployeeDetail) {
    setDrawerMode('edit')
    setDrawerTab('personal')
    setDraft({
      id: detail.id,
      legal_entity_id: detail.legal_entity_id,
      employee_number: detail.employee_number,
      personal_number: detail.personal_number ?? '',
      first_name: detail.first_name,
      last_name: detail.last_name,
      email: detail.email ?? '',
      mobile_phone: detail.mobile_phone ?? '',
      department_id: detail.department_id ?? '',
      job_role_id: detail.job_role_id ?? '',
      manager_employee_id: detail.manager_employee_id ?? '',
      manager_name: detail.manager_name ?? '',
      profile_photo_url: detail.profile_photo_url ?? '',
      hire_date: detail.hire_date,
      salary_type: detail.salary_type ?? 'monthly_fixed',
      base_salary: detail.base_salary != null ? String(detail.base_salary) : '',
      pay_policy_id: detail.pay_policy_id ?? options?.pay_policies?.[0]?.id ?? '',
      hourly_rate_override: detail.hourly_rate_override ?? '',
      is_pension_participant: detail.is_pension_participant,
      default_device_user_id: detail.default_device_user_id ?? '',
      new_job_role_title_ka: '',
      new_job_role_title_en: '',
      new_job_role_is_managerial: false
    })
    setDraftPhoto(null)
    setDrawerSyncedDevices(detail.synced_devices ?? [])
    setDrawerOpen(true)
  }

  async function openEmployeeProfileById(employeeId: string) {
    if (!options && canEditEmployees) {
      await loadEmployeeFormOptions()
    }
    const detail = await getJson<EmployeeDetail>(`/employees/${employeeId}`)
    populateDraftFromDetail(detail)
  }

  async function openEditDrawer(employee: GridItem) {
    await openEmployeeProfileById(employee.id)
  }

  async function createDepartment(payload: { name_ka: string; name_en: string }) {
    const legalEntityId = options?.legal_entity_id || draft.legal_entity_id
    if (!legalEntityId) {
      throw new Error('Legal entity is required before creating a department.')
    }
    const department = await postJson<{ id: string; name_en: string; name_ka: string; code: string }>('/departments', {
      legal_entity_id: legalEntityId,
      name_ka: payload.name_ka,
      name_en: payload.name_en || null,
    })
    await loadEmployeeFormOptions()
    setDraft((current) => ({ ...current, department_id: department.id }))
    setNotice(`Department created: ${department.name_ka || department.name_en}`)
    setError('')
    return department
  }

  async function openSyncModal(employee: GridItem) {
    try {
      if (!options) {
        await loadEmployeeFormOptions()
      }
      const detail = await getJson<EmployeeDetail>(`/employees/${employee.id}`)
      const syncedDeviceIds = detail.synced_devices?.map((device) => device.id) ?? []
      setSyncEmployee(employee)
      setSelectedDeviceIds(syncedDeviceIds)
      setSyncOpen(true)
      setError('')
    } catch (err) {
      setError((err as Error).message)
    }
  }

  function deactivateEmployee(employee: GridItem) {
    setPendingEmployeeAction({ kind: 'deactivate', employee })
  }

  function deleteEmployee(employee: GridItem) {
    setPendingEmployeeAction({ kind: 'delete', employee })
  }

  async function confirmEmployeeAction() {
    if (!pendingEmployeeAction) {
      return
    }
    const { employee, kind } = pendingEmployeeAction
    const employeeName = `${employee.first_name} ${employee.last_name}`.trim()
    setEmployeeActionBusy(true)
    try {
      if (kind === 'delete') {
        await deleteJson(`/employees/${employee.id}`)
      } else {
        await postJson(`/employees/${employee.id}/deactivate`)
      }
      await refreshAfterMutation()
      setPendingEmployeeAction(null)
      setNotice(kind === 'delete'
        ? `${employeeName} has been archived and removed from the active employee list.`
        : `${employeeName} has been deactivated.`)
      setError('')
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setEmployeeActionBusy(false)
    }
  }

  async function refreshAfterMutation() {
    const [homeData, gridData, orgChartData, personalReportsData] = await Promise.all([
      getJson<WidgetData>('/ux/home-data'),
      getJson<GridResponse>('/ux/employees-grid', {
        search: deferredSearch,
        status_filter: statusFilter,
        department_id: departmentFilter || null,
        email_contains: emailFilter || null,
        phone_contains: phoneFilter || null,
        sort_by: sortBy,
        sort_direction: sortDirection,
        page,
        page_size: pageSize
      }),
      getJson<OrgChartData>('/ux/org-chart'),
      getJson<PersonalReportsData>('/ux/personal-reports')
    ])
    setSummary(homeData.summary)
    setGrid(gridData)
    setOrgChart(orgChartData)
    setPersonalReports(personalReportsData)
  }

  async function enrollEmployeeCard(payload: { employeeId: string; deviceId: string; cardNumber: string }) {
    try {
      const session = await postJson<{ enrollment_token: string }>('/api/v1/devices/enroll-card', {
        employee_id: payload.employeeId,
        device_id: payload.deviceId
      })
      await postJson('/api/v1/devices/enroll-card/read', {
        enrollment_token: session.enrollment_token,
        card_id: payload.cardNumber
      })
      await openEmployeeProfileById(payload.employeeId)
      await loadLivePanels()
      setNotice('Card enrolled and queued for device sync.')
      setError('')
    } catch (err) {
      setError((err as Error).message)
      throw err
    }
  }

  async function importEmployees(file: File) {
    if (!options?.legal_entity_id) {
      setError('იურიდიული ერთეულის კონფიგურაცია ვერ მოიძებნა')
      return
    }

    setImportBusy(true)
    try {
      const form = new FormData()
      form.append('file', file)
      form.append('legal_entity_id', options.legal_entity_id)
      const response = await postForm<{ created_count: number; updated_count: number; skipped_count: number }>('/employees/import', form)
      await loadEmployeeFormOptions()
      await refreshAfterMutation()
      setNotice(`Import complete: ${response.created_count} created, ${response.updated_count} updated, ${response.skipped_count} skipped.`)
      setError('')
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setImportBusy(false)
    }
  }

  async function downloadEmployeesFile(path: string, params?: Record<string, string | number | null | undefined>) {
    try {
      const { blob, fileName } = await downloadFile(path, params)
      const objectUrl = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = objectUrl
      link.download = fileName ?? 'download'
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(objectUrl)
      setError('')
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function exportEmployees(format: 'csv' | 'xlsx') {
    await downloadEmployeesFile('/employee-tools/export', {
      format,
      search: deferredSearch || null,
      status_filter: statusFilter || null,
      department_id: departmentFilter || null,
      email_contains: emailFilter || null,
      phone_contains: phoneFilter || null,
      sort_by: sortBy,
      sort_direction: sortDirection,
    })
  }

  async function downloadEmployeeImportTemplate(format: 'csv' | 'xlsx') {
    await downloadEmployeesFile(`/employee-tools/import-template.${format}`)
  }

  async function submitEmployee() {
    let jobRoleId = draft.job_role_id || null
    if (draft.new_job_role_title_ka.trim() || draft.new_job_role_title_en.trim()) {
      try {
        const role = await postJson<{ id: string }>('/job-roles', {
          legal_entity_id: draft.legal_entity_id,
          title_ka: draft.new_job_role_title_ka,
          title_en: draft.new_job_role_title_en || null,
          is_managerial: draft.new_job_role_is_managerial
        })
        jobRoleId = role.id
        await loadEmployeeFormOptions()
      } catch (err) {
        setError((err as Error).message)
        return
      }
    }

    try {
      let employeeId = draft.id ?? ''
      if (drawerMode === 'create') {
        const response = await postJson<EmployeeInviteResult>('/api/v1/invites', {
          legal_entity_id: draft.legal_entity_id,
          email: draft.email || null,
          department_id: draft.department_id || null,
          job_role_id: jobRoleId,
          manager_employee_id: draft.manager_employee_id || null,
          salary_type: draft.salary_type,
          base_salary: Number(draft.base_salary || 0),
          pay_policy_id: draft.pay_policy_id,
          is_pension_participant: draft.is_pension_participant
        })
        employeeId = response.employee_id
        setEmployeeInviteResult(response)
      } else if (draft.id) {
        const payload = {
          first_name: draft.first_name,
          last_name: draft.last_name,
          email: draft.email || null,
          mobile_phone: draft.mobile_phone || null,
          department_id: draft.department_id || null,
          job_role_id: jobRoleId,
          manager_employee_id: draft.manager_employee_id || null,
          default_device_user_id: draft.default_device_user_id || null,
          salary_type: draft.salary_type,
          base_salary: Number(draft.base_salary || 0),
          pay_policy_id: draft.pay_policy_id,
          hourly_rate_override: draft.hourly_rate_override ? Number(draft.hourly_rate_override) : null,
          is_pension_participant: draft.is_pension_participant
        }
        const updatePayload = {
          first_name: payload.first_name,
          last_name: payload.last_name,
          email: payload.email,
          mobile_phone: payload.mobile_phone,
          department_id: payload.department_id,
          job_role_id: payload.job_role_id,
          manager_employee_id: payload.manager_employee_id,
          default_device_user_id: payload.default_device_user_id
        } as Record<string, unknown>
        if (employeeFormPermissions.can_view_salary) {
          updatePayload.salary_type = payload.salary_type
          updatePayload.base_salary = payload.base_salary
          updatePayload.pay_policy_id = payload.pay_policy_id
          updatePayload.hourly_rate_override = payload.hourly_rate_override
          updatePayload.is_pension_participant = payload.is_pension_participant
        }
        await putJson(`/employees/${draft.id}`, updatePayload)
        employeeId = draft.id
      }
      if (drawerMode === 'edit' && employeeId && draftPhoto) {
        const photoForm = new FormData()
        photoForm.append('photo', draftPhoto)
        await postForm(`/employees/${employeeId}/profile-photo`, photoForm)
      }
      setDrawerOpen(false)
      setDraftPhoto(null)
      await refreshAfterMutation()
      setNotice(drawerMode === 'create' ? 'Invite created successfully.' : 'Employee profile updated successfully.')
      setError('')
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function submitSync() {
    if (!syncEmployee) {
      return
    }
    try {
      const response = await postJson<{
        added_device_count: number
        removed_device_count: number
        current_device_ids: string[]
      }>(`/employees/${syncEmployee.id}/device-sync`, { device_ids: selectedDeviceIds })
      const detail = await getJson<EmployeeDetail>(`/employees/${syncEmployee.id}`)
      setDrawerSyncedDevices(detail.synced_devices ?? [])
      setSelectedDeviceIds(response.current_device_ids ?? [])
      setSyncOpen(false)
      await Promise.all([loadLivePanels(), loadEmployeeFormOptions()])
      setNotice(`Hardware sync updated: ${response.added_device_count} added, ${response.removed_device_count} removed.`)
      setError('')
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function submitLeaveRequest(payload: { leave_type_id: string; start_date: string; end_date: string; reason: string; doctor_note: File | null }) {
    const form = new FormData()
    form.append('leave_type_id', payload.leave_type_id)
    form.append('start_date', payload.start_date)
    form.append('end_date', payload.end_date)
    form.append('reason', payload.reason)
    if (payload.doctor_note) {
      form.append('doctor_note', payload.doctor_note)
    }
    try {
      await postForm('/ess/leave/request', form)
      setLeaveData(await getJson<LeaveSelfServiceData>('/ux/leave-self-service'))
      setNotice('Leave request submitted successfully.')
      setError('')
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function viewAttendanceByEmployee(employeeId: string, employeeName: string) {
    try {
      const rows = await getJson<AttendanceHistoryItem[]>(`/ux/employee-attendance/${employeeId}`)
      setAttendanceEmployeeName(employeeName)
      setAttendanceRows(rows)
      setAttendanceOpen(true)
      setError('')
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function viewAttendance(employee: GridItem) {
    await viewAttendanceByEmployee(employee.id, `${employee.first_name} ${employee.last_name}`)
  }

  async function moveAtsCard(applicationId: string, targetStage: string) {
    const previousBoard = atsBoard
    setAtsBoard((current) => moveCandidateLocally(current, applicationId, targetStage))
    try {
      const card = previousBoard ? Object.values(previousBoard.cards).flat().find((item) => item.id === applicationId) : null
      const payload: Record<string, unknown> = { stage_code: targetStage }
      if (targetStage === 'HIRED') {
        const payPolicyId = options?.pay_policies?.[0]?.id
        if (!payPolicyId) {
          throw new Error('No pay policy configured for hire conversion')
        }
        payload.hire_payload = {
          hire_date: new Date().toISOString().slice(0, 10),
          pay_policy_id: payPolicyId,
          base_salary: card?.salary_max ?? card?.salary_min ?? 0,
          access_role_codes: ['EMPLOYEE']
        }
      }
      const response = await postJson<{
        stage_code: string
        employee_id?: string
        invite_link?: string
        invite_email_status?: string
      }>(`/ats/applications/${applicationId}/move`, payload)
      await loadAtsBoard()
      if (targetStage === 'HIRED') {
        const candidateName = [card?.first_name, card?.last_name].filter(Boolean).join(' ') || 'Candidate'
        setNotice(
          response.invite_email_status === 'sent'
            ? `${candidateName} was moved to Hired and the onboarding invite email was sent.`
            : `${candidateName} was moved to Hired and the onboarding invite was created. SMTP is not configured, so the email was skipped.`
        )
      }
      setError('')
    } catch (err) {
      setAtsBoard(previousBoard)
      setError((err as Error).message)
    }
  }

  async function scheduleAtsInterview(
    applicationId: string,
    payload: {
      scheduled_at: string
      duration_minutes: number
      notes: string
    }
  ): Promise<{ calendar_url?: string | null }> {
    try {
      const response = await postJson<{
        status: string
        scheduled_at: string
        duration_minutes: number
        calendar_url?: string | null
        email_status?: string
      }>(`/ats/applications/${applicationId}/schedule-interview`, payload)
      await loadAtsBoard()
      setNotice(
        response.email_status === 'sent'
          ? 'Interview scheduled and notification email sent.'
          : 'Interview scheduled. Google Calendar link is ready.'
      )
      setError('')
      return response
    } catch (err) {
      setError((err as Error).message)
      throw err
    }
  }

  async function assignShift(
    employeeId: string,
    payload: {
      shiftPatternId?: string | null
      shiftDate: string
      startTime?: string
      endTime?: string
    }
  ) {
    const previousPlanner = shiftPlanner
    setShiftPlanner((current) => updateShiftPlannerLocally(current, employeeId, payload))
    try {
      const res = await postJson<{ over_40h_warning?: boolean }>('/ux/shift-planner/assignments', {
        employee_id: employeeId,
        shift_pattern_id: payload.shiftPatternId ?? null,
        shift_date: payload.shiftDate,
        start_time: payload.startTime ?? null,
        end_time: payload.endTime ?? null,
      })
      await Promise.all([
        loadShiftPlanner(),
        ...(canAccessAttendance ? [loadAttendanceHubData()] : [])
      ])
      setError('')
      if (res.over_40h_warning) {
        setToasts((rows) => [
          ...rows,
          {
            id: `w-${Date.now()}`,
            tone: 'warning',
            message: 'გაფრთხილება: ამ კვირის გეგმილი საათები აღემატება 40 საათს.'
          }
        ])
      }
    } catch (err) {
      setShiftPlanner(previousPlanner)
      setError((err as Error).message)
    }
  }

  async function clearShift(employeeId: string, shiftDate: string) {
    const previousPlanner = shiftPlanner
    setShiftPlanner((current) => clearShiftLocally(current, employeeId, shiftDate))
    try {
      await deleteJson(`/ux/shift-planner/assignments/${employeeId}/${shiftDate}`)
      await Promise.all([
        loadShiftPlanner(),
        ...(canAccessAttendance ? [loadAttendanceHubData()] : [])
      ])
      setError('')
    } catch (err) {
      setShiftPlanner(previousPlanner)
      setError((err as Error).message)
    }
  }

  async function submitWebPunch(payload: { direction: string; latitude: number | null; longitude: number | null }) {
    try {
      await postJson('/attendance/web-punch', payload)
      await Promise.all([
        loadLivePanels(),
        loadWebPunchData(),
        loadHomePanels(),
        loadDashboardSummary(),
        ...(canAccessCompanyDashboard ? [getJson<AnalyticsOverview>('/ux/analytics-overview').then(setAnalytics)] : []),
        ...(canAccessAttendance ? [loadAttendanceHubData()] : [])
      ])
      setError('')
    } catch (err) {
      setError((err as Error).message)
      throw err
    }
  }

  async function headerWebCheckIn() {
    try {
      await submitWebPunch({ direction: 'auto', latitude: null, longitude: null })
      setNotice(isTopCheckedIn ? 'Web Check-Out ჩაიწერა' : 'Web Check-In ჩაიწერა')
    } catch {
      /* toast via submitWebPunch error path */
    }
  }

  async function saveVacancy(
    vacancyId: string | null,
    payload: {
      posting_code: string
      title_en: string
      title_ka: string
      description: string
      public_description: string
      employment_type: string
      location_text: string
      status: string
      open_positions: number
      salary_min: number
      salary_max: number
      department_id: string | null
      job_role_id: string | null
      closes_at: string | null
      public_slug: string
      external_form_url: string | null
      is_public: boolean
      application_form_schema: Array<{ key: string; label: string; field_type: string; required: boolean; options: Array<{ label: string; value: string }> }>
    }
  ): Promise<{ vacancy_id: string; public_slug: string }> {
    try {
      if (vacancyId) {
        const response = await putJson<{ status: string; public_slug: string }>(`/vacancies/${vacancyId}`, payload)
        await Promise.all([loadVacancyData(), loadAtsBoard()])
        setError('')
        return { vacancy_id: vacancyId, public_slug: response.public_slug }
      } else {
        const response = await postJson<{ vacancy_id: string; public_slug: string }>('/vacancies', payload)
        await Promise.all([loadVacancyData(), loadAtsBoard()])
        setError('')
        return response
      }
    } catch (err) {
      setError((err as Error).message)
      throw err
    }
  }

  async function saveInventoryItem(
    itemId: string | null,
    payload: {
      category_id: string | null
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
      assigned_department_id: string | null
      notes: string | null
    }
  ) {
    try {
      if (itemId) {
        await putJson(`/inventory/items/${itemId}`, payload)
      } else {
        await postJson('/inventory/items', payload)
      }
      await loadWarehouseData()
      setError('')
    } catch (err) {
      setError((err as Error).message)
      throw err
    }
  }

  async function assignInventoryItem(
    itemId: string,
    payload: {
      employee_id: string
      assigned_at: string
      expected_return_at: string | null
      condition_on_issue: string
      note: string | null
      employee_signature_name: string
    }
  ) {
    try {
      await postJson(`/inventory/items/${itemId}/assign`, payload)
      await loadWarehouseData()
      setError('')
    } catch (err) {
      setError((err as Error).message)
      throw err
    }
  }

  async function saveDeviceRegistryItem(
    deviceId: string | null,
    payload: {
      legal_entity_id: string
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
    }
  ) {
    try {
      if (deviceId) {
        await putJson(`/devices/registry/${deviceId}`, payload)
      } else {
        await postJson('/devices/registry', payload)
      }
      setDeviceRegistry(await getJson<DeviceRegistryData>('/ux/device-registry'))
      setNotice('მოწყობილობის რეესტრი განახლდა')
      setError('')
    } catch (err) {
      setError((err as Error).message)
      throw err
    }
  }

  async function createObjective(payload: {
    cycle_id: string
    scope: string
    title: string
    description: string | null
    department_id: string | null
    employee_id: string | null
    owner_employee_id: string | null
    weight: number
    key_result_title: string
    metric_unit: string
    target_value: number
  }) {
    try {
      const objectiveResponse = await postJson<{ objective_id: string }>('/performance/objectives', {
        cycle_id: payload.cycle_id,
        scope: payload.scope,
        title: payload.title,
        description: payload.description,
        department_id: payload.department_id,
        employee_id: payload.employee_id,
        owner_employee_id: payload.owner_employee_id,
        weight: payload.weight
      })
      await postJson('/performance/key-results', {
        objective_id: objectiveResponse.objective_id,
        title: payload.key_result_title,
        metric_unit: payload.metric_unit,
        start_value: 0,
        target_value: payload.target_value,
        current_value: 0
      })
      await loadPerformanceData()
      setError('')
    } catch (err) {
      setError((err as Error).message)
      throw err
    }
  }

  async function markPaid(timesheetId: string, payload: { payment_method: string; payment_reference: string | null; note: string | null }) {
    try {
      await postJson(`/payroll/timesheets/${timesheetId}/mark-paid`, payload)
      await loadPayrollData()
      setError('')
    } catch (err) {
      setError((err as Error).message)
      throw err
    }
  }

  async function importSmartPssAttendance(file: File) {
    setAttendanceImportBusy(true)
    try {
      const form = new FormData()
      form.append('file', file)
      const response = await postForm<{
        imported_count: number
        duplicate_count: number
        unmatched_count: number
        skipped_count: number
      }>('/attendance/import-smartpss', form)
      await Promise.all([
        ...(canAccessAttendance ? [loadAttendanceHubData(), loadShiftPlanner()] : []),
        loadHomePanels(),
        loadDashboardSummary(),
      ])
      setNotice(
        `SmartPSS import complete: ${response.imported_count} imported, ${response.duplicate_count} duplicates, ${response.unmatched_count} unmatched, ${response.skipped_count} skipped.`
      )
      setError('')
    } catch (err) {
      setError((err as Error).message)
      throw err
    } finally {
      setAttendanceImportBusy(false)
    }
  }

  async function generatePayrollDraft() {
    const [yearText, monthText] = payrollMonth.split('-')
    try {
      await postJson('/payroll/drafts/generate', {
        year: Number(yearText),
        month: Number(monthText),
        department_id: payrollDepartmentId || null
      })
      await loadPayrollData()
      setNotice('Payroll draft generated.')
      setError('')
    } catch (err) {
      setError((err as Error).message)
      throw err
    }
  }

  async function saveSystemConfig(payload: {
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
  }) {
    if (!options?.legal_entity_id) {
      return
    }
    try {
      await putJson(`/system/config/${options.legal_entity_id}`, payload)
      await Promise.all([
        loadSystemConfigData(),
        loadStaticPanels({
          includePayroll: payload.payroll_dashboard_enabled && (employeePermissions.includes('payroll.export') || currentUser?.role_codes?.includes('ADMIN') || false),
          canAccessRecruitment,
          canAccessAssets,
          canAccessSettings,
          canAccessCompanyDashboard: payload.company_dashboard_enabled && (
            employeePermissions.includes('attendance.read_department')
            || employeePermissions.includes('attendance.read_all')
            || employeePermissions.includes('attendance.review')
            || employeePermissions.includes('employee.manage')
            || (currentUser?.managed_department_ids?.length ?? 0) > 0
            || currentUser?.role_codes?.includes('ADMIN')
          ),
          canManageDevices: canAccessSettings || employeePermissions.includes('device.manage'),
        }),
        loadBootstrap(),
      ])
      setError('')
    } catch (err) {
      setError((err as Error).message)
      throw err
    }
  }

  async function saveScheduleManagers(payload: { assignments: Array<{ department_id: string; employee_ids: string[] }> }) {
    if (!options?.legal_entity_id) {
      return
    }
    try {
      await putJson(`/system/policies/${options.legal_entity_id}/schedule-managers`, payload)
      await Promise.all([loadSystemConfigData(), loadAttendanceHubData(), loadShiftPlanner()])
      setNotice('Schedule manager assignments updated.')
      setError('')
    } catch (err) {
      setError((err as Error).message)
      throw err
    }
  }

  async function saveLeavePolicies(payload: {
    paid_leave_allowance_days: number
    unpaid_leave_allowance_days: number
    eligibility_months: number
    enable_birthday_off: boolean
    enable_day_off: boolean
    global_leave_approver_employee_id: string | null
    department_approvers: Array<{ department_id: string; approver_employee_id: string | null }>
  }) {
    if (!options?.legal_entity_id) {
      return
    }
    try {
      await putJson(`/system/policies/${options.legal_entity_id}/leave`, payload)
      const latestLeaveData = await getJson<LeaveSelfServiceData>('/ux/leave-self-service')
      setLeaveData(latestLeaveData)
      await loadSystemConfigData()
      setNotice('Leave policies updated.')
      setError('')
    } catch (err) {
      setError((err as Error).message)
      throw err
    }
  }

  async function saveEmployeeEditors(payload: { assignments: Array<{ department_id: string; employee_ids: string[] }> }) {
    if (!options?.legal_entity_id) {
      return
    }
    try {
      await putJson(`/system/policies/${options.legal_entity_id}/employee-editors`, payload)
      await Promise.all([loadSystemConfigData(), refreshAfterMutation()])
      setNotice('Department-based employee edit access updated.')
      setError('')
    } catch (err) {
      setError((err as Error).message)
      throw err
    }
  }

  async function saveWorksites(payload: { worksites: Array<{ id?: string | null; name: string; latitude: number; longitude: number; radius_meters: number; address_text: string | null; is_active: boolean }> }) {
    if (!options?.legal_entity_id) {
      return
    }
    try {
      await putJson(`/system/policies/${options.legal_entity_id}/worksites`, payload)
      await loadSystemConfigData()
      setNotice('Worksites updated.')
      setError('')
    } catch (err) {
      setError((err as Error).message)
      throw err
    }
  }

  async function createMiddlewareKey(payload: { key_name: string }) {
    if (!options?.legal_entity_id) {
      throw new Error('Legal entity is not available')
    }
    try {
      const response = await postJson<{ key_id: string; api_key: string; key_name: string }>(`/system/policies/${options.legal_entity_id}/middleware-keys`, payload)
      await loadSystemConfigData()
      setNotice('Middleware API key created.')
      setError('')
      return response
    } catch (err) {
      setError((err as Error).message)
      throw err
    }
  }

  async function revokeMiddlewareKey(keyId: string) {
    if (!options?.legal_entity_id) {
      return
    }
    try {
      await deleteJson(`/system/policies/${options.legal_entity_id}/middleware-keys/${keyId}`)
      await loadSystemConfigData()
      setNotice('Middleware API key revoked.')
      setError('')
    } catch (err) {
      setError((err as Error).message)
      throw err
    }
  }

  async function saveEmployeeRoles(employeeId: string, roleCodes: string[]) {
    try {
      await putJson(`/rbac/employees/${employeeId}/roles`, { role_codes: roleCodes })
      await loadSystemConfigData()
      setError('')
    } catch (err) {
      setError((err as Error).message)
      throw err
    }
  }

  async function saveRolePermissions(roleCode: string, permissionCodes: string[]) {
    try {
      await putJson(`/system/rbac/roles/${roleCode}/permissions`, { permission_codes: permissionCodes })
      await loadSystemConfigData()
      setNotice(`Permissions updated for ${roleCode}.`)
      setError('')
    } catch (err) {
      setError((err as Error).message)
      throw err
    }
  }

  async function saveSubscriptions(payload: FeatureFlags) {
    if (!options?.legal_entity_id) {
      return
    }
    try {
      await putJson(`/system/tenants/${options.legal_entity_id}/subscriptions`, payload)
      await loadSystemConfigData()
      await loadBootstrap()
      setNotice('Tenant მოდულები განახლდა')
      setError('')
    } catch (err) {
      setError((err as Error).message)
      throw err
    }
  }

  async function createTenant(payload: {
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
  }) {
    try {
      const response = await postJson<{ legal_entity_id: string; admin_username: string }>('/system/tenants', payload)
      await loadSystemConfigData()
      setNotice(`კომპანია დაემატა. ადმინი: ${response.admin_username}`)
      setError('')
    } catch (err) {
      setError((err as Error).message)
      throw err
    }
  }

  async function saveTenantDomain(
    domainId: string | null,
    payload: { host: string; subdomain: string | null; is_primary: boolean; is_active: boolean }
  ) {
    if (!options?.legal_entity_id) {
      return
    }
    try {
      if (domainId) {
        await putJson(`/system/tenants/domains/${domainId}`, payload)
      } else {
        await postJson(`/system/tenants/${options.legal_entity_id}/domains`, payload)
      }
      await Promise.all([loadSystemConfigData(), loadBootstrap()])
      setNotice('Tenant domain განახლდა')
      setError('')
    } catch (err) {
      setError((err as Error).message)
      throw err
    }
  }

  function openMessageComposer(target: { employeeId: string; employeeName: string }) {
    if (availableMessageChannels.length === 0) {
      setError('Connect Slack or company email in Apps & Integrations before sending messages.')
      return
    }
    setMessageTarget(target)
  }

  async function sendDirectMessage(payload: { channel: MessageChannel; subject: string; message: string }) {
    if (!messageTarget) {
      return
    }
    setMessageSending(true)
    try {
      await postJson('/integrations/messages/send', {
        employee_id: messageTarget.employeeId,
        channel: payload.channel,
        subject: payload.channel === 'email' ? payload.subject : null,
        message: payload.message,
      })
      setMessageTarget(null)
      setNotice(`Message sent to ${messageTarget.employeeName}.`)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setMessageSending(false)
    }
  }

  async function connectGoogleCalendar() {
    if (integrationsOverview?.google_calendar.configured === false || upcomingSchedule?.configured === false) {
      setError('Google Calendar is not configured yet. Add GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_REDIRECT_URI to .env, then rebuild Docker.')
      return
    }
    setIntegrationBusy(true)
    try {
      const response = await getJson<{ authorize_url: string }>('/integrations/google-calendar/oauth-url')
      const popup = window.open(response.authorize_url, 'google-calendar-connect', 'popup=yes,width=560,height=720')
      if (!popup) {
        window.location.href = response.authorize_url
        return
      }
      popup.focus()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setIntegrationBusy(false)
    }
  }

  async function disconnectGoogleCalendar() {
    setIntegrationBusy(true)
    try {
      await deleteJson('/integrations/google-calendar/connection')
      await Promise.all([loadHomePanels(), loadIntegrationOverview()])
      setNotice('Google Calendar disconnected.')
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setIntegrationBusy(false)
    }
  }

  async function connectSlack() {
    if (integrationsOverview?.slack.configured === false) {
      setError('Slack is not configured yet. Add SLACK_CLIENT_ID, SLACK_CLIENT_SECRET, and SLACK_REDIRECT_URI to .env, then rebuild Docker.')
      return
    }
    setIntegrationBusy(true)
    try {
      const response = await getJson<{ authorize_url: string }>('/integrations/slack/oauth-url')
      const popup = window.open(response.authorize_url, 'slack-connect', 'popup=yes,width=640,height=820')
      if (!popup) {
        window.location.href = response.authorize_url
        return
      }
      popup.focus()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setIntegrationBusy(false)
    }
  }

  async function disconnectSlack() {
    setIntegrationBusy(true)
    try {
      await deleteJson('/integrations/slack/connection')
      await loadIntegrationOverview()
      setNotice('Slack disconnected.')
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setIntegrationBusy(false)
    }
  }

  async function handleLiveFeedDetails(event: FeedEvent) {
    if (event.employee_id) {
      try {
        await openEmployeeProfileById(event.employee_id)
      } catch (err) {
        setError((err as Error).message)
      }
      return
    }
    setActiveSection('attendance')
  }

  function renderSection() {
    const dashboardWidgetVisibility = uiPolicies.dashboard_widget_visibility ?? {}
    const showDashboardMetricSection =
      Boolean(dashboardWidgetVisibility.summary_cards ?? true)
      || Boolean(dashboardWidgetVisibility.analytics ?? true)
      || Boolean(dashboardWidgetVisibility.upcoming_schedule ?? true)
    const showDashboardLiveFeed = Boolean(dashboardWidgetVisibility.live_feed ?? true)
    const showDashboardActionCenter = Boolean(dashboardWidgetVisibility.action_center ?? true)
    const showDashboardCelebrations = Boolean(dashboardWidgetVisibility.celebrations ?? true)

    switch (activeSection) {
      case 'dashboard': {
        const showCalendarColumn = canAccessCompanyDashboard && Boolean(dashboardWidgetVisibility.upcoming_schedule ?? true)
        const hasLeftColumn = canAccessCompanyDashboard && showDashboardLiveFeed
        const hasRightStack =
          canAccessCompanyDashboard && (showCalendarColumn || showDashboardActionCenter)
        return (
          <div className="space-y-6">
            {showDashboardMetricSection ? (
              <MetricCards
                summary={summary}
                analytics={analytics}
                weeklyAttendance={weeklyAttendance}
                upcomingSchedule={upcomingSchedule}
                hideUpcomingSchedule={showCalendarColumn}
                widgetVisibility={dashboardWidgetVisibility}
                onOpenEmployees={() => setActiveSection('employees')}
                onViewAttendance={() => setActiveSection('attendance')}
                onConnectGoogleCalendar={() => void connectGoogleCalendar()}
                onDisconnectGoogleCalendar={() => void disconnectGoogleCalendar()}
                onSendMessage={(employeeId, employeeName) => openMessageComposer({ employeeId, employeeName })}
              />
            ) : null}
            {canAccessCompanyDashboard ? (
              <>
                {hasLeftColumn || hasRightStack ? (
                  <div
                    className={classNames(
                      'grid gap-6',
                      hasLeftColumn && hasRightStack ? 'xl:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)]' : ''
                    )}
                  >
                    {hasLeftColumn ? (
                      <div className="space-y-6">
                        <LiveFeed
                          feed={feed}
                          onViewDetails={(event) => void handleLiveFeedDetails(event)}
                          onSendMessage={(employeeId, employeeName) => openMessageComposer({ employeeId, employeeName })}
                        />
                        {multiPointSummary.length > 0 ? (
                          <article className="panel-card p-5">
                            <div className="flex items-center justify-between">
                              <div>
                                <h2 className="text-lg font-semibold text-slate-900">დღის მრავალწერტილოვანი დასწრება</h2>
                                <p className="mt-1 text-sm text-slate-500">პირველი (MIN) და ბოლო (MAX) გადახვევა — ყველა მკითხველი ერთად</p>
                              </div>
                            </div>
                            <ul className="mt-4 divide-y divide-slate-100">
                              {multiPointSummary.slice(0, 8).map((entry) => {
                                const fullName = `${entry.first_name ?? ''} ${entry.last_name ?? ''}`.trim() || entry.employee_number
                                const fmt = (value: string | null) =>
                                  value ? new Date(value).toLocaleTimeString('ka-GE', { hour: '2-digit', minute: '2-digit' }) : '—'
                                return (
                                  <li key={entry.employee_id} className="py-3 text-sm">
                                    <div className="font-semibold text-slate-900">
                                      {fullName} <span className="text-xs font-normal text-slate-400">#{entry.employee_number}</span>
                                    </div>
                                    <div className="mt-1 text-slate-600">
                                      <span className="font-medium text-emerald-700">შემოვიდა {fmt(entry.first_swipe_ts)}</span>
                                      {entry.first_location_name ? <> · {entry.first_location_name}</> : null}
                                      {entry.last_swipe_ts ? (
                                        <>
                                          <span className="px-2 text-slate-300">→</span>
                                          <span className="font-medium text-amber-700">გავიდა {fmt(entry.last_swipe_ts)}</span>
                                          {entry.last_location_name ? <> · {entry.last_location_name}</> : null}
                                        </>
                                      ) : (
                                        <span className="ml-2 rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-semibold text-emerald-700">აქტიური</span>
                                      )}
                                    </div>
                                    <div className="mt-1 text-xs text-slate-400">სულ {entry.swipe_count} გადახვევა</div>
                                  </li>
                                )
                              })}
                            </ul>
                          </article>
                        ) : null}
                      </div>
                    ) : null}
                    {hasRightStack ? (
                      <div className="space-y-6">
                        {showCalendarColumn ? (
                          <UpcomingSchedulePanel
                            upcomingSchedule={upcomingSchedule}
                            calendarBusy={integrationBusy}
                            onConnectGoogleCalendar={() => void connectGoogleCalendar()}
                            onDisconnectGoogleCalendar={() => void disconnectGoogleCalendar()}
                            onSendMessage={(employeeId, employeeName) => openMessageComposer({ employeeId, employeeName })}
                          />
                        ) : null}
                        {showDashboardActionCenter ? (
                          <DashboardActionPanel
                            summary={dashboardSummary}
                            upcomingSchedule={upcomingSchedule}
                            onOpenAttendance={() => setActiveSection('attendance')}
                            onOpenEmployees={() => setActiveSection('employees')}
                          />
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                ) : null}
                {showDashboardCelebrations ? (
                  <CelebrationWidget
                    data={celebrationData}
                    onSendMessage={(employeeId, employeeName) => openMessageComposer({ employeeId, employeeName })}
                  />
                ) : null}
              </>
            ) : (
              <PersonalReportsPanel data={personalReports} />
            )}
          </div>
        )
      }
      case 'employees':
        return (
          <EmployeeGrid
            grid={grid}
            permissions={employeeGridPermissions}
            busy={busy}
            importBusy={importBusy}
            search={search}
            statusFilter={statusFilter}
            departmentFilter={departmentFilter}
            emailFilter={emailFilter}
            phoneFilter={phoneFilter}
            departments={options?.departments ?? []}
            sortBy={sortBy}
            sortDirection={sortDirection}
            onSearchChange={(value) => {
              setSearch(value)
              setPage(1)
            }}
            onStatusFilterChange={(value) => {
              setStatusFilter(value)
              setPage(1)
            }}
            onDepartmentFilterChange={(value) => {
              setDepartmentFilter(value)
              setPage(1)
            }}
            onEmailFilterChange={(value) => {
              setEmailFilter(value)
              setPage(1)
            }}
            onPhoneFilterChange={(value) => {
              setPhoneFilter(value)
              setPage(1)
            }}
            onSortByChange={setSortBy}
            onToggleSortDirection={() => setSortDirection((current) => (current === 'asc' ? 'desc' : 'asc'))}
            onOpenCreate={openCreateDrawer}
            onOpenEdit={(employee) => void openEditDrawer(employee)}
            onOpenSync={(employee) => void openSyncModal(employee)}
            onViewAttendance={(employee) => void viewAttendance(employee)}
            onDeactivate={deactivateEmployee}
            onDelete={deleteEmployee}
            onPageChange={setPage}
            onPageSizeChange={(size) => {
              setPageSize(size)
              setPage(1)
            }}
            onImport={(file) => void importEmployees(file)}
            onExport={(format) => void exportEmployees(format)}
            onDownloadTemplate={(format) => void downloadEmployeeImportTemplate(format)}
          />
        )
      case 'attendance':
        return (
          <AttendanceHub
            data={attendanceHub}
            shiftPlannerData={shiftPlanner}
            attendanceImportBusy={attendanceImportBusy}
            selectedMonth={shiftMonthStart}
            onPreviousMonth={() => setShiftMonthStart((current) => shiftDateByMonths(current, -1))}
            onNextMonth={() => setShiftMonthStart((current) => shiftDateByMonths(current, 1))}
            onMonthChange={setShiftMonthStart}
            onAssignShift={assignShift}
            onClearShift={clearShift}
            onImportSmartPss={importSmartPssAttendance}
            onDepartmentChange={setAttendanceDepartmentId}
          />
        )
      case 'payroll':
        return (
          <PayrollHub
            data={payrollHub}
            monthValue={payrollMonth}
            departmentId={payrollDepartmentId}
            onMonthChange={setPayrollMonth}
            onDepartmentChange={setPayrollDepartmentId}
            onGenerateDraft={generatePayrollDraft}
            onMarkPaid={markPaid}
          />
        )
      case 'leave':
        return <LeaveCalculator data={leaveData} onSubmit={submitLeaveRequest} />
      case 'ats':
        return (
          <div className="space-y-6">
            <VacancyManager data={vacancyData} canManage={canManageRecruitment} onSave={saveVacancy} />
            <AtsBoard
              board={atsBoard}
              busy={atsBusy}
              canManage={canManageRecruitment}
              onMoveCard={moveAtsCard}
              onScheduleInterview={scheduleAtsInterview}
            />
          </div>
        )
      case 'assets':
        return <WarehousePanel data={warehouseData} onSaveItem={saveInventoryItem} onAssign={assignInventoryItem} />
      case 'org_chart':
        return <OrgChartPanel data={orgChart} />
      case 'okrs':
        return <PerformanceHub data={performanceHub} onCreateObjective={createObjective} />
      case 'team_chat':
        return <TeamChat config={teamChatConfig} />
      case 'settings':
        return (
          <SettingsCategorizedLayout onOpenIntegrations={() => setActiveSection('integrations')}>
            <SystemConfigPanel
              data={systemConfig}
              onSaveConfig={saveSystemConfig}
              onSaveRoles={saveEmployeeRoles}
              onSaveRolePermissions={saveRolePermissions}
              onSaveScheduleManagers={saveScheduleManagers}
              onSaveEmployeeEditors={saveEmployeeEditors}
              onSaveLeavePolicies={saveLeavePolicies}
              onSaveSubscriptions={saveSubscriptions}
              onSaveWorksites={saveWorksites}
              onCreateMiddlewareKey={createMiddlewareKey}
              onRevokeMiddlewareKey={revokeMiddlewareKey}
              onCreateTenant={createTenant}
              onSaveDomain={saveTenantDomain}
            />
            <div id="settings-devices" className="scroll-mt-6">
              <DeviceRegistryPanel
                data={deviceRegistry}
                legalEntityId={options?.legal_entity_id ?? ''}
                onSave={saveDeviceRegistryItem}
              />
            </div>
          </SettingsCategorizedLayout>
        )
      case 'integrations':
        return (
          <IntegrationsPanel
            data={integrationsOverview}
            busy={integrationBusy}
            onConnectGoogleCalendar={() => void connectGoogleCalendar()}
            onDisconnectGoogleCalendar={() => void disconnectGoogleCalendar()}
            onConnectSlack={() => void connectSlack()}
            onDisconnectSlack={() => void disconnectSlack()}
          />
        )
      case 'support':
        return <SupportPanel />
      default:
        return null
    }
  }

  if (typeof window !== 'undefined') {
    const path = window.location.pathname
    if (path === '/careers' || path.startsWith('/careers/')) {
      return <PublicCareers />
    }
  }

  if (!token) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-50 px-6 py-12">
        <section className="grid w-full max-w-xl gap-4 rounded-[28px] border border-slate-200 bg-white p-8 shadow-panel">
          <div>
            <p className="text-xs uppercase tracking-[0.34em] text-slate-400">{bootstrap?.tenant.trade_name ?? 'ITGS HR'}</p>
            <h1 className="mt-3 text-3xl font-semibold text-slate-950">
              {authScreen === 'invite'
                ? 'Complete Registration'
                : authScreen === 'reset'
                  ? 'Reset Password'
                  : authScreen === 'forgot'
                    ? 'Forgot Password'
                    : ka.login}
            </h1>
            <p className="mt-2 text-sm text-slate-500">
              {authScreen === 'invite'
                ? 'Finish your employee registration, set a private password, and activate your self-service portal.'
                : authScreen === 'reset'
                  ? 'Choose a new secure password for your HRMS account.'
                  : authScreen === 'forgot'
                    ? 'Enter your work email or username and we will send you a reset link.'
                    : 'Sign in to your HRMS workspace, approvals, attendance, and self-service portal.'}
            </p>
          </div>

          {authScreen === 'invite' ? (
            <>
              <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 text-sm text-slate-700">
                <p className="font-semibold text-slate-900">{invitePreview?.full_name || invitePreview?.email || 'Pending employee invitation'}</p>
                <p className="mt-1">{invitePreview?.email ?? 'Email unavailable'}</p>
                <p className="mt-2 text-slate-500">
                  {[invitePreview?.department_name, invitePreview?.job_role_title, invitePreview?.manager_name ? `Manager: ${invitePreview.manager_name}` : null]
                    .filter(Boolean)
                    .join(' / ')}
                </p>
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <input
                  className="input-shell"
                  value={inviteRegistration.personalNumber}
                  onChange={(event) => setInviteRegistration((current) => ({ ...current, personalNumber: event.target.value }))}
                  placeholder="Personal ID"
                />
                <input
                  className="input-shell"
                  value={inviteRegistration.mobilePhone}
                  onChange={(event) => setInviteRegistration((current) => ({ ...current, mobilePhone: event.target.value }))}
                  placeholder="Phone Number"
                />
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <input
                  className="input-shell"
                  type="password"
                  value={inviteRegistration.password}
                  onChange={(event) => setInviteRegistration((current) => ({ ...current, password: event.target.value }))}
                  placeholder="Create Password"
                />
                <input
                  className="input-shell"
                  type="password"
                  value={inviteRegistration.confirmPassword}
                  onChange={(event) => setInviteRegistration((current) => ({ ...current, confirmPassword: event.target.value }))}
                  placeholder="Confirm Password"
                />
              </div>
              <label className="grid gap-2 text-sm text-slate-600">
                <span>Profile Photo (optional)</span>
                <input
                  className="input-shell"
                  type="file"
                  accept="image/*"
                  onChange={(event) => setInviteRegistration((current) => ({ ...current, profilePhoto: event.target.files?.[0] ?? null }))}
                />
              </label>
              <button className="primary-btn" onClick={() => void handleInviteCompletion()} disabled={authBusy}>
                {authBusy ? 'Processing...' : 'Complete Registration'}
              </button>
            </>
          ) : authScreen === 'reset' ? (
            <>
              {resetPreview ? (
                <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 text-sm text-slate-700">
                  <p className="font-semibold text-slate-900">{resetPreview.full_name || resetPreview.email || 'Password reset'}</p>
                  <p className="mt-1">{resetPreview.email ?? 'Email unavailable'}</p>
                </div>
              ) : null}
              <input
                className="input-shell"
                type="password"
                value={resetPasswordState.password}
                onChange={(event) => setResetPasswordState((current) => ({ ...current, password: event.target.value }))}
                placeholder="New Password"
              />
              <input
                className="input-shell"
                type="password"
                value={resetPasswordState.confirmPassword}
                onChange={(event) => setResetPasswordState((current) => ({ ...current, confirmPassword: event.target.value }))}
                placeholder="Confirm New Password"
              />
              <div className="flex flex-wrap gap-3">
                <button className="primary-btn" onClick={() => void handleResetPassword()} disabled={authBusy}>
                  {authBusy ? 'Processing...' : 'Save New Password'}
                </button>
                <button
                  type="button"
                  className="muted-btn"
                  onClick={() => {
                    clearAuthQueryTokens()
                    setResetToken('')
                    setResetPreview(null)
                    setAuthScreen('login')
                    setAuthError('')
                  }}
                >
                  Back to Login
                </button>
              </div>
            </>
          ) : authScreen === 'forgot' ? (
            <>
              <input
                className="input-shell"
                value={forgotUsernameOrEmail}
                onChange={(event) => setForgotUsernameOrEmail(event.target.value)}
                placeholder="Work Email or Username"
              />
              <div className="flex flex-wrap gap-3">
                <button className="primary-btn" onClick={() => void handleForgotPassword()} disabled={authBusy}>
                  {authBusy ? 'Sending...' : 'Send Reset Email'}
                </button>
                <button type="button" className="muted-btn" onClick={() => { setAuthScreen('login'); setAuthNotice(''); setAuthError('') }}>
                  Back to Login
                </button>
              </div>
            </>
          ) : (
            <>
              <input className="input-shell" value={loginState.username} onChange={(event) => setLoginState((current) => ({ ...current, username: event.target.value }))} placeholder={ka.username} />
              <input className="input-shell" type="password" value={loginState.password} onChange={(event) => setLoginState((current) => ({ ...current, password: event.target.value }))} placeholder={ka.password} />
              <button className="primary-btn" onClick={() => void handleLogin()}>
                {ka.login}
              </button>
              <button type="button" className="text-left text-sm font-medium text-blue-700 hover:text-blue-800" onClick={() => { setAuthScreen('forgot'); setAuthError(''); setAuthNotice('') }}>
                Forgot Password?
              </button>
            </>
          )}

          {authNotice ? <p className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 break-words whitespace-pre-wrap">{authNotice}</p> : null}
          {authError ? <p className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-600 break-words whitespace-pre-wrap">{authError}</p> : null}
        </section>
      </main>
    )
  }

  return (
    <div
      className="min-h-screen bg-[var(--page-bg)] p-3 sm:p-4"
      style={
        {
          ['--brand-primary' as string]: branding.primaryColor,
          ['--brand-primary-rgb' as string]: branding.primaryRgb
        } as CSSProperties
      }
    >
      {mobileMenuOpen ? (
        <button
          type="button"
          className="fixed inset-0 z-40 bg-slate-950/60 lg:hidden"
          aria-label="დახურვა"
          onClick={() => setMobileMenuOpen(false)}
        />
      ) : null}
      <Sidebar
        collapsed={sidebarCollapsed}
        activeKey={activeSection}
        branding={branding}
        featureFlags={featureFlags}
        allowedSections={allowedSections}
        mobileOpen={mobileMenuOpen}
        onCloseMobile={() => setMobileMenuOpen(false)}
        onSelect={(key) => setActiveSection(key as AppSection)}
        onToggle={() => setSidebarCollapsed((current) => !current)}
        onLogout={() => {
          logout()
          setCurrentUser(null)
          setToken('')
        }}
      />

      <div
        className={classNames(
          'page-layout-card min-h-[calc(100vh-24px)] transition-[margin] duration-300',
          sidebarCollapsed ? 'lg:ml-[100px]' : 'lg:ml-[280px]'
        )}
      >
      <main className="flex min-w-0 flex-1 flex-col overflow-hidden bg-transparent">
        <header className="topbar-shell dashboard-topbar shrink-0">
          <div className="flex justify-between gap-4 px-4 py-5 sm:px-6 sm:py-6">
            <div className="flex min-w-0 items-start gap-3">
              <button
                type="button"
                className={classNames(
                  'rounded-xl border p-2.5 lg:hidden',
                  'border-white/12 bg-white/[0.08] text-slate-100'
                )}
                onClick={() => setMobileMenuOpen(true)}
              >
                <Menu className="h-5 w-5" />
              </button>
              <div className="min-w-0">
                <p className="dashboard-kicker text-[12px] font-semibold uppercase tracking-[0.28em]">
                  {activeSection === 'dashboard' ? 'სამუშაო ძალის მართვის ცენტრი' : sectionCopy[activeSection].subtitle}
                </p>
                <h1 className={classNames(
                  'dashboard-title mt-3 font-semibold tracking-[-0.05em]',
                  activeSection === 'dashboard' ? 'text-[34px]' : 'text-[30px]'
                )}>
                  {sectionCopy[activeSection].title}
                </h1>
                <p className="dashboard-copy mt-3 max-w-3xl text-sm leading-6">
                  {activeSection === 'dashboard'
                    ? `${sectionCopy[activeSection].subtitle}. ${branding.companyName}-ის მიმოხილვა ${topBarDate}-ისთვის, მიმდინარე აქტივობით, დამტკიცებებით და დაგეგმვით.`
                    : `${branding.companyName} · ${topBarRole} · ${topBarDate}. ${sectionCopy[activeSection].subtitle}.`}
                </p>
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-2 sm:gap-3">
                <div className="hidden text-slate-200 sm:flex sm:flex-col sm:text-right sm:text-xs">
                {isTopCheckedIn ? `Checked in ${formatDuration(topElapsedSeconds)}` : 'Checked out'}
                <span className="mt-1 text-[11px] text-slate-300">
                  Today {formatDuration((webPunchData?.status_summary?.completed_work_seconds_today ?? 0) + topElapsedSeconds)}
                </span>
              </div>
              <button type="button" className="primary-btn px-3 py-2.5 text-sm sm:px-5" onClick={() => void headerWebCheckIn()}>
                <Fingerprint className="h-4 w-4" />
                <span className="hidden sm:inline">{topWebPunchButtonLabel}</span>
                <span className="sm:hidden">{isTopCheckedIn ? 'Check-Out' : 'Check-In'}</span>
              </button>
            </div>
          </div>
        </header>

        <div className="page-shell">
          {renderSection()}

          <footer className="mt-10 border-t border-slate-100 pt-6 text-center text-xs leading-relaxed text-slate-500">
            <p>Made by Nika Datiashvili, Designed by Tamta Modebadze, Supported by ITGS Sulkhan Sulkhanishvili.</p>
            <p className="mt-1">© 2026 ITGS HR. All Rights Reserved.</p>
          </footer>
        </div>
      </main>
      </div>

      <ToastStack items={toasts} onDismiss={(id) => setToasts((rows) => rows.filter((row) => row.id !== id))} />

      <EmployeeDrawer
        open={drawerOpen}
        mode={drawerMode}
        draft={draft}
        options={options}
        syncedDevices={drawerSyncedDevices}
        permissions={employeeFormPermissions}
        activeTab={drawerTab}
        selectedPhoto={draftPhoto}
        onChangeTab={setDrawerTab}
        onDraftChange={setDraft}
        onPhotoChange={setDraftPhoto}
        onClose={() => {
          setDrawerOpen(false)
          setDraftPhoto(null)
          setDrawerSyncedDevices([])
        }}
        onSubmit={() => void submitEmployee()}
        onCreateDepartment={createDepartment}
        onEnrollCard={enrollEmployeeCard}
      />

      <MessageComposerModal
        open={messageTarget !== null}
        targetName={messageTarget?.employeeName ?? ''}
        availableChannels={availableMessageChannels}
        busy={messageSending}
        onClose={() => setMessageTarget(null)}
        onSend={(payload) => void sendDirectMessage(payload)}
      />

      <AttendanceModal
        open={attendanceOpen}
        employeeName={attendanceEmployeeName}
        rows={attendanceRows}
        onClose={() => setAttendanceOpen(false)}
      />

      {employeeInviteResult ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 px-4 py-6">
          <div className="w-full max-w-xl rounded-2xl bg-white p-6 shadow-2xl shadow-slate-950/20">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="section-kicker">Employee Invite</p>
                <h2 className="mt-2 text-xl font-semibold text-slate-950">Registration Link Created</h2>
              </div>
              <button type="button" className="muted-btn px-3 py-2 text-sm" onClick={() => setEmployeeInviteResult(null)}>
                Close
              </button>
            </div>
            <div className="mt-5 space-y-4 text-sm text-slate-600">
              <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
                <p className="text-xs uppercase tracking-[0.18em] text-slate-400">Username</p>
                <p className="mt-1 font-semibold text-slate-900">{employeeInviteResult.username}</p>
              </div>
              <div>
                <p className="mb-2 text-xs uppercase tracking-[0.18em] text-slate-400">Invite Link</p>
                <input className="input-shell w-full" value={employeeInviteResult.invite_link} readOnly />
              </div>
              {employeeInviteResult.invite_email_status === 'sent' ? (
                <p className="rounded-xl bg-emerald-50 px-4 py-3 text-emerald-700">Invite email was sent.</p>
              ) : employeeInviteResult.invite_email_status === 'failed' ? (
                <p className="rounded-xl bg-amber-50 px-4 py-3 text-amber-700">
                  Invite link was created, but email delivery failed: {employeeInviteResult.invite_email_error ?? 'SMTP delivery error'}
                </p>
              ) : (
                <p className="rounded-xl bg-slate-50 px-4 py-3 text-slate-600">Invite link was created. SMTP is not configured, so no email was sent.</p>
              )}
            </div>
          </div>
        </div>
      ) : null}

      <ConfirmActionModal
        open={pendingEmployeeAction !== null}
        title={employeeActionCopy.title}
        body={employeeActionCopy.body}
        confirmLabel={employeeActionCopy.confirmLabel}
        busy={employeeActionBusy}
        tone={employeeActionCopy.tone}
        onClose={() => {
          if (!employeeActionBusy) {
            setPendingEmployeeAction(null)
          }
        }}
        onConfirm={() => void confirmEmployeeAction()}
      />

      <HardwareSyncModal
        open={syncOpen}
        employee={syncEmployee}
        devices={options?.devices ?? []}
        selectedDeviceIds={selectedDeviceIds}
        onToggleDevice={(deviceId) =>
          setSelectedDeviceIds((current) =>
            current.includes(deviceId) ? current.filter((item) => item !== deviceId) : [...current, deviceId]
          )
        }
        onSelectAll={() => setSelectedDeviceIds(options?.devices?.map((device) => device.id) ?? [])}
        onClearAll={() => setSelectedDeviceIds([])}
        onClose={() => setSyncOpen(false)}
        onSubmit={() => void submitSync()}
      />
    </div>
  )
}
