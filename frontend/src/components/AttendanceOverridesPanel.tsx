import { useState } from 'react'

import { AlertTriangle, CheckCircle2, LockKeyhole } from 'lucide-react'

import type { AttendanceOverrideItem } from '../types'
import { formatDateTime } from '../utils'

type AttendanceOverridesPanelProps = {
  items: AttendanceOverrideItem[]
  onResolve: (item: AttendanceOverrideItem, payload: {
    session_id: string | null
    work_date: string
    corrected_check_in: string
    corrected_check_out: string | null
    resolution_note: string
    mark_review_status: string
  }) => Promise<void>
}

export function AttendanceOverridesPanel(props: AttendanceOverridesPanelProps) {
  const [selectedId, setSelectedId] = useState<string>('')
  const [correctedIn, setCorrectedIn] = useState('')
  const [correctedOut, setCorrectedOut] = useState('')
  const [resolutionNote, setResolutionNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const selectedItem = props.items.find((item) => item.id === selectedId) ?? null

  async function handleResolve() {
    if (!selectedItem) {
      return
    }
    if (resolutionNote.trim().length < 5) {
      setError('ხელით შესწორებისთვის მიუთითეთ მიზეზი მინიმუმ 5 სიმბოლოთი.')
      return
    }
    setBusy(true)
    setError('')
    try {
      await props.onResolve(selectedItem, {
        session_id: selectedItem.session_id,
        work_date: selectedItem.work_date,
        corrected_check_in: correctedIn || selectedItem.check_in_ts || `${selectedItem.work_date}T09:00:00`,
        corrected_check_out: correctedOut || selectedItem.check_out_ts,
        resolution_note: resolutionNote.trim(),
        mark_review_status: 'corrected'
      })
      setSelectedId('')
      setCorrectedIn('')
      setCorrectedOut('')
      setResolutionNote('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel-card p-5">
      <div className="mb-5 flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <p className="section-kicker">Manual Adjustment</p>
          <h2 className="section-title">დასწრების ხელით შესწორება</h2>
          <p className="mt-1 text-sm text-slate-500">Raw hardware logs უცვლელია. HR ქმნის მხოლოდ audit trail-ით დაცულ ხელით კორექციას და მიზეზი სავალდებულოა.</p>
        </div>
        <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm font-semibold text-amber-700">
          ღია საკითხები: {props.items.length}
        </div>
      </div>

      <div className="mb-4 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
        <div className="flex items-center gap-2 font-semibold text-slate-900">
          <LockKeyhole className="h-4 w-4 text-slate-500" />
          Raw logs read-only რეჟიმშია
        </div>
        <p className="mt-1">კონსოლი ქმნის ცალკე კორექციის ჩანაწერს და არ ცვლის თავდაპირველ მოწყობილობის ლოგს.</p>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="space-y-3">
          {props.items.map((item) => (
            <button
              key={item.id}
              type="button"
              className={selectedId === item.id ? 'w-full rounded-2xl border border-amber-300 bg-amber-50 p-4 text-left transition' : 'w-full rounded-2xl border border-slate-200 bg-white p-4 text-left transition hover:border-slate-300'}
              onClick={() => {
                setSelectedId(item.id)
                setError('')
              }}
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="font-semibold text-slate-950">{item.first_name} {item.last_name} • {item.employee_number}</p>
                  <p className="mt-1 text-sm text-slate-500">{item.flag_type} • {item.work_date}</p>
                </div>
                <span className={item.severity === 'high' ? 'rounded-full bg-rose-100 px-3 py-1 text-xs font-semibold text-rose-700' : 'rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-700'}>
                  {item.severity}
                </span>
              </div>
              <p className="mt-3 text-sm text-slate-600">{item.details}</p>
              <div className="mt-3 flex flex-wrap gap-3 text-xs text-slate-500">
                <span>IN: {formatDateTime(item.check_in_ts)}</span>
                <span>OUT: {formatDateTime(item.check_out_ts)}</span>
              </div>
            </button>
          ))}
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-5">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <AlertTriangle className="h-4 w-4 text-amber-500" />
            კორექციის კონსოლი
          </div>

          {selectedItem ? (
            <div className="mt-4 space-y-4">
              <div className="rounded-2xl bg-slate-50 px-4 py-3 text-sm text-slate-600">
                {selectedItem.first_name} {selectedItem.last_name} • {selectedItem.work_date}
              </div>

              <input className="input-shell" type="datetime-local" value={correctedIn} onChange={(event) => setCorrectedIn(event.target.value)} />
              <input className="input-shell" type="datetime-local" value={correctedOut} onChange={(event) => setCorrectedOut(event.target.value)} />
              <textarea
                className="input-shell min-h-[120px]"
                value={resolutionNote}
                onChange={(event) => setResolutionNote(event.target.value)}
                placeholder="შესწორების მიზეზი"
              />

              {error ? (
                <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 break-words whitespace-pre-wrap">
                  {error}
                </div>
              ) : null}

              <button
                type="button"
                className="primary-btn inline-flex w-full items-center justify-center gap-2"
                onClick={() => void handleResolve()}
                disabled={busy}
              >
                <CheckCircle2 className="h-4 w-4" />
                {busy ? 'მუშავდება...' : 'დადასტურება და კორექცია'}
              </button>
            </div>
          ) : (
            <p className="mt-4 text-sm text-slate-500">აირჩიეთ ჩანაწერი სიიდან, შემდეგ მიუთითეთ შესწორებული დრო და მიზეზი.</p>
          )}
        </div>
      </div>
    </section>
  )
}
