import { CalendarClock, Mail, MessageSquareShare, Unplug } from 'lucide-react'

import type { IntegrationOverview } from '../types'
import { classNames } from '../utils'

type IntegrationCardProps = {
  title: string
  description: string
  badge: string
  connected: boolean
  configured: boolean
  details: string
  icon: typeof CalendarClock
  actionLabel: string
  secondaryActionLabel?: string
  busy?: boolean
  onAction: () => void
  onSecondaryAction?: () => void
}

function IntegrationCard(props: IntegrationCardProps) {
  const Icon = props.icon
  return (
    <article className="panel-card rounded-[28px]">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-4">
          <div className="flex h-14 w-14 items-center justify-center rounded-[20px] bg-slate-950 text-white shadow-[0_18px_30px_rgba(15,23,42,0.18)]">
            <Icon className="h-6 w-6" />
          </div>
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-slate-400">{props.badge}</p>
            <h3 className="mt-2 text-xl font-semibold text-slate-950">{props.title}</h3>
            <p className="mt-2 max-w-xl text-sm leading-6 text-slate-500">{props.description}</p>
          </div>
        </div>
        <span
          className={classNames(
            'rounded-full px-3 py-1 text-xs font-semibold',
            props.connected ? 'bg-emerald-100 text-emerald-700' : props.configured ? 'bg-amber-100 text-amber-700' : 'bg-slate-100 text-slate-600'
          )}
        >
          {props.connected ? 'Connected' : props.configured ? 'Ready to connect' : 'Setup needed'}
        </span>
      </div>

      <div className="mt-5 rounded-[22px] border border-slate-200/80 bg-white/78 px-4 py-4">
        <p className="text-sm font-medium text-slate-900">{props.details}</p>
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-3">
        <button type="button" className="primary-btn px-5 py-3" onClick={props.onAction} disabled={props.busy}>
          {props.actionLabel}
        </button>
        {props.onSecondaryAction ? (
          <button type="button" className="muted-btn px-4 py-3" onClick={props.onSecondaryAction} disabled={props.busy}>
            <Unplug className="h-4 w-4" />
            {props.secondaryActionLabel ?? 'Disconnect'}
          </button>
        ) : null}
      </div>
    </article>
  )
}

type IntegrationsPanelProps = {
  data: IntegrationOverview | null
  busy?: boolean
  onConnectGoogleCalendar: () => void
  onDisconnectGoogleCalendar: () => void
  onConnectSlack: () => void
  onDisconnectSlack: () => void
}

export function IntegrationsPanel(props: IntegrationsPanelProps) {
  const overview = props.data

  return (
    <div className="space-y-6">
      <section className="panel-card rounded-[30px]">
        <p className="text-[12px] font-semibold uppercase tracking-[0.28em] text-slate-400">Apps & Integrations</p>
        <h2 className="mt-3 text-[30px] font-semibold tracking-[-0.04em] text-slate-950">Connection Hub</h2>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-500">
          Manage the apps that power your HR dashboard, scheduling, and direct employee communication. Connections here are reused across the dashboard action shortcuts.
        </p>
      </section>

      <div className="grid gap-6 xl:grid-cols-2">
        <IntegrationCard
          title="Google Calendar"
          description="Sync interviews, reviews, payroll checkpoints, and HR operations meetings into the dashboard schedule panel."
          badge="Scheduling"
          connected={Boolean(overview?.google_calendar.connected)}
          configured={Boolean(overview?.google_calendar.configured)}
          details={
            overview?.google_calendar.connected
              ? `Connected as ${overview.google_calendar.account_email ?? 'Google Calendar account'}.`
              : overview?.google_calendar.error ?? 'Connect your Google Calendar account to load upcoming schedule items.'
          }
          icon={CalendarClock}
          actionLabel={overview?.google_calendar.connected ? 'Reconnect' : 'Connect'}
          secondaryActionLabel="Disconnect"
          busy={props.busy}
          onAction={props.onConnectGoogleCalendar}
          onSecondaryAction={overview?.google_calendar.connected ? props.onDisconnectGoogleCalendar : undefined}
        />

        <IntegrationCard
          title="Slack Workspace"
          description="Enable tenant-wide Slack connectivity so HR can send direct messages to employees from live feed, celebrations, and schedule widgets."
          badge="Messaging"
          connected={Boolean(overview?.slack.connected)}
          configured={Boolean(overview?.slack.configured)}
          details={
            overview?.slack.connected
              ? `Connected to ${overview.slack.team_name ?? 'Slack workspace'}${overview.slack.team_id ? ` (${overview.slack.team_id})` : ''}.`
              : overview?.slack.error ?? 'Connect Slack to unlock direct employee messages from the dashboard.'
          }
          icon={MessageSquareShare}
          actionLabel={overview?.slack.connected ? 'Reconnect' : 'Connect'}
          secondaryActionLabel="Disconnect"
          busy={props.busy}
          onAction={props.onConnectSlack}
          onSecondaryAction={overview?.slack.connected ? props.onDisconnectSlack : undefined}
        />
      </div>

      <IntegrationCard
        title="Google Workspace Email"
        description="Use the company SMTP mailbox for direct employee updates when Slack is unavailable or email is the preferred channel."
        badge="Delivery"
        connected={Boolean(overview?.email.connected)}
        configured={Boolean(overview?.email.configured)}
        details={
          overview?.email.connected
            ? `Messages will send from ${overview.email.from_email ?? 'the configured mailbox'}.`
            : overview?.email.error ?? 'Configure SMTP credentials in the server environment to send email from the dashboard.'
        }
        icon={Mail}
        actionLabel="Configured in server"
        busy
        onAction={() => undefined}
      />
    </div>
  )
}
