import type { EmployeeDraft, EmployeeFormOptions, FeedEvent, ShiftPattern, ShiftPatternSegment } from './types'

export function classNames(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ')
}

export function initials(firstName?: string | null, lastName?: string | null): string {
  return `${firstName?.[0] ?? ''}${lastName?.[0] ?? ''}`.toUpperCase() || 'HR'
}

export function formatDateTime(value: string | null): string {
  if (!value) {
    return '-'
  }
  return new Intl.DateTimeFormat('ka-GE', {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  }).format(new Date(value))
}

export function formatDate(value: string | null): string {
  if (!value) {
    return '-'
  }
  return new Intl.DateTimeFormat('ka-GE', {
    month: 'short',
    day: '2-digit'
  }).format(new Date(value))
}

export function formatMoney(value: string | number): string {
  const numeric = typeof value === 'number' ? value : Number(value)
  return new Intl.NumberFormat('ka-GE', {
    style: 'currency',
    currency: 'GEL',
    maximumFractionDigits: 0
  }).format(Number.isNaN(numeric) ? 0 : numeric)
}

export function formatHours(totalMinutes: number): string {
  const safeMinutes = Math.max(totalMinutes, 0)
  return `${(safeMinutes / 60).toFixed(1)} სთ`
}

export function eventTone(event: FeedEvent): string {
  if (event.device_status === 'offline') {
    return 'border-rose-300 bg-rose-50 text-rose-700'
  }
  if (event.direction === 'out') {
    return 'border-sky-300 bg-sky-50 text-sky-700'
  }
  return 'border-emerald-300 bg-emerald-50 text-emerald-700'
}

export function statusBadge(status: string): string {
  if (status === 'active') {
    return 'bg-emerald-100 text-emerald-700'
  }
  if (status === 'draft') {
    return 'bg-sky-100 text-sky-700'
  }
  if (status === 'suspended') {
    return 'bg-amber-100 text-amber-700'
  }
  return 'bg-slate-200 text-slate-700'
}

export function findShiftSegment(pattern: ShiftPattern | undefined, shiftDate: string): ShiftPatternSegment | null {
  if (!pattern) {
    return null
  }
  const selectedDate = new Date(`${shiftDate}T00:00:00`)
  if (Number.isNaN(selectedDate.getTime())) {
    return null
  }
  if (pattern.pattern_type === 'fixed_weekly') {
    const dayIndex = ((selectedDate.getDay() + 6) % 7) + 1
    return pattern.segments.find((segment) => segment.day_index === dayIndex) ?? null
  }
  return pattern.segments.find((segment) => segment.day_index === 1) ?? null
}

export function defaultDraft(options: EmployeeFormOptions | null): EmployeeDraft {
  return {
    legal_entity_id: options?.legal_entity_id ?? '',
    employee_number: '',
    personal_number: '',
    first_name: '',
    last_name: '',
    email: '',
    mobile_phone: '',
    department_id: options?.departments?.[0]?.id ?? '',
    job_role_id: options?.job_roles?.[0]?.id ?? '',
    manager_employee_id: '',
    hire_date: new Date().toISOString().slice(0, 10),
    salary_type: 'monthly_fixed',
    base_salary: '',
    pay_policy_id: options?.pay_policies?.[0]?.id ?? '',
    hourly_rate_override: '',
    is_pension_participant: true,
    default_device_user_id: '',
    manager_name: '',
    profile_photo_url: '',
    new_job_role_title_ka: '',
    new_job_role_title_en: '',
    new_job_role_is_managerial: false
  }
}

export type EmployeeDraftErrors = Partial<Record<'email' | 'personal_number' | 'mobile_phone' | 'first_name' | 'last_name' | 'employee_number', string>>

export function validateEmployeeDraft(draft: EmployeeDraft, mode: 'create' | 'edit' = 'edit'): EmployeeDraftErrors {
  const errors: EmployeeDraftErrors = {}
  const email = draft.email.trim()
  const personalNumberDigits = draft.personal_number.replace(/\D/g, '')
  const phoneDigits = draft.mobile_phone.replace(/\D/g, '')

  if (mode === 'edit' && !draft.employee_number.trim()) {
    errors.employee_number = 'Enter employee number'
  }
  if (mode === 'edit' && !draft.first_name.trim()) {
    errors.first_name = 'Enter first name'
  }
  if (mode === 'edit' && !draft.last_name.trim()) {
    errors.last_name = 'Enter last name'
  }
  if (mode === 'create' && !email) {
    errors.email = 'Enter work email'
  }
  if (email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
    errors.email = 'Enter a valid email address'
  }
  if (mode === 'edit' && draft.personal_number.trim() && personalNumberDigits.length !== 11) {
    errors.personal_number = 'Personal number must contain 11 digits'
  }
  if (mode === 'edit' && draft.mobile_phone.trim() && (phoneDigits.length < 9 || phoneDigits.length > 15)) {
    errors.mobile_phone = 'Phone number must contain 9 to 15 digits'
  }
  return errors
}
