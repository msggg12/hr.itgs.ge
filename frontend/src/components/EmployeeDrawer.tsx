import { useEffect, useMemo, useRef, useState } from 'react'

import { Building2, Camera, ChevronRight, CreditCard, DollarSign, Fingerprint, LoaderCircle, PlusCircle, Users, X } from 'lucide-react'

import { ka } from '../i18n/ka'
import type { EmployeeDraft, EmployeeFormOptions, OptionItem } from '../types'
import { classNames, validateEmployeeDraft } from '../utils'

type DrawerTab = 'personal' | 'salary' | 'device'

type EmployeeDrawerProps = {
  open: boolean
  mode: 'create' | 'edit'
  draft: EmployeeDraft
  options: EmployeeFormOptions | null
  syncedDevices: OptionItem[]
  permissions: {
    can_edit: boolean
    can_view_salary: boolean
    can_sync_devices: boolean
    can_create_department: boolean
  }
  activeTab: DrawerTab
  selectedPhoto: File | null
  onChangeTab: (tab: DrawerTab) => void
  onDraftChange: (draft: EmployeeDraft) => void
  onPhotoChange: (file: File | null) => void
  onClose: () => void
  onSubmit: () => void
  onCreateDepartment: (payload: { name_ka: string; name_en: string }) => Promise<{ id: string; name_ka: string; name_en: string }>
  onEnrollCard: (payload: { employeeId: string; deviceId: string; cardNumber: string }) => Promise<void>
}

function FieldError(props: { message?: string }) {
  if (!props.message) {
    return null
  }
  return <p className="mt-2 text-xs font-medium text-rose-600">{props.message}</p>
}

const defaultDrawerPermissions = {
  can_edit: false,
  can_view_salary: false,
  can_sync_devices: false,
  can_create_department: false,
}

function DrawerTabs(props: { activeTab: DrawerTab; availableTabs: DrawerTab[]; onChange: (tab: DrawerTab) => void }) {
  const tabMap: Record<DrawerTab, { label: string; icon: typeof Users }> = {
    personal: { label: ka.personalInfo, icon: Users },
    salary: { label: ka.salaryInfo, icon: DollarSign },
    device: { label: ka.biometricAssignment, icon: Fingerprint },
  }

  return (
    <div className="flex gap-2 rounded-lg bg-slate-100 p-1">
      {props.availableTabs.map((tabKey) => {
        const tab = tabMap[tabKey]
        const Icon = tab.icon
        const active = props.activeTab === tabKey
        return (
          <button
            key={tabKey}
            type="button"
            onClick={() => props.onChange(tabKey)}
            className={classNames(
              'flex flex-1 items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold transition',
              active ? 'bg-white text-slate-950 ring-1 ring-slate-200' : 'text-slate-500 hover:text-slate-900'
            )}
          >
            <Icon className="h-4 w-4" />
            {tab.label}
          </button>
        )
      })}
    </div>
  )
}

