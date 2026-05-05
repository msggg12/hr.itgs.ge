import { useEffect, useState } from 'react'

import { Flame } from 'lucide-react'

import type { PerformanceHubData } from '../types'

type PerformanceHubProps = {
  data: PerformanceHubData | null
  onCreateObjective: (payload: {
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
  }) => Promise<void>
}

export function PerformanceHub(props: PerformanceHubProps) {
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({
    cycle_id: props.data?.cycles?.[0]?.id ?? '',
    scope: 'employee',
    title: '',
    description: '',
    department_id: '',
    employee_id: '',
    owner_employee_id: '',
    weight: 1,
    key_result_title: '',
    metric_unit: '%',
    target_value: 100
  })

  useEffect(() => {
    if (!props.data?.cycles?.length) {
      return
    }
    setForm((current) => ({
      ...current,
      cycle_id: current.cycle_id || props.data.cycles?.[0]?.id || ''
    }))
  }, [props.data])

  async function handleSubmit() {
    setBusy(true)
    try {
      await props.onCreateObjective({
        cycle_id: form.cycle_id,
        scope: form.scope,
        title: form.title,
        description: form.description || null,
        department_id: form.department_id || null,
        employee_id: form.employee_id || null,
        owner_employee_id: form.owner_employee_id || null,
        weight: Number(form.weight),
        key_result_title: form.key_result_title,
        metric_unit: form.metric_unit,
        target_value: Number(form.target_value)
      })
      setForm((current) => ({
        ...current,
        title: '',
        description: '',
        key_result_title: '',
        target_value: 100
      }))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="space-y-6">
      <section className="panel-card">
        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-[0.32em] text-slate-400">OKR Control</p>
            <h2 className="mt-2 text-xl font-semibold text-slate-950">აქტიური OKR-ები</h2>
            <p className="mt-1 text-sm text-slate-500">მენეჯერი ქმნის objective-ს და მის პირველ key result-ს ერთი ფორმიდან.</p>
          </div>
          <div className="rounded-xl border border-emerald-100 bg-emerald-50 px-4 py-3 text-sm font-semibold text-emerald-700">
            Objectives: {props.data?.objectives?.length ?? 0}
          </div>
        </div>

        <div className="grid gap-6 xl:grid-cols-[minmax(0,0.9fr)_minmax(340px,1fr)]">
          <div className="rounded-xl border border-slate-200 bg-white p-5">
            <div className="grid gap-4 md:grid-cols-2">
              <select className="input-shell" value={form.cycle_id} onChange={(event) => setForm((current) => ({ ...current, cycle_id: event.target.value }))}>
                <option value="">Cycle</option>
                {(props.data?.cycles ?? []).map((cycle) => <option key={cycle.id} value={cycle.id}>{cycle.title}</option>)}
              </select>
              <select className="input-shell" value={form.scope} onChange={(event) => setForm((current) => ({ ...current, scope: event.target.value }))}>
                <option value="employee">Employee</option>
                <option value="department">Department</option>
              </select>
              <input className="input-shell md:col-span-2" value={form.title} onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))} placeholder="Objective title" />
              <textarea className="input-shell md:col-span-2 min-h-[96px]" value={form.description} onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))} placeholder="აღწერა" />
              <select className="input-shell" value={form.employee_id} onChange={(event) => setForm((current) => ({ ...current, employee_id: event.target.value }))}>
                <option value="">Employee</option>
                {(props.data?.employees ?? []).map((employee) => <option key={employee.id} value={employee.id}>{employee.full_name}</option>)}
              </select>
              <select className="input-shell" value={form.owner_employee_id} onChange={(event) => setForm((current) => ({ ...current, owner_employee_id: event.target.value }))}>
                <option value="">Owner</option>
                {(props.data?.employees ?? []).map((employee) => <option key={employee.id} value={employee.id}>{employee.full_name}</option>)}
              </select>
              <input className="input-shell" type="number" step="0.1" value={form.weight} onChange={(event) => setForm((current) => ({ ...current, weight: Number(event.target.value) }))} placeholder="Weight" />
              <input className="input-shell" value={form.key_result_title} onChange={(event) => setForm((current) => ({ ...current, key_result_title: event.target.value }))} placeholder="First Key Result" />
              <input className="input-shell" value={form.metric_unit} onChange={(event) => setForm((current) => ({ ...current, metric_unit: event.target.value }))} placeholder="Metric Unit" />
              <input className="input-shell" type="number" value={form.target_value} onChange={(event) => setForm((current) => ({ ...current, target_value: Number(event.target.value) }))} placeholder="Target Value" />
            </div>
            <button type="button" className="brand-button mt-4 rounded-2xl px-4 py-3 font-semibold text-white" onClick={() => void handleSubmit()} disabled={busy}>
              {busy ? 'იქმნება...' : 'Objective შექმნა'}
            </button>
          </div>

          <div className="space-y-3">
            {(props.data?.objectives ?? []).slice(0, 8).map((objective) => (
              <article key={objective.id} className="rounded-xl border border-slate-200 bg-white p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-xs uppercase tracking-[0.18em] text-slate-400">{objective.cycle_title}</p>
                    <h3 className="mt-2 font-semibold text-slate-950">{objective.title}</h3>
                    <p className="mt-1 text-sm text-slate-500">{objective.employee_name ?? objective.department_name ?? '-'}</p>
                  </div>
                  <div className="rounded-full bg-action-50 px-3 py-1 text-xs font-semibold text-action-600">{objective.progress_percent}%</div>
                </div>
                <div className="mt-4 h-2 rounded-full bg-slate-100">
                  <div className="h-2 rounded-full bg-action-500" style={{ width: `${Math.min(objective.progress_percent, 100)}%` }} />
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="panel-card">
        <div className="mb-5 flex items-center gap-3">
          <Flame className="h-5 w-5 text-amber-500" />
          <h2 className="text-xl font-semibold text-slate-950">Team Capacity Heatmap</h2>
        </div>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {(props.data?.heatmap ?? []).map((item) => (
            <article key={item.employee_id} className="rounded-xl border border-slate-200 bg-white p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="font-semibold text-slate-950">{item.employee_name}</p>
                  <p className="text-sm text-slate-500">{item.employee_number}</p>
                </div>
                <span className={`rounded-full px-3 py-1 text-xs font-semibold ${item.risk_band === 'high' ? 'bg-rose-50 text-rose-700' : item.risk_band === 'medium' ? 'bg-amber-50 text-amber-700' : 'bg-emerald-50 text-emerald-700'}`}>
                  {item.risk_band}
                </span>
              </div>
              <div className="mt-4 space-y-2 text-sm text-slate-600">
                <div className="flex items-center justify-between"><span>Shift hours</span><span>{item.planned_hours}</span></div>
                <div className="flex items-center justify-between"><span>Objectives</span><span>{item.objective_count}</span></div>
                <div className="flex items-center justify-between"><span>Utilization</span><span>{item.utilization_score}%</span></div>
              </div>
              <div className="mt-4 h-2 rounded-full bg-slate-100">
                <div className={`h-2 rounded-full ${item.risk_band === 'high' ? 'bg-rose-500' : item.risk_band === 'medium' ? 'bg-amber-400' : 'bg-emerald-500'}`} style={{ width: `${Math.min(item.utilization_score, 100)}%` }} />
              </div>
            </article>
          ))}
        </div>
      </section>
    </section>
  )
}
