import { FormEvent, useEffect, useMemo, useState } from 'react'

import { ArrowLeft, BriefcaseBusiness, CalendarDays, ChevronLeft, ChevronRight, MapPin, Search, Send, UsersRound } from 'lucide-react'

import { publicGetJson, publicPostJson } from '../api'
import type { PublicCareersData, PublicVacancyDetail, VacancyFieldDefinition } from '../types'
import { classNames, formatDate, formatMoney } from '../utils'

type CareerRoute = {
  tenantSlug: string
  vacancySlug: string | null
}

type ApplicationForm = {
  first_name: string
  last_name: string
  email: string
  phone: string
  city: string
  current_company: string
  current_position: string
  notes: string
  answers: Record<string, string>
}

const emptyApplication: ApplicationForm = {
  first_name: '',
  last_name: '',
  email: '',
  phone: '',
  city: '',
  current_company: '',
  current_position: '',
  notes: '',
  answers: {}
}

function parseCareerRoute(): CareerRoute {
  const segments = window.location.pathname.split('/').filter(Boolean)
  if (segments[0] === 'careers') {
    return {
      tenantSlug: segments[1] ?? '',
      vacancySlug: segments[2] ?? null
    }
  }
  return {
    tenantSlug: segments[0] ?? '',
    vacancySlug: segments[1] ?? null
  }
}

function salaryLabel(min: string | null, max: string | null): string {
  if (min && max) {
    return `${formatMoney(min)} - ${formatMoney(max)}`
  }
  if (min) {
    return `From ${formatMoney(min)}`
  }
  if (max) {
    return `Up to ${formatMoney(max)}`
  }
  return 'Salary disclosed later'
}

