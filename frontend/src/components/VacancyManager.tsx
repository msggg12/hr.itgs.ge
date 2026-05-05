import { useEffect, useMemo, useState } from 'react'

import { ExternalLink, FilePlus2, Link2, Save, Send } from 'lucide-react'

import type { VacancyData, VacancyFieldDefinition, VacancyItem } from '../types'

type VacancySaveResult = {
  vacancy_id: string
  public_slug: string
}

type VacancyManagerProps = {
  data: VacancyData | null
  canManage: boolean
  onSave: (vacancyId: string | null, payload: {
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
    application_form_schema: VacancyFieldDefinition[]
  }) => Promise<VacancySaveResult>
}

type VacancyFormState = {
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
  department_id: string
  job_role_id: string
  closes_at: string
  public_slug: string
  external_form_url: string
  is_public: boolean
  application_form_schema: VacancyFieldDefinition[]
}

const blankField = (): VacancyFieldDefinition => ({
  key: '',
  label: '',
  field_type: 'text',
  required: true,
  options: [],
})

const blankForm = (): VacancyFormState => ({
  posting_code: '',
  title_en: '',
  title_ka: '',
  description: '',
  public_description: '',
  employment_type: 'full_time',
  location_text: '',
  status: 'draft',
  open_positions: 1,
  salary_min: 0,
  salary_max: 0,
  department_id: '',
  job_role_id: '',
  closes_at: '',
  public_slug: '',
  external_form_url: '',
  is_public: true,
  application_form_schema: [blankField()],
})

function normalizeSchema(schema: unknown): VacancyFieldDefinition[] {
  if (!Array.isArray(schema)) {
    return [blankField()]
  }
  const fields = schema
    .filter((item): item is Partial<VacancyFieldDefinition> => Boolean(item) && typeof item === 'object')
    .map((item) => ({
      key: String(item.key ?? ''),
      label: String(item.label ?? ''),
      field_type: String(item.field_type ?? 'text'),
      required: item.required ?? true,
      options: Array.isArray(item.options) ? item.options : [],
    }))
  return fields.length ? fields : [blankField()]
}

