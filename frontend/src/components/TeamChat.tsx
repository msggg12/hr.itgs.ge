import { ExternalLink, MessageCircleMore, MessagesSquare, ShieldCheck } from 'lucide-react'

import { ka } from '../i18n/ka'
import type { TeamChatConfig } from '../types'

export function TeamChat(props: { config: TeamChatConfig | null }) {
  const linked = Boolean(props.config?.channel_url)
  const channelUrl = props.config?.channel_url ?? null
  const embedAllowed = Boolean(
    channelUrl
    && (
      channelUrl.startsWith('/')
      || (typeof window !== 'undefined' && channelUrl.startsWith(window.location.origin))
    ),
  )

  return (
    <article className="panel-card overflow-hidden p-0">
      <div className="flex items-center justify-between border-b border-slate-200 px-6 py-5">
        <div>
          <h2 className="text-xl font-semibold text-slate-950">{ka.teamChat}</h2>
          <p className="mt-1 text-sm text-slate-500">
            {props.config?.mattermost_username ? `${ka.linkedAs}: @${props.config.mattermost_username}` : 'Mattermost workspace'}
          </p>
        </div>
        <div className="brand-soft rounded-lg border border-slate-200 p-3">
          <MessagesSquare className="h-5 w-5" />
        </div>
      </div>

      {linked ? (
        <div className="p-5">
          <div className="mb-5 grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto]">
            <div className="rounded-2xl border border-slate-200 bg-slate-50 px-5 py-4">
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                <ShieldCheck className="h-4 w-4 text-emerald-600" />
                HRMS chat workspace is connected
              </div>
              <div className="mt-3 flex flex-wrap gap-2 text-sm text-slate-600">
                <span className="rounded-full bg-white px-3 py-1.5">{ka.currentChannel}: {props.config?.preferred_channel}</span>
                <span className="rounded-full bg-white px-3 py-1.5">Team: {props.config?.default_team ?? 'workspace'}</span>
                {props.config?.mattermost_username ? <span className="rounded-full bg-white px-3 py-1.5">@{props.config.mattermost_username}</span> : null}
              </div>
              {!embedAllowed ? (
                <p className="mt-3 text-sm text-slate-500">
                  Chat is opening through the tenant Mattermost workspace. Direct in-page embedding depends on the final SSO / reverse-proxy setup, so this build launches the real workspace cleanly in a new tab.
                </p>
              ) : null}
            </div>
            <a className="inline-flex items-center justify-center gap-2 rounded-2xl bg-slate-950 px-5 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-slate-800" href={channelUrl ?? '#'} target="_blank" rel="noreferrer">
              {ka.openMattermost}
              <ExternalLink className="h-4 w-4" />
            </a>
          </div>
          {embedAllowed ? (
            <iframe
              title="Mattermost"
              src={channelUrl ?? undefined}
              className="h-[720px] w-full rounded-xl border border-slate-200"
              referrerPolicy="strict-origin-when-cross-origin"
            />
          ) : (
            <div className="grid gap-4 rounded-2xl border border-dashed border-slate-300 bg-white p-8 lg:grid-cols-[minmax(0,1fr)_minmax(260px,0.7fr)]">
              <div>
                <div className="flex items-center gap-2 text-base font-semibold text-slate-950">
                  <MessageCircleMore className="h-5 w-5 text-action-600" />
                  Launch company chat
                </div>
                <p className="mt-3 text-sm leading-7 text-slate-600">
                  Your company chat workspace is connected and ready. Open the live Mattermost workspace to continue conversations, department updates, and HR notifications in the tenant-isolated environment.
                </p>
              </div>
              <div className="rounded-2xl border border-slate-200 bg-slate-50 p-5 text-sm text-slate-600">
                <div className="font-semibold text-slate-900">Workspace</div>
                <div className="mt-2 break-all">{props.config?.server_base_url}</div>
                <div className="mt-4 font-semibold text-slate-900">Default team</div>
                <div className="mt-2">{props.config?.default_team ?? 'N/A'}</div>
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="p-5">
          <div className="rounded-xl border border-dashed border-slate-300 px-6 py-16 text-center text-slate-500">
            {ka.chatNotLinked}
          </div>
        </div>
      )}
    </article>
  )
}