export function EmployeeDrawer(props: EmployeeDrawerProps) {
  const errors = validateEmployeeDraft(props.draft, props.mode)
  const hasErrors = Object.keys(errors).length > 0
  const [previewUrl, setPreviewUrl] = useState('')
  const [rolePanelOpen, setRolePanelOpen] = useState(false)
  const [departmentPanelOpen, setDepartmentPanelOpen] = useState(false)
  const [departmentDraft, setDepartmentDraft] = useState({ name_ka: '', name_en: '' })
  const [departmentBusy, setDepartmentBusy] = useState(false)
  const [departmentError, setDepartmentError] = useState('')
  const [cardModalOpen, setCardModalOpen] = useState(false)
  const [enrollmentDeviceId, setEnrollmentDeviceId] = useState('')
  const [enrollmentCardNumber, setEnrollmentCardNumber] = useState('')
  const [enrollmentBusy, setEnrollmentBusy] = useState(false)
  const [enrollmentNotice, setEnrollmentNotice] = useState('')
  const keyBufferRef = useRef('')
  const keyTimerRef = useRef<number | null>(null)

  const permissions = props.permissions ?? defaultDrawerPermissions
  const syncedDevices = props.syncedDevices ?? []
  const availableTabs: DrawerTab[] = [
    'personal',
    ...(permissions.can_view_salary ? (['salary'] as DrawerTab[]) : []),
    ...(props.mode === 'edit' && permissions.can_sync_devices ? (['device'] as DrawerTab[]) : []),
  ]

  const syncedDeviceIds = useMemo(() => new Set(syncedDevices.map((device) => device.id)), [syncedDevices])

  useEffect(() => {
    if (!props.selectedPhoto) {
      setPreviewUrl('')
      return
    }
    const nextUrl = URL.createObjectURL(props.selectedPhoto)
    setPreviewUrl(nextUrl)
    return () => URL.revokeObjectURL(nextUrl)
  }, [props.selectedPhoto])

  useEffect(() => {
    if (props.open) {
      setRolePanelOpen(Boolean(props.draft.new_job_role_title_ka || props.draft.new_job_role_title_en))
    }
  }, [props.open, props.draft.new_job_role_title_ka, props.draft.new_job_role_title_en])

  useEffect(() => {
    if (props.open && !availableTabs.includes(props.activeTab)) {
      props.onChangeTab('personal')
    }
  }, [availableTabs, props.activeTab, props.onChangeTab, props.open])

  useEffect(() => {
    if (!props.open) {
      setDepartmentPanelOpen(false)
      setDepartmentDraft({ name_ka: '', name_en: '' })
      setDepartmentError('')
      setDepartmentBusy(false)
      setCardModalOpen(false)
      setEnrollmentCardNumber('')
      setEnrollmentNotice('')
      setEnrollmentBusy(false)
    }
  }, [props.open])

  useEffect(() => {
    if (!cardModalOpen) {
      return
    }
    function commitCardValue() {
      const normalized = keyBufferRef.current.replace(/\D/g, '')
      keyBufferRef.current = ''
      if (normalized) {
        setEnrollmentCardNumber(normalized)
        setEnrollmentNotice('Card ID captured from USB reader.')
      }
      if (keyTimerRef.current) {
        window.clearTimeout(keyTimerRef.current)
        keyTimerRef.current = null
      }
    }
    function handleKeydown(event: KeyboardEvent) {
      if (event.key === 'Enter' || event.key === 'Tab') {
        event.preventDefault()
        commitCardValue()
        return
      }
      if (!/^[0-9]$/.test(event.key)) {
        return
      }
      keyBufferRef.current += event.key
      if (keyTimerRef.current) {
        window.clearTimeout(keyTimerRef.current)
      }
      keyTimerRef.current = window.setTimeout(() => {
        commitCardValue()
      }, 120)
    }
    window.addEventListener('keydown', handleKeydown)
    return () => {
      window.removeEventListener('keydown', handleKeydown)
      if (keyTimerRef.current) {
        window.clearTimeout(keyTimerRef.current)
        keyTimerRef.current = null
      }
      keyBufferRef.current = ''
    }
  }, [cardModalOpen])

  if (!props.open) {
    return null
  }

  const managerLabel = props.options?.managers?.find((manager) => manager.id === props.draft.manager_employee_id)?.full_name ?? props.draft.manager_name ?? ''
  const photoUrl = previewUrl || props.draft.profile_photo_url || ''
  const showNewRolePanel = rolePanelOpen || Boolean(props.draft.new_job_role_title_ka || props.draft.new_job_role_title_en)

  async function handleCreateDepartment() {
    if (!departmentDraft.name_ka.trim()) {
      setDepartmentError(ka.departmentNameKaRequired)
      return
    }
    setDepartmentBusy(true)
    try {
      const department = await props.onCreateDepartment({
        name_ka: departmentDraft.name_ka.trim(),
        name_en: departmentDraft.name_en.trim(),
      })
      props.onDraftChange({ ...props.draft, department_id: department.id })
      setDepartmentDraft({ name_ka: '', name_en: '' })
      setDepartmentPanelOpen(false)
      setDepartmentError('')
    } catch (err) {
      setDepartmentError((err as Error).message)
    } finally {
      setDepartmentBusy(false)
    }
  }

  async function handleEnrollCard() {
    if (!props.draft.id || !enrollmentDeviceId || !enrollmentCardNumber.trim()) {
      setEnrollmentNotice('Select a device and scan a card first.')
      return
    }
    setEnrollmentBusy(true)
    try {
      await props.onEnrollCard({
        employeeId: props.draft.id,
        deviceId: enrollmentDeviceId,
        cardNumber: enrollmentCardNumber.trim()
      })
      setEnrollmentNotice('Card enrolled successfully.')
      setCardModalOpen(false)
      setEnrollmentCardNumber('')
    } finally {
      setEnrollmentBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-slate-950/45">
      <div className="h-full w-full max-w-2xl overflow-y-auto border-l border-slate-200 bg-white px-6 py-6 shadow-panel">
        <div className="mb-5 flex items-center justify-between">
          <div>
            <p className="text-xs uppercase tracking-[0.24em] text-slate-400">{props.mode === 'create' ? 'Invite Employee' : ka.editEmployee}</p>
            <h2 className="mt-2 text-2xl font-semibold text-slate-950">{props.mode === 'create' ? 'Send Registration Invite' : ka.editEmployee}</h2>
          </div>
          <button type="button" className="rounded-lg border border-slate-200 p-3 text-slate-500 transition hover:bg-slate-50" onClick={props.onClose}>
            <ChevronRight className="h-4 w-4 rotate-180" />
          </button>
        </div>

        <DrawerTabs activeTab={props.activeTab} availableTabs={availableTabs} onChange={props.onChangeTab} />

        <div className="mt-6 grid gap-4">
          {props.activeTab === 'personal' ? (
            <div className="grid gap-4">
              {props.mode === 'edit' ? (
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                  <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
                    <div className="flex h-24 w-24 items-center justify-center overflow-hidden rounded-xl border border-slate-200 bg-white">
                      {photoUrl ? (
                        <img src={photoUrl} alt="Employee profile" className="h-full w-full object-cover" />
                      ) : (
                        <Camera className="h-6 w-6 text-slate-300" />
                      )}
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-semibold text-slate-950">{ka.profilePhoto}</p>
                      <p className="mt-1 text-sm text-slate-500">{ka.profilePhotoHint}</p>
                      <div className="mt-3 flex flex-wrap gap-3">
                        <label className="primary-btn cursor-pointer">
                          <input
                            type="file"
                            accept=".jpg,.jpeg,image/jpeg"
                            className="hidden"
                            onChange={(event) => props.onPhotoChange(event.target.files?.[0] ?? null)}
                          />
                          {ka.uploadJpg}
                        </label>
                        {props.selectedPhoto ? (
                          <button type="button" className="muted-btn" onClick={() => props.onPhotoChange(null)}>
                            {ka.clearPhoto}
                          </button>
                        ) : null}
                      </div>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-900">
                  HR now sends an invite instead of creating the full profile manually. The employee will finish their own registration, set a password, and upload a photo later from the secure invite link.
                </div>
              )}

              <div className="grid gap-4 md:grid-cols-2">
                {props.mode === 'edit' ? (
                  <>
                    <div>
                      <input className="input-shell" placeholder={ka.employeeNumber} value={props.draft.employee_number} onChange={(event) => props.onDraftChange({ ...props.draft, employee_number: event.target.value })} disabled={props.mode === 'edit'} />
                      <FieldError message={errors.employee_number} />
                    </div>
                    <div>
                      <input className="input-shell" placeholder={ka.personalNumber} value={props.draft.personal_number} onChange={(event) => props.onDraftChange({ ...props.draft, personal_number: event.target.value })} disabled={props.mode === 'edit'} />
                      <FieldError message={errors.personal_number} />
                    </div>
                    <div>
                      <input className="input-shell" placeholder={ka.name} value={props.draft.first_name} onChange={(event) => props.onDraftChange({ ...props.draft, first_name: event.target.value })} />
                      <FieldError message={errors.first_name} />
                    </div>
                    <div>
                      <input className="input-shell" placeholder={ka.fullName} value={props.draft.last_name} onChange={(event) => props.onDraftChange({ ...props.draft, last_name: event.target.value })} />
                      <FieldError message={errors.last_name} />
                    </div>
                  </>
                ) : null}
                <div>
                  <input className="input-shell" placeholder={ka.email} value={props.draft.email} onChange={(event) => props.onDraftChange({ ...props.draft, email: event.target.value })} />
                  <FieldError message={errors.email} />
                </div>
                {props.mode === 'edit' ? (
                  <>
                    <div>
                      <input className="input-shell" placeholder={ka.phone} value={props.draft.mobile_phone} onChange={(event) => props.onDraftChange({ ...props.draft, mobile_phone: event.target.value })} />
                      <FieldError message={errors.mobile_phone} />
                    </div>
                    <input className="input-shell" type="date" value={props.draft.hire_date} onChange={(event) => props.onDraftChange({ ...props.draft, hire_date: event.target.value })} disabled={props.mode === 'edit'} />
                  </>
                ) : (
                  <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
                    The employee will provide personal ID, phone number, and password from the invite link.
                  </div>
                )}
                <div className="grid gap-3">
                  <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
                    <select className="input-shell" value={props.draft.department_id} onChange={(event) => props.onDraftChange({ ...props.draft, department_id: event.target.value })}>
                      <option value="">{ka.departmentSelect}</option>
                      {props.options?.departments?.map((department) => (
                        <option key={department.id} value={department.id}>{department.name_ka ?? department.name_en}</option>
                      ))}
                    </select>
                    {permissions.can_create_department ? (
                      <button type="button" className="muted-btn" onClick={() => setDepartmentPanelOpen((current) => !current)}>
                        <Building2 className="h-4 w-4" />
                        Add Department
                      </button>
                    ) : null}
                  </div>
                  {departmentPanelOpen ? (
                    <div className="grid gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4">
                      <input
                        className="input-shell"
                        placeholder={ka.departmentNameKa}
                        value={departmentDraft.name_ka}
                        onChange={(event) => setDepartmentDraft((current) => ({ ...current, name_ka: event.target.value }))}
                      />
                      <input
                        className="input-shell"
                        placeholder={ka.departmentNameEn}
                        value={departmentDraft.name_en}
                        onChange={(event) => setDepartmentDraft((current) => ({ ...current, name_en: event.target.value }))}
                      />
                      {departmentError ? <p className="text-xs font-medium text-rose-600">{departmentError}</p> : null}
                      <div className="flex flex-wrap gap-2">
                        <button type="button" className="primary-btn" onClick={() => void handleCreateDepartment()} disabled={departmentBusy}>
                          {departmentBusy ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <PlusCircle className="h-4 w-4" />}
                          {ka.saveDepartment}
                        </button>
                        <button type="button" className="muted-btn" onClick={() => setDepartmentPanelOpen(false)}>
                          {ka.cancel}
                        </button>
                      </div>
                    </div>
                  ) : null}
                </div>

                <div className="md:col-span-2">
                  <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
                    <select className="input-shell" value={props.draft.job_role_id} onChange={(event) => props.onDraftChange({ ...props.draft, job_role_id: event.target.value })}>
                      <option value="">{ka.jobRoleSelect}</option>
                      {props.options?.job_roles?.map((role) => (
                        <option key={role.id} value={role.id}>{role.title_ka ?? role.title_en}</option>
                      ))}
                    </select>
                    <button type="button" className="muted-btn" onClick={() => setRolePanelOpen(true)}>
                      <PlusCircle className="h-4 w-4" />
                      {ka.addPosition}
                    </button>
                  </div>
                  {showNewRolePanel ? (
                    <div className="mt-3 grid gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4 md:grid-cols-2">
                      <input className="input-shell" placeholder={ka.newPositionKa} value={props.draft.new_job_role_title_ka} onChange={(event) => props.onDraftChange({ ...props.draft, new_job_role_title_ka: event.target.value })} />
                      <input className="input-shell" placeholder="New position in English" value={props.draft.new_job_role_title_en} onChange={(event) => props.onDraftChange({ ...props.draft, new_job_role_title_en: event.target.value })} />
                      <label className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700 md:col-span-2">
                        <input type="checkbox" checked={props.draft.new_job_role_is_managerial} onChange={(event) => props.onDraftChange({ ...props.draft, new_job_role_is_managerial: event.target.checked })} />
                        {ka.managerialRoleLabel}
                      </label>
                    </div>
                  ) : null}
                </div>

                <div className="md:col-span-2">
                  <select className="input-shell" value={props.draft.manager_employee_id} onChange={(event) => props.onDraftChange({ ...props.draft, manager_employee_id: event.target.value })}>
                    <option value="">{ka.managerSelect}</option>
                    {props.options?.managers?.map((manager) => (
                      <option key={manager.id} value={manager.id}>{manager.full_name}</option>
                    ))}
                  </select>
                  <p className="mt-2 text-sm text-slate-500">
                    {managerLabel ? `${ka.managerSummary}: ${managerLabel}` : ka.managerHint}
                  </p>
                </div>
              </div>
            </div>
          ) : null}

          {props.activeTab === 'salary' && permissions.can_view_salary ? (
            <div className="grid gap-4 md:grid-cols-2">
              <select className="input-shell" value={props.draft.salary_type} onChange={(event) => props.onDraftChange({ ...props.draft, salary_type: event.target.value })}>
                <option value="monthly_fixed">Monthly Fixed</option>
                <option value="hourly">Hourly</option>
              </select>
              <input className="input-shell" placeholder={ka.salary} value={props.draft.base_salary} onChange={(event) => props.onDraftChange({ ...props.draft, base_salary: event.target.value })} />
              <input className="input-shell" placeholder={props.draft.salary_type === 'hourly' ? 'Hourly rate override (optional)' : ka.hourlyRate} value={props.draft.hourly_rate_override} onChange={(event) => props.onDraftChange({ ...props.draft, hourly_rate_override: event.target.value })} />
              <select className="input-shell md:col-span-2" value={props.draft.pay_policy_id} onChange={(event) => props.onDraftChange({ ...props.draft, pay_policy_id: event.target.value })}>
                {props.options?.pay_policies?.map((policy) => (
                  <option key={policy.id} value={policy.id}>{policy.code} - {policy.name}</option>
                ))}
              </select>
              <label className="flex items-center gap-3 rounded-lg border border-slate-200 px-4 py-3 text-sm text-slate-700 md:col-span-2">
                <input type="checkbox" checked={props.draft.is_pension_participant} onChange={(event) => props.onDraftChange({ ...props.draft, is_pension_participant: event.target.checked })} />
                {ka.pensionParticipant}
              </label>
            </div>
          ) : null}

          {props.activeTab === 'device' && permissions.can_sync_devices ? (
            <div className="grid gap-4">
              <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                {ka.biometricsHint}
              </div>

              <input
                className="input-shell"
                placeholder={ka.deviceUserId}
                value={props.draft.default_device_user_id}
                onChange={(event) => props.onDraftChange({ ...props.draft, default_device_user_id: event.target.value })}
              />

              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  className="muted-btn"
                  onClick={() => {
                    setEnrollmentDeviceId(props.syncedDevices[0]?.id ?? props.options?.devices?.[0]?.id ?? '')
                    setEnrollmentNotice('Waiting for card reader input...')
                    setEnrollmentCardNumber('')
                    setCardModalOpen(true)
                  }}
                >
                  <CreditCard className="h-4 w-4" />
                  Enroll Card
                </button>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-950">{ka.activeDeviceAssignments}</p>
                    <p className="mt-1 text-sm text-slate-500">{props.syncedDevices.length} {ka.selectedDevices.toLowerCase()}</p>
                  </div>
                  <div className="rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-700">
                    {props.syncedDevices.length}
                  </div>
                </div>

                {props.syncedDevices.length === 0 ? (
                  <div className="mt-4 rounded-xl border border-dashed border-slate-300 bg-white px-4 py-8 text-center text-sm text-slate-500">
                    {ka.noActiveDeviceAssignments}
                  </div>
                ) : (
                  <div className="mt-4 grid gap-3">
                    {syncedDevices.map((device) => (
                      <div key={device.id} className="rounded-xl border border-emerald-200 bg-white px-4 py-3 shadow-sm">
                        <div className="flex items-center justify-between gap-3">
                          <div>
                            <p className="font-semibold text-slate-950">{device.device_name}</p>
                            <p className="mt-1 text-sm text-slate-500">{device.brand} - {device.host}</p>
                            {device.device_user_id ? (
                              <p className="mt-1 text-xs text-slate-400">{ka.deviceUserId}: {device.device_user_id}</p>
                            ) : null}
                            {device.card_number ? (
                              <p className="mt-1 text-xs font-semibold text-slate-600">Card: {device.card_number}</p>
                            ) : null}
                          </div>
                          <span className="rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-700">
                            {ka.syncedOnDevice}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="grid gap-3">
                {(props.options?.devices ?? []).map((device) => {
                  const isSynced = syncedDeviceIds.has(device.id)
                  return (
                    <div key={device.id} className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
                      <div className="flex items-center justify-between gap-4">
                        <div>
                          <p className="font-semibold text-slate-950">{device.device_name}</p>
                          <p className="mt-1 text-sm text-slate-500">{device.brand} - {device.host}</p>
                        </div>
                        <span className={classNames(
                          'rounded-full px-3 py-1 text-xs font-semibold',
                          isSynced ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-200 text-slate-600'
                        )}>
                          {isSynced ? ka.syncedOnDevice : ka.notSyncedOnDevice}
                        </span>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          ) : null}
        </div>

        {hasErrors ? (
          <div className="mt-6 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 break-words whitespace-pre-wrap">
            {ka.fixRequiredFields}
          </div>
        ) : null}

        <div className="mt-8 flex items-center justify-end gap-3">
          <button type="button" className="muted-btn" onClick={props.onClose}>
            {ka.cancel}
          </button>
          <button type="button" className="primary-btn" onClick={props.onSubmit} disabled={hasErrors}>
            {props.mode === 'create' ? 'Send Invite' : ka.save}
          </button>
        </div>
      </div>

      {cardModalOpen ? (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/55 px-4">
          <div className="w-full max-w-lg rounded-[28px] border border-slate-200 bg-white p-6 shadow-2xl">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-xs uppercase tracking-[0.28em] text-slate-400">Card Enrollment</p>
                <h3 className="mt-2 text-2xl font-semibold text-slate-950">Scan USB HID Card</h3>
                <p className="mt-2 text-sm text-slate-500">Keep this modal open and swipe the card on the USB reader. The numeric card ID will be captured automatically.</p>
              </div>
              <button type="button" className="rounded-full border border-slate-200 p-2 text-slate-500 hover:bg-slate-50" onClick={() => !enrollmentBusy && setCardModalOpen(false)}>
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="mt-6 grid gap-4">
              <select className="input-shell" value={enrollmentDeviceId} onChange={(event) => setEnrollmentDeviceId(event.target.value)}>
                <option value="">Select target device</option>
                {(props.options?.devices ?? []).map((device) => (
                  <option key={device.id} value={device.id}>
                    {device.device_name} - {device.brand}
                  </option>
                ))}
              </select>
              <input
                className="input-shell"
                placeholder="Card number will appear here"
                value={enrollmentCardNumber}
                onChange={(event) => setEnrollmentCardNumber(event.target.value.replace(/\D/g, ''))}
              />
              <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
                {enrollmentNotice || 'Waiting for card reader input...'}
              </div>
            </div>

            <div className="mt-6 flex items-center justify-end gap-3">
              <button type="button" className="muted-btn" onClick={() => setCardModalOpen(false)} disabled={enrollmentBusy}>
                Cancel
              </button>
              <button type="button" className="primary-btn" onClick={() => void handleEnrollCard()} disabled={enrollmentBusy || !enrollmentDeviceId || !enrollmentCardNumber}>
                {enrollmentBusy ? 'Enrolling...' : 'Save Card'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
