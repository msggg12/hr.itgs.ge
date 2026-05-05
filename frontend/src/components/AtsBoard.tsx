import type { CSSProperties } from 'react'
import { useState } from 'react'
import { createPortal } from 'react-dom'

import { DndContext, DragOverlay, MouseSensor, TouchSensor, type DragEndEvent, type DragStartEvent, closestCorners, useDraggable, useDroppable, useSensor, useSensors } from '@dnd-kit/core'
import { BriefcaseBusiness, CalendarDays, CalendarPlus, ExternalLink, MapPin, UserRound, X } from 'lucide-react'

import { ka } from '../i18n/ka'
import type { AtsBoardData, AtsCard } from '../types'
import { classNames, formatDate, formatMoney, initials } from '../utils'

type AtsBoardProps = {
  board: AtsBoardData | null
  busy: boolean
  canManage: boolean
  onMoveCard: (applicationId: string, targetStage: string) => Promise<void>
  onScheduleInterview: (applicationId: string, payload: {
    scheduled_at: string
    duration_minutes: number
    notes: string
  }) => Promise<{ calendar_url?: string | null }>
}

type ScheduleModalState = {
  card: AtsCard
  scheduledAt: string
  durationMinutes: number
  notes: string
}

function CandidateCard(props: {
  candidate: AtsCard
  canManage: boolean
  onScheduleInterview: (candidate: AtsCard) => void
}) {
  const draggable = useDraggable({
    id: `candidate-${props.candidate.id}`,
    data: { applicationId: props.candidate.id, currentStage: props.candidate.stage_code, candidate: props.candidate },
    disabled: !props.canManage,
  })

  return (
    <CandidateCardBody
      candidate={props.candidate}
      canManage={props.canManage}
      onScheduleInterview={() => props.onScheduleInterview(props.candidate)}
      setNodeRef={props.canManage ? draggable.setNodeRef : undefined}
      listeners={props.canManage ? draggable.listeners : undefined}
      attributes={props.canManage ? draggable.attributes : undefined}
      style={props.canManage && draggable.isDragging ? { opacity: 0.28 } : undefined}
      isDragging={props.canManage ? draggable.isDragging : false}
    />
  )
}