function compactText(value: string, maxLength = 190): string {
  const normalized = value.replace(/\s+/g, ' ').trim()
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength - 1)}...` : normalized
}

function FieldInput(props: {
  field: VacancyFieldDefinition
  value: string
  onChange: (value: string) => void
}) {
  if (props.field.field_type === 'textarea') {
    return (
      <textarea
        className="input-shell min-h-[110px] w-full"
        value={props.value}
        onChange={(event) => props.onChange(event.target.value)}
        required={props.field.required}
      />
    )
  }
  if (props.field.field_type === 'select' && props.field.options.length) {
    return (
      <select
        className="input-shell w-full"
        value={props.value}
        onChange={(event) => props.onChange(event.target.value)}
        required={props.field.required}
      >
        <option value="">Select</option>
        {props.field.options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    )
  }
  return (
    <input
      className="input-shell w-full"
      type={props.field.field_type === 'number' ? 'number' : 'text'}
      value={props.value}
      onChange={(event) => props.onChange(event.target.value)}
      required={props.field.required}
    />
  )
}

export function PublicCareers() {
  const [route, setRoute] = useState<CareerRoute>(() => parseCareerRoute())
  const [data, setData] = useState<PublicCareersData | null>(null)
  const [detail, setDetail] = useState<PublicVacancyDetail | null>(null)
  const [department, setDepartment] = useState('all')
  const [location, setLocation] = useState('all')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [application, setApplication] = useState<ApplicationForm>(emptyApplication)
  const [applicationStatus, setApplicationStatus] = useState('')

  useEffect(() => {
    const syncRoute = () => setRoute(parseCareerRoute())
    window.addEventListener('popstate', syncRoute)
    return () => window.removeEventListener('popstate', syncRoute)
  }, [])

  useEffect(() => {
    if (!route.tenantSlug || route.vacancySlug) {
      return
    }
    setBusy(true)
    setError('')
    publicGetJson<PublicCareersData>(`/public/careers/${route.tenantSlug}/vacancies`, {
      department,
      location,
      page,
      page_size: 6
    })
      .then((payload) => {
        setData(payload)
        document.documentElement.style.setProperty('--brand-primary', payload.tenant.primary_color)
      })
      .catch((err) => setError((err as Error).message))
      .finally(() => setBusy(false))
  }, [department, location, page, route.tenantSlug, route.vacancySlug])

  useEffect(() => {
    if (!route.vacancySlug) {
      setDetail(null)
      setApplication(emptyApplication)
      setApplicationStatus('')
      return
    }
    setBusy(true)
    setError('')
    publicGetJson<PublicVacancyDetail>(`/public/vacancies/${route.vacancySlug}`)
      .then((payload) => {
        setDetail(payload)
        document.documentElement.style.setProperty('--brand-primary', payload.primary_color ?? '#2563eb')
      })
      .catch((err) => setError((err as Error).message))
      .finally(() => setBusy(false))
  }, [route.vacancySlug])

  const filteredItems = useMemo(() => {
    const query = search.trim().toLowerCase()
    if (!query) {
      return data?.items ?? []
    }
    return (data?.items ?? []).filter((item) =>
      [item.title_en, item.title_ka, item.department_name, item.location_text, item.employment_type]
        .filter(Boolean)
        .some((value) => value!.toLowerCase().includes(query))
    )
  }, [data?.items, search])

  function navigate(path: string) {
    window.history.pushState({}, '', path)
    setRoute(parseCareerRoute())
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  async function submitApplication(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!detail) {
      return
    }
    setBusy(true)
    setApplicationStatus('')
    setError('')
    try {
      await publicPostJson(`/public/vacancies/${detail.public_slug}/apply`, {
        first_name: application.first_name,
        last_name: application.last_name,
        email: application.email || null,
        phone: application.phone || null,
        city: application.city || null,
        source: 'career_page',
        current_company: application.current_company || null,
        current_position: application.current_position || null,
        notes: application.notes || null,
        answers: application.answers
      })
      setApplication(emptyApplication)
      setApplicationStatus('Application submitted. The recruitment team will review it shortly.')
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (route.vacancySlug) {
    return (
      <main className="min-h-screen bg-slate-950 text-slate-900">
        <section className="mx-auto grid min-h-screen w-full max-w-7xl gap-6 px-4 py-6 sm:px-6 lg:grid-cols-[minmax(0,0.9fr)_420px] lg:px-8">
          <div className="rounded-[28px] bg-white p-5 sm:p-7">
            <button type="button" className="muted-btn mb-6" onClick={() => navigate(`/careers/${route.tenantSlug}`)}>
              <ArrowLeft className="h-4 w-4" />
              Back to jobs
            </button>
            {error ? <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div> : null}
            {detail ? (
              <article>
                <div className="flex flex-wrap items-center gap-2 text-sm text-slate-500">
                  <span>{detail.tenant_name}</span>
                  <span>/</span>
                  <span>{detail.posting_code}</span>
                </div>
                <h1 className="mt-4 max-w-3xl text-4xl font-semibold tracking-[-0.03em] text-slate-950 sm:text-5xl">{detail.title_en}</h1>
                <div className="mt-5 flex flex-wrap gap-2">
                  <span className="subtle-badge"><BriefcaseBusiness className="mr-1 h-3.5 w-3.5" />{detail.employment_type}</span>
                  <span className="subtle-badge"><MapPin className="mr-1 h-3.5 w-3.5" />{detail.location_text ?? 'Flexible'}</span>
                  <span className="subtle-badge"><UsersRound className="mr-1 h-3.5 w-3.5" />{detail.open_positions} open</span>
                  <span className="subtle-badge"><CalendarDays className="mr-1 h-3.5 w-3.5" />Closes {formatDate(detail.closes_at)}</span>
                </div>
                <div className="mt-8 grid gap-4 rounded-2xl border border-slate-200 bg-slate-50 p-5 sm:grid-cols-3">
                  <div>
                    <p className="text-xs uppercase tracking-[0.18em] text-slate-400">Department</p>
                    <p className="mt-2 font-semibold text-slate-950">{detail.department_name ?? '-'}</p>
                  </div>
                  <div>
                    <p className="text-xs uppercase tracking-[0.18em] text-slate-400">Role</p>
                    <p className="mt-2 font-semibold text-slate-950">{detail.job_role_name ?? '-'}</p>
                  </div>
                  <div>
                    <p className="text-xs uppercase tracking-[0.18em] text-slate-400">Compensation</p>
                    <p className="mt-2 font-semibold text-slate-950">{salaryLabel(detail.salary_min, detail.salary_max)}</p>
                  </div>
                </div>
                <div className="prose prose-slate mt-8 max-w-none whitespace-pre-wrap text-sm leading-7 text-slate-700">
                  {detail.public_description || detail.description}
                </div>
              </article>
            ) : busy ? (
              <div className="rounded-2xl border border-dashed border-slate-200 px-4 py-16 text-center text-sm text-slate-500">Loading vacancy...</div>
            ) : null}
          </div>

          <aside className="rounded-[28px] bg-white p-5 sm:p-6 lg:sticky lg:top-6 lg:self-start">
            <div className="mb-5">
              <p className="section-kicker">Apply</p>
              <h2 className="mt-2 text-2xl font-semibold text-slate-950">Candidate details</h2>
            </div>
            {applicationStatus ? (
              <div className="mb-4 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{applicationStatus}</div>
            ) : null}
            <form className="grid gap-3" onSubmit={(event) => void submitApplication(event)}>
              <div className="grid gap-3 sm:grid-cols-2">
                <input className="input-shell w-full" value={application.first_name} onChange={(event) => setApplication((current) => ({ ...current, first_name: event.target.value }))} placeholder="First name" required />
                <input className="input-shell w-full" value={application.last_name} onChange={(event) => setApplication((current) => ({ ...current, last_name: event.target.value }))} placeholder="Last name" required />
              </div>
              <input className="input-shell w-full" type="email" value={application.email} onChange={(event) => setApplication((current) => ({ ...current, email: event.target.value }))} placeholder="Email" />
              <input className="input-shell w-full" value={application.phone} onChange={(event) => setApplication((current) => ({ ...current, phone: event.target.value }))} placeholder="Phone" />
              <input className="input-shell w-full" value={application.city} onChange={(event) => setApplication((current) => ({ ...current, city: event.target.value }))} placeholder="City" />
              <div className="grid gap-3 sm:grid-cols-2">
                <input className="input-shell w-full" value={application.current_company} onChange={(event) => setApplication((current) => ({ ...current, current_company: event.target.value }))} placeholder="Current company" />
                <input className="input-shell w-full" value={application.current_position} onChange={(event) => setApplication((current) => ({ ...current, current_position: event.target.value }))} placeholder="Current position" />
              </div>
              {(detail?.application_form_schema ?? []).map((field) => (
                <label key={field.key} className="grid gap-1.5 text-sm font-semibold text-slate-700">
                  {field.label}
                  <FieldInput
                    field={field}
                    value={application.answers[field.key] ?? ''}
                    onChange={(value) => setApplication((current) => ({ ...current, answers: { ...current.answers, [field.key]: value } }))}
                  />
                </label>
              ))}
              <textarea className="input-shell min-h-[120px] w-full" value={application.notes} onChange={(event) => setApplication((current) => ({ ...current, notes: event.target.value }))} placeholder="Cover note" />
              <button type="submit" className="primary-btn" disabled={busy || !detail}>
                <Send className="h-4 w-4" />
                {busy ? 'Submitting...' : 'Submit application'}
              </button>
            </form>
          </aside>
        </section>
      </main>
    )
  }

  if (!route.tenantSlug) {
    return (
      <main className="min-h-screen bg-slate-950 px-4 py-16 text-slate-900">
        <div className="mx-auto max-w-lg rounded-[28px] border border-slate-200 bg-white p-8 text-center shadow-sm">
          <h1 className="text-xl font-semibold text-slate-900">Careers URL incomplete</h1>
          <p className="mt-3 text-sm text-slate-600">Open a link shaped like <span className="font-mono text-slate-800">/careers/your-company</span> (and optionally a role segment).</p>
        </div>
      </main>
    )
  }

  return (
    <main className="min-h-screen bg-slate-950 text-slate-900">
      <section className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
        <div className="rounded-[28px] bg-white p-5 sm:p-7">
          <div className="grid gap-6 lg:grid-cols-[minmax(0,0.8fr)_minmax(320px,0.45fr)]">
            <div>
              <div className="mb-6 flex items-center gap-3">
                <div className="flex h-12 w-12 items-center justify-center overflow-hidden rounded-2xl bg-slate-950 text-sm font-bold text-white">
                  {data?.tenant.logo_url ? <img src={data.tenant.logo_url} alt="" className="h-full w-full object-cover" /> : data?.tenant.logo_text ?? 'HR'}
                </div>
                <div>
                  <p className="text-sm text-slate-500">{data?.tenant.legal_name ?? 'Careers'}</p>
                  <h1 className="text-3xl font-semibold tracking-[-0.03em] text-slate-950 sm:text-5xl">{data?.tenant.trade_name ?? 'Open roles'}</h1>
                </div>
              </div>
              <p className="max-w-3xl text-base leading-7 text-slate-600">
                Explore open positions, filter by team or location, and apply directly from the role page.
              </p>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
              <div className="grid gap-3">
                <div className="relative">
                  <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                  <input className="input-shell w-full pl-11" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search roles" />
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <select className="input-shell w-full" value={department} onChange={(event) => { setDepartment(event.target.value); setPage(1) }}>
                    <option value="all">All departments</option>
                    {(data?.filters.departments ?? []).map((item) => <option key={item} value={item}>{item}</option>)}
                  </select>
                  <select className="input-shell w-full" value={location} onChange={(event) => { setLocation(event.target.value); setPage(1) }}>
                    <option value="all">All locations</option>
                    {(data?.filters.locations ?? []).map((item) => <option key={item} value={item}>{item}</option>)}
                  </select>
                </div>
              </div>
            </div>
          </div>

          {error ? <div className="mt-5 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div> : null}

          <div className="mt-8 grid gap-4 lg:grid-cols-2">
            {filteredItems.map((item) => (
              <article key={item.id} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">{item.posting_code}</p>
                    <h2 className="mt-2 text-2xl font-semibold tracking-[-0.02em] text-slate-950">{item.title_en}</h2>
                  </div>
                  <span className="subtle-badge">{item.open_positions} open</span>
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  <span className="subtle-badge"><BriefcaseBusiness className="mr-1 h-3.5 w-3.5" />{item.employment_type}</span>
                  <span className="subtle-badge"><MapPin className="mr-1 h-3.5 w-3.5" />{item.location_text ?? 'Flexible'}</span>
                  {item.department_name ? <span className="subtle-badge">{item.department_name}</span> : null}
                </div>
                <p className="mt-5 min-h-[56px] text-sm leading-7 text-slate-600">{compactText(item.summary)}</p>
                <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-4">
                  <p className="text-sm font-semibold text-slate-800">{salaryLabel(item.salary_min, item.salary_max)}</p>
                  <button type="button" className="primary-btn py-2.5" onClick={() => navigate(item.detail_url)}>
                    View role
                  </button>
                </div>
              </article>
            ))}
          </div>

          {!filteredItems.length && !busy ? (
            <div className="mt-8 rounded-2xl border border-dashed border-slate-200 px-4 py-16 text-center text-sm text-slate-500">
              {search.trim() || department !== 'all' || location !== 'all'
                ? 'No vacancies match the selected filters.'
                : 'No active vacancies found for this company.'}
            </div>
          ) : null}

          <div className="mt-8 flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-slate-500">{data ? `${data.total} open roles` : busy ? 'Loading roles...' : 'No roles loaded'}</p>
            <div className="flex items-center gap-2">
              <button type="button" className="muted-btn px-3 py-2" onClick={() => setPage((current) => Math.max(1, current - 1))} disabled={!data || page <= 1}>
                <ChevronLeft className="h-4 w-4" />
              </button>
              <span className={classNames('rounded-xl border border-slate-200 px-4 py-2 text-sm font-semibold', busy && 'opacity-60')}>
                {page} / {data?.page_count ?? 1}
              </span>
              <button type="button" className="muted-btn px-3 py-2" onClick={() => setPage((current) => Math.min(data?.page_count ?? current, current + 1))} disabled={!data || page >= data.page_count}>
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>
      </section>
    </main>
  )
}