export function VacancyManager(props: VacancyManagerProps) {
  const [selectedId, setSelectedId] = useState<string>('new')
  const [busy, setBusy] = useState(false)
  const [departmentSearch, setDepartmentSearch] = useState('')
  const [jobRoleSearch, setJobRoleSearch] = useState('')
  const [form, setForm] = useState<VacancyFormState>(blankForm)

  const selectedVacancy = useMemo(
    () => props.data?.items?.find((item) => item.id === selectedId) ?? null,
    [props.data?.items, selectedId],
  )

  useEffect(() => {
    if (!selectedVacancy) {
      setForm(blankForm())
      setDepartmentSearch('')
      setJobRoleSearch('')
      return
    }
    setDepartmentSearch(selectedVacancy.department_name ?? '')
    setJobRoleSearch(selectedVacancy.job_role_name ?? '')
    setForm({
      posting_code: selectedVacancy.posting_code,
      title_en: selectedVacancy.title_en,
      title_ka: selectedVacancy.title_ka,
      description: selectedVacancy.description,
      public_description: selectedVacancy.public_description ?? selectedVacancy.description,
      employment_type: selectedVacancy.employment_type,
      location_text: selectedVacancy.location_text ?? '',
      status: selectedVacancy.status,
      open_positions: selectedVacancy.open_positions,
      salary_min: selectedVacancy.salary_min ?? 0,
      salary_max: selectedVacancy.salary_max ?? 0,
      department_id: props.data?.departments?.find((item) => item.name_en === selectedVacancy.department_name || item.name_ka === selectedVacancy.department_name)?.id ?? '',
      job_role_id: props.data?.job_roles?.find((item) => item.title_en === selectedVacancy.job_role_name || item.title_ka === selectedVacancy.job_role_name)?.id ?? '',
      closes_at: selectedVacancy.closes_at ? selectedVacancy.closes_at.slice(0, 16) : '',
      public_slug: selectedVacancy.public_slug ?? '',
      external_form_url: selectedVacancy.external_form_url ?? '',
      is_public: selectedVacancy.is_public,
      application_form_schema: normalizeSchema(selectedVacancy.application_form_schema),
    })
  }, [props.data, selectedVacancy])

  const filteredDepartments = (props.data?.departments ?? []).filter((item) => {
    if (!departmentSearch.trim()) {
      return true
    }
    const needle = departmentSearch.toLowerCase()
    return `${item.name_ka ?? ''} ${item.name_en ?? ''}`.toLowerCase().includes(needle)
  })

  const filteredJobRoles = (props.data?.job_roles ?? []).filter((item) => {
    if (!jobRoleSearch.trim()) {
      return true
    }
    const needle = jobRoleSearch.toLowerCase()
    return `${item.title_ka ?? ''} ${item.title_en ?? ''}`.toLowerCase().includes(needle)
  })

  function updateField(index: number, patch: Partial<VacancyFieldDefinition>) {
    setForm((current) => ({
      ...current,
      application_form_schema: current.application_form_schema.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item),
    }))
  }

  async function handleSave(statusOverride?: 'draft' | 'published') {
    if (!props.canManage) {
      return
    }
    setBusy(true)
    try {
      const result = await props.onSave(selectedId === 'new' ? null : selectedId, {
        ...form,
        status: statusOverride ?? form.status,
        department_id: form.department_id || null,
        job_role_id: form.job_role_id || null,
        closes_at: form.closes_at || null,
        external_form_url: form.external_form_url || null,
        application_form_schema: form.application_form_schema.filter((field) => field.key && field.label),
      })
      setSelectedId(result.vacancy_id)
      setForm((current) => ({
        ...current,
        status: statusOverride ?? current.status,
        public_slug: result.public_slug,
      }))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel-card">
      <div className="mb-5 flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.32em] text-slate-400">Vacancy Lifecycle</p>
          <h2 className="mt-2 text-xl font-semibold text-slate-950">Vacancies and Public Careers</h2>
          <p className="mt-1 text-sm text-slate-500">Publish vacancies, bind them to real organization data, and keep the public job board polished.</p>
          {!props.canManage ? <p className="mt-2 text-xs font-semibold uppercase tracking-[0.18em] text-amber-600">Read only</p> : null}
        </div>
        <select className="input-shell min-w-[280px]" value={selectedId} onChange={(event) => setSelectedId(event.target.value)}>
          <option value="new">New Vacancy</option>
          {(props.data?.items ?? []).map((item) => (
            <option key={item.id} value={item.id}>
              {item.posting_code} - {item.title_ka || item.title_en}
            </option>
          ))}
        </select>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,0.95fr)_minmax(350px,0.85fr)]">
        <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-5">
          <div className="grid gap-4 md:grid-cols-2">
            <input className="input-shell" value={form.posting_code} onChange={(event) => setForm((current) => ({ ...current, posting_code: event.target.value }))} placeholder="Posting Code" disabled={!props.canManage} />
            <select className="input-shell" value={form.status} onChange={(event) => setForm((current) => ({ ...current, status: event.target.value }))} disabled={!props.canManage}>
              <option value="draft">Draft</option>
              <option value="published">Published</option>
              <option value="closed">Closed</option>
              <option value="on_hold">On Hold</option>
            </select>
            <input className="input-shell" value={form.title_en} onChange={(event) => setForm((current) => ({ ...current, title_en: event.target.value }))} placeholder="English title" disabled={!props.canManage} />
            <input className="input-shell" value={form.title_ka} onChange={(event) => setForm((current) => ({ ...current, title_ka: event.target.value }))} placeholder="ქართული სათაური" disabled={!props.canManage} />

            <input className="input-shell" value={departmentSearch} onChange={(event) => setDepartmentSearch(event.target.value)} placeholder="Search department" disabled={!props.canManage} />
            <select className="input-shell" value={form.department_id} onChange={(event) => setForm((current) => ({ ...current, department_id: event.target.value }))} disabled={!props.canManage}>
              <option value="">Select department</option>
              {filteredDepartments.map((item) => (
                <option key={item.id} value={item.id}>{item.name_ka ?? item.name_en}</option>
              ))}
            </select>

            <input className="input-shell" value={jobRoleSearch} onChange={(event) => setJobRoleSearch(event.target.value)} placeholder="Search position" disabled={!props.canManage} />
            <select className="input-shell" value={form.job_role_id} onChange={(event) => setForm((current) => ({ ...current, job_role_id: event.target.value }))} disabled={!props.canManage}>
              <option value="">Select position</option>
              {filteredJobRoles.map((item) => (
                <option key={item.id} value={item.id}>{item.title_ka ?? item.title_en}</option>
              ))}
            </select>

            <input className="input-shell" value={form.location_text} onChange={(event) => setForm((current) => ({ ...current, location_text: event.target.value }))} placeholder="Location" disabled={!props.canManage} />
            <input className="input-shell" type="number" value={form.open_positions} onChange={(event) => setForm((current) => ({ ...current, open_positions: Number(event.target.value) || 1 }))} placeholder="Open positions" disabled={!props.canManage} />
            <input className="input-shell" type="number" value={form.salary_min} onChange={(event) => setForm((current) => ({ ...current, salary_min: Number(event.target.value) || 0 }))} placeholder="Salary min" disabled={!props.canManage} />
            <input className="input-shell" type="number" value={form.salary_max} onChange={(event) => setForm((current) => ({ ...current, salary_max: Number(event.target.value) || 0 }))} placeholder="Salary max" disabled={!props.canManage} />
            <input className="input-shell" type="datetime-local" value={form.closes_at} onChange={(event) => setForm((current) => ({ ...current, closes_at: event.target.value }))} disabled={!props.canManage} />
            <input className="input-shell" value={form.public_slug} onChange={(event) => setForm((current) => ({ ...current, public_slug: event.target.value }))} placeholder="Public slug" disabled={!props.canManage} />
            <input className="input-shell md:col-span-2" value={form.external_form_url} onChange={(event) => setForm((current) => ({ ...current, external_form_url: event.target.value }))} placeholder="External form URL (optional)" disabled={!props.canManage} />
          </div>

          <label className="grid gap-2 text-sm font-medium text-slate-700">
            <span>Job Description</span>
            <textarea className="input-shell min-h-[160px]" value={form.description} onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))} placeholder="Internal description and recruiter notes" disabled={!props.canManage} />
          </label>

          <label className="grid gap-2 text-sm font-medium text-slate-700">
            <span>Public Requirements / Careers Copy</span>
            <textarea className="input-shell min-h-[160px]" value={form.public_description} onChange={(event) => setForm((current) => ({ ...current, public_description: event.target.value }))} placeholder="Visible on the public link. Add company info, role summary, requirements, responsibilities, benefits, and application instructions." disabled={!props.canManage} />
          </label>

          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <p className="text-sm font-semibold text-slate-950">Application collection</p>
            <p className="mt-1 text-sm text-slate-500">Leave the external URL empty to collect candidates and CVs inside ATS. Add a URL only when applications should go to Google Forms or another external form.</p>
          </div>

          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-2 font-semibold text-slate-950">
                <FilePlus2 className="h-4 w-4 text-action-600" />
                Custom Application Form
              </div>
              <button
                type="button"
                className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
                onClick={() => setForm((current) => ({ ...current, application_form_schema: [...current.application_form_schema, blankField()] }))}
                disabled={!props.canManage}
              >
                Add Field
              </button>
            </div>
            <div className="space-y-3">
              {form.application_form_schema.map((field, index) => (
                <div key={`${field.key}-${index}`} className="grid gap-3 rounded-lg border border-slate-200 bg-white p-3 md:grid-cols-[1fr_1fr_140px_88px_44px]">
                  <input className="input-shell" value={field.key} onChange={(event) => updateField(index, { key: event.target.value })} placeholder="field_key" disabled={!props.canManage} />
                  <input className="input-shell" value={field.label} onChange={(event) => updateField(index, { label: event.target.value })} placeholder="Label" disabled={!props.canManage} />
                  <select className="input-shell" value={field.field_type} onChange={(event) => updateField(index, { field_type: event.target.value })} disabled={!props.canManage}>
                    <option value="text">text</option>
                    <option value="textarea">textarea</option>
                    <option value="email">email</option>
                    <option value="phone">phone</option>
                    <option value="number">number</option>
                    <option value="date">date</option>
                  </select>
                  <label className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 text-sm text-slate-600">
                    <input type="checkbox" checked={field.required} disabled={!props.canManage} onChange={(event) => updateField(index, { required: event.target.checked })} />
                    Req
                  </label>
                  <button
                    type="button"
                    className="rounded-2xl border border-rose-200 bg-rose-50 text-rose-600 disabled:cursor-not-allowed disabled:opacity-50"
                    onClick={() => setForm((current) => ({ ...current, application_form_schema: current.application_form_schema.filter((_, itemIndex) => itemIndex !== index) }))}
                    disabled={!props.canManage}
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          </div>

          <div className="flex flex-wrap gap-3">
            <button type="button" className="muted-btn" onClick={() => void handleSave('draft')} disabled={busy || !props.canManage}>
              <Save className="h-4 w-4" />
              {busy ? 'Saving...' : 'Save Draft'}
            </button>
            <button type="button" className="brand-button inline-flex items-center gap-2 rounded-2xl px-4 py-3 font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50" onClick={() => void handleSave('published')} disabled={busy || !props.canManage}>
              <Send className="h-4 w-4" />
              {busy ? 'Publishing...' : 'Publish Vacancy'}
            </button>
          </div>
        </div>

        <div className="space-y-3">
          {(props.data?.items ?? []).map((item: VacancyItem) => (
            <button key={item.id} type="button" className={`w-full rounded-xl border p-4 text-left transition ${selectedId === item.id ? 'brand-border brand-soft border' : 'border-slate-200 bg-white hover:border-slate-300'}`} onClick={() => setSelectedId(item.id)}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-[0.2em] text-slate-400">{item.posting_code}</p>
                  <h3 className="mt-2 font-semibold text-slate-950">{item.title_ka || item.title_en}</h3>
                  <p className="mt-1 text-sm text-slate-500">{item.department_name ?? '-'} • {item.application_count} applicants</p>
                </div>
                <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold capitalize text-slate-600">{item.status.replace('_', ' ')}</span>
              </div>
              <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
                {item.external_form_url ? <span className="rounded-full bg-amber-50 px-3 py-1 text-amber-700">External Form</span> : <span className="rounded-full bg-emerald-50 px-3 py-1 text-emerald-700">Internal Form</span>}
                {item.public_url ? <span className="rounded-full bg-action-50 px-3 py-1 text-action-600">{item.public_slug}</span> : null}
              </div>
              {item.public_url ? <a className="mt-3 inline-flex items-center gap-2 text-sm font-semibold text-action-500" href={item.public_url} target="_blank" rel="noreferrer"><Link2 className="h-4 w-4" />Public link</a> : null}
              {item.external_form_url ? <a className="mt-2 inline-flex items-center gap-2 text-sm font-semibold text-slate-600" href={item.external_form_url} target="_blank" rel="noreferrer"><ExternalLink className="h-4 w-4" />External form</a> : null}
            </button>
          ))}
        </div>
      </div>
    </section>
  )
}