function CandidateCardBody(props: {
  candidate: AtsCard
  canManage?: boolean
  onScheduleInterview?: () => void
  setNodeRef?: (element: HTMLElement | null) => void
  listeners?: Record<string, unknown>
  attributes?: Record<string, unknown>
  style?: CSSProperties
  isDragging?: boolean
}) {
  const score = props.candidate.compatibility_score
  const interviewLabel = props.candidate.interview_scheduled_at
    ? new Intl.DateTimeFormat('en-GB', {
        day: '2-digit',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
      }).format(new Date(props.candidate.interview_scheduled_at))
    : null

  return (
    <article
      ref={props.setNodeRef}
      style={props.style}
      {...props.listeners}
      {...props.attributes}
      className={classNames(
        'rounded-xl border border-slate-200 bg-white p-4 shadow-sm transition-transform transition-shadow',
        'select-none',
        props.canManage && 'cursor-grab active:cursor-grabbing',
        props.isDragging && 'rotate-[1deg] shadow-2xl ring-2 ring-action-200'
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-slate-900 text-xs font-bold text-white">
            {initials(props.candidate.first_name, props.candidate.last_name)}
          </div>
          <div>
            <h3 className="font-semibold text-slate-950">{props.candidate.first_name} {props.candidate.last_name}</h3>
            <p className="text-xs text-slate-500">{props.candidate.job_title}</p>
          </div>
        </div>
        <div className="flex flex-col items-end gap-2">
          {score != null ? (
            <span className={classNames(
              'rounded-full px-2.5 py-1 text-[11px] font-semibold',
              score >= 75 ? 'bg-emerald-50 text-emerald-700' : score >= 50 ? 'bg-amber-50 text-amber-700' : 'bg-slate-100 text-slate-600'
            )}>
              {Math.round(score)}% Match
            </span>
          ) : null}
          {props.candidate.actual_stage_code !== props.candidate.stage_code ? (
            <span className="rounded-full bg-slate-100 px-2 py-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-600">
              {props.candidate.actual_stage_code}
            </span>
          ) : null}
        </div>
      </div>

      <div className="mt-4 grid gap-2 text-sm text-slate-600">
        <div className="flex items-center gap-2">
          <BriefcaseBusiness className="h-4 w-4 text-action-600" />
          <span>{props.candidate.posting_code} - {props.candidate.department_name ?? '-'}</span>
        </div>
        <div className="flex items-center gap-2">
          <UserRound className="h-4 w-4 text-action-600" />
          <span>{ka.candidateOwner}: {props.candidate.owner_name || '-'}</span>
        </div>
        <div className="flex items-center gap-2">
          <MapPin className="h-4 w-4 text-action-600" />
          <span>{props.candidate.city ?? props.candidate.email ?? props.candidate.phone ?? '-'}</span>
        </div>
      </div>

      {props.candidate.compatibility_summary ? (
        <p className="mt-3 rounded-lg bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-600">
          {props.candidate.compatibility_summary}
        </p>
      ) : null}

      {interviewLabel ? (
        <div className="mt-3 flex items-center justify-between rounded-lg border border-sky-100 bg-sky-50 px-3 py-2 text-xs text-sky-700">
          <span className="inline-flex items-center gap-2">
            <CalendarDays className="h-3.5 w-3.5" />
            Interview: {interviewLabel}
          </span>
          {props.candidate.interview_calendar_url ? (
            <a
              href={props.candidate.interview_calendar_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 font-semibold"
              onPointerDown={(event) => event.stopPropagation()}
              onClick={(event) => event.stopPropagation()}
            >
              <ExternalLink className="h-3.5 w-3.5" />
              Open
            </a>
          ) : null}
        </div>
      ) : null}

      <div className="mt-4 flex items-center justify-between text-xs text-slate-500">
        <span>{ka.appliedAt}: {formatDate(props.candidate.applied_at)}</span>
        <span>{props.candidate.salary_max ?? props.candidate.salary_min ? formatMoney(props.candidate.salary_max ?? props.candidate.salary_min ?? 0) : '-'}</span>
      </div>

      {props.canManage ? (
        <div className="mt-4 flex items-center justify-end gap-2">
          <button
            type="button"
            className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
            onPointerDown={(event) => event.stopPropagation()}
            onClick={(event) => {
              event.stopPropagation()
              props.onScheduleInterview?.()
            }}
          >
            <CalendarPlus className="h-3.5 w-3.5" />
            Schedule
          </button>
        </div>
      ) : null}
    </article>
  )
}

function StageColumn(props: {
  code: string
  title: string
  candidates: AtsCard[]
  canManage: boolean
  onScheduleInterview: (candidate: AtsCard) => void
}) {
  const { isOver, setNodeRef } = useDroppable({
    id: `stage-${props.code}`,
    data: { stageCode: props.code },
    disabled: !props.canManage,
  })

  return (
    <section ref={setNodeRef} className={classNames('rounded-xl border border-slate-200 bg-slate-50 p-4 transition', isOver && 'border-action-300 bg-action-50')}>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h3 className="font-semibold text-slate-950">{props.title}</h3>
          <p className="text-xs uppercase tracking-[0.18em] text-slate-400">{props.candidates.length}</p>
        </div>
      </div>
      <div className="space-y-3">
        {props.candidates.map((candidate) => (
          <CandidateCard
            key={candidate.id}
            candidate={candidate}
            canManage={props.canManage}
            onScheduleInterview={props.onScheduleInterview}
          />
        ))}
        {!props.candidates.length ? (
          <div className="rounded-lg border border-dashed border-slate-300 px-4 py-10 text-center text-sm text-slate-500">
            {ka.noCandidates}
          </div>
        ) : null}
      </div>
    </section>
  )
}

export function AtsBoard(props: AtsBoardProps) {
  const [activeCard, setActiveCard] = useState<AtsCard | null>(null)
  const [scheduleModal, setScheduleModal] = useState<ScheduleModalState | null>(null)
  const [scheduleBusy, setScheduleBusy] = useState(false)
  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 4 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 120, tolerance: 6 } })
  )

  function handleDragStart(event: DragStartEvent) {
    if (!props.canManage) {
      return
    }
    setActiveCard((event.active.data.current?.candidate as AtsCard | null) ?? null)
  }

  async function handleDragEnd(event: DragEndEvent) {
    if (!props.canManage) {
      setActiveCard(null)
      return
    }
    const applicationId = event.active.data.current?.applicationId as string | undefined
    const currentStage = event.active.data.current?.currentStage as string | undefined
    const targetStage = (event.over?.data.current?.stageCode as string | undefined) ?? event.over?.id?.toString().replace('stage-', '')
    setActiveCard(null)
    if (!applicationId || !targetStage || targetStage === currentStage) {
      return
    }
    await props.onMoveCard(applicationId, targetStage)
  }

  async function submitSchedule() {
    if (!scheduleModal) {
      return
    }
    setScheduleBusy(true)
    try {
      const response = await props.onScheduleInterview(scheduleModal.card.id, {
        scheduled_at: scheduleModal.scheduledAt,
        duration_minutes: scheduleModal.durationMinutes,
        notes: scheduleModal.notes,
      })
      setScheduleModal(null)
      if (response.calendar_url) {
        window.open(response.calendar_url, '_blank', 'noopener,noreferrer')
      }
    } catch {
      // Shared app error state is set by the callback.
    } finally {
      setScheduleBusy(false)
    }
  }

  return (
    <article className="panel-card">
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-slate-950">{ka.recruitmentPipeline}</h2>
          <p className="mt-1 text-sm text-slate-500">{props.canManage ? ka.dragToAssign : 'Read-only recruitment pipeline view'}</p>
        </div>
        <div className="flex items-center gap-2">
          {activeCard ? <div className="rounded-full border border-action-200 bg-action-50 px-3 py-1 text-xs font-semibold text-action-600">Dragging</div> : null}
          {!props.canManage ? <div className="rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-700">Read only</div> : null}
          {props.busy ? <div className="rounded-full border border-action-200 bg-action-50 px-3 py-1 text-xs font-semibold text-action-600">Syncing</div> : null}
        </div>
      </div>

      <DndContext sensors={sensors} collisionDetection={closestCorners} onDragStart={handleDragStart} onDragEnd={(event) => void handleDragEnd(event)}>
        <div className="grid gap-4 xl:grid-cols-4">
          {props.board?.columns?.map((column) => (
            <StageColumn
              key={column.code}
              code={column.code}
              title={column.name_ka}
              candidates={props.board?.cards[column.code] ?? []}
              canManage={props.canManage}
              onScheduleInterview={(candidate) => setScheduleModal({
                card: candidate,
                scheduledAt: candidate.interview_scheduled_at ? candidate.interview_scheduled_at.slice(0, 16) : '',
                durationMinutes: candidate.interview_duration_minutes ?? 45,
                notes: candidate.interview_notes ?? '',
              })}
            />
          ))}
        </div>
        {typeof document !== 'undefined'
          ? createPortal(
            <DragOverlay dropAnimation={null} zIndex={100}>
              {activeCard ? (
                <CandidateCardBody
                  candidate={activeCard}
                  canManage={props.canManage}
                  style={{ width: 320, boxShadow: '0 28px 64px rgba(15, 23, 42, 0.24)' }}
                />
              ) : null}
            </DragOverlay>,
            document.body
          )
          : null}
      </DndContext>

      {scheduleModal ? (
        <div className="fixed inset-0 z-[90] flex items-center justify-center bg-slate-950/55 px-4">
          <div className="w-full max-w-lg rounded-[28px] border border-slate-200 bg-white p-6 shadow-2xl">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-xs uppercase tracking-[0.28em] text-slate-400">Interview Scheduling</p>
                <h3 className="mt-2 text-2xl font-semibold text-slate-950">
                  {scheduleModal.card.first_name} {scheduleModal.card.last_name}
                </h3>
                <p className="mt-2 text-sm text-slate-500">{scheduleModal.card.job_title}</p>
              </div>
              <button
                type="button"
                className="rounded-full border border-slate-200 p-2 text-slate-500 hover:bg-slate-50"
                onClick={() => !scheduleBusy && setScheduleModal(null)}
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="mt-6 grid gap-4">
              <label className="grid gap-2 text-sm text-slate-600">
                <span>Date & Time</span>
                <input
                  className="input-shell"
                  type="datetime-local"
                  value={scheduleModal.scheduledAt}
                  onChange={(event) => setScheduleModal((current) => current ? { ...current, scheduledAt: event.target.value } : current)}
                />
              </label>
              <label className="grid gap-2 text-sm text-slate-600">
                <span>Duration (minutes)</span>
                <input
                  className="input-shell"
                  type="number"
                  min={15}
                  step={15}
                  value={scheduleModal.durationMinutes}
                  onChange={(event) => setScheduleModal((current) => current ? { ...current, durationMinutes: Number(event.target.value) || 45 } : current)}
                />
              </label>
              <label className="grid gap-2 text-sm text-slate-600">
                <span>Notes</span>
                <textarea
                  className="input-shell min-h-[120px]"
                  value={scheduleModal.notes}
                  onChange={(event) => setScheduleModal((current) => current ? { ...current, notes: event.target.value } : current)}
                  placeholder="Interview notes, meeting topic, or instructions"
                />
              </label>
            </div>

            <div className="mt-6 flex items-center justify-end gap-3">
              <button type="button" className="muted-btn" onClick={() => setScheduleModal(null)} disabled={scheduleBusy}>
                Cancel
              </button>
              <button
                type="button"
                className="primary-btn"
                onClick={() => void submitSchedule()}
                disabled={scheduleBusy || !scheduleModal.scheduledAt}
              >
                {scheduleBusy ? 'Saving...' : 'Schedule Interview'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </article>
  )
}
