import { useEffect, useState } from 'react'

import { Clock3, MapPin, ShieldCheck } from 'lucide-react'

import type { WebPunchConfigData } from '../types'
import { formatDateTime } from '../utils'

type WebPunchPanelProps = {
  data: WebPunchConfigData | null
  onSubmit: (payload: { direction: string; latitude: number | null; longitude: number | null }) => Promise<void>
}

function formatTimer(totalSeconds: number): string {
  const hours = String(Math.floor(totalSeconds / 3600)).padStart(2, '0')
  const minutes = String(Math.floor((totalSeconds % 3600) / 60)).padStart(2, '0')
  const seconds = String(totalSeconds % 60).padStart(2, '0')
  return `${hours}:${minutes}:${seconds}`
}

export function WebPunchPanel(props: WebPunchPanelProps) {
  const [latitude, setLatitude] = useState('')
  const [longitude, setLongitude] = useState('')
  const [busy, setBusy] = useState(false)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)

  const status = props.data?.status_summary
  const isCurrentlyCheckedIn = status?.is_checked_in ?? false
  const checkInTime = status?.current_segment_started_at ? new Date(status.current_segment_started_at) : null
  const completedSeconds = status?.completed_work_seconds_today ?? 0

  useEffect(() => {
    if (!checkInTime) {
      setElapsedSeconds(0)
      return undefined
    }

    const updateElapsed = () => {
      setElapsedSeconds(Math.max(0, Math.floor((Date.now() - checkInTime.getTime()) / 1000)))
    }

    updateElapsed()
    const timer = window.setInterval(updateElapsed, 1000)
    return () => window.clearInterval(timer)
  }, [checkInTime])

  async function handleSubmit() {
    setBusy(true)
    try {
      await props.onSubmit({
        direction: 'auto',
        latitude: latitude ? Number(latitude) : null,
        longitude: longitude ? Number(longitude) : null,
      })
      setLatitude('')
      setLongitude('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="glass-panel p-5">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-[0.32em] text-action-400">Web Punch</p>
          <h2 className="mt-2 text-xl font-semibold text-navy-900">Quick Check-In / Check-Out</h2>
        </div>
        <span className={`rounded-full px-3 py-1 text-xs font-semibold ${isCurrentlyCheckedIn ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-600'}`}>
          {isCurrentlyCheckedIn ? 'Checked In' : 'Checked Out'}
        </span>
      </div>

      <div className="mt-5 grid gap-4 md:grid-cols-2">
        <div className="rounded-2xl border border-slate-200 bg-white px-4 py-4">
          <div className="flex items-center gap-2 text-xs uppercase tracking-[0.24em] text-slate-400">
            <ShieldCheck className="h-4 w-4 text-action-400" />
            Status
          </div>
          <p className="mt-3 text-lg font-semibold text-slate-950">
            {isCurrentlyCheckedIn ? 'Working now' : 'Waiting for punch'}
          </p>
          <p className="mt-2 text-sm text-slate-500">
            {checkInTime ? `Started ${formatDateTime(checkInTime.toISOString())}` : 'No open session'}
          </p>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white px-4 py-4">
          <div className="flex items-center gap-2 text-xs uppercase tracking-[0.24em] text-slate-400">
            <Clock3 className="h-4 w-4 text-action-400" />
            Timer
          </div>
          <p className="mt-3 text-lg font-semibold text-slate-950">{isCurrentlyCheckedIn ? formatTimer(elapsedSeconds) : '--:--:--'}</p>
          <p className="mt-2 text-sm text-slate-500">Today total {formatTimer(completedSeconds + elapsedSeconds)}</p>
        </div>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <label className="space-y-2">
          <span className="inline-flex items-center gap-2 text-xs uppercase tracking-[0.24em] text-slate-400">
            <MapPin className="h-4 w-4 text-action-400" />
            Lat
          </span>
          <input className="input-shell" value={latitude} onChange={(event) => setLatitude(event.target.value)} placeholder="41.7151" />
        </label>
        <label className="space-y-2">
          <span className="inline-flex items-center gap-2 text-xs uppercase tracking-[0.24em] text-slate-400">
            <MapPin className="h-4 w-4 text-action-400" />
            Lng
          </span>
          <input className="input-shell" value={longitude} onChange={(event) => setLongitude(event.target.value)} placeholder="44.8271" />
        </label>
      </div>

      <button
        type="button"
        className="brand-button mt-4 w-full rounded-2xl px-4 py-3 font-semibold text-white"
        onClick={() => void handleSubmit()}
        disabled={busy}
      >
        {busy ? 'Sending...' : isCurrentlyCheckedIn ? 'Check Out' : 'Check In'}
      </button>
    </section>
  )
}
