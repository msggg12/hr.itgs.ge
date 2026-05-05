import { useEffect, useState } from 'react'

import { Mail, MessageSquareShare, SendHorizontal } from 'lucide-react'

import type { MessageChannel } from '../types'
import { classNames } from '../utils'

type MessageComposerModalProps = {
  open: boolean
  targetName: string
  availableChannels: MessageChannel[]
  busy?: boolean
  onClose: () => void
  onSend: (payload: { channel: MessageChannel; subject: string; message: string }) => void
}

const channelMeta: Record<MessageChannel, { label: string; description: string; icon: typeof MessageSquareShare }> = {
  slack: {
    label: 'Slack DM',
    description: 'Send a direct Slack message to the employee.',
    icon: MessageSquareShare,
  },
  email: {
    label: 'Google Workspace Email',
    description: 'Send an email using the connected company mailbox.',
    icon: Mail,
  },
}

export function MessageComposerModal(props: MessageComposerModalProps) {
  const [channel, setChannel] = useState<MessageChannel>('slack')
  const [subject, setSubject] = useState('HR Update')
  const [message, setMessage] = useState('')

  useEffect(() => {
    if (!props.open) {
      return
    }
    const nextChannel = props.availableChannels[0] ?? 'email'
    setChannel(nextChannel)
    setSubject('HR Update')
    setMessage('')
  }, [props.availableChannels, props.open])

  if (!props.open) {
    return null
  }

  const hasChannels = props.availableChannels.length > 0

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-950/50 px-4 backdrop-blur-sm">
      <div className="w-full max-w-xl rounded-[28px] border border-white/50 bg-[rgba(255,252,248,0.96)] p-6 shadow-[0_28px_70px_rgba(15,23,42,0.18)]">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.26em] text-slate-400">Quick Message</p>
            <h3 className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-slate-950">{props.targetName}</h3>
            <p className="mt-2 text-sm text-slate-500">Send a direct update from the dashboard using your connected workspace apps.</p>
          </div>
          <button type="button" className="muted-btn px-4 py-2" onClick={props.onClose}>
            Close
          </button>
        </div>

        {!hasChannels ? (
          <div className="mt-5 rounded-2xl border border-dashed border-slate-200 bg-white/70 px-5 py-10 text-center text-sm text-slate-500">
            Connect Slack or company email in Apps & Integrations to enable direct messaging.
          </div>
        ) : (
          <>
            <div className="mt-5 grid gap-3 sm:grid-cols-2">
              {props.availableChannels.map((option) => {
                const meta = channelMeta[option]
                const Icon = meta.icon
                return (
                  <button
                    key={option}
                    type="button"
                    onClick={() => setChannel(option)}
                    className={classNames(
                      'rounded-[22px] border px-4 py-4 text-left transition',
                      channel === option
                        ? 'border-[rgba(var(--brand-primary-rgb),0.28)] bg-[rgba(var(--brand-primary-rgb),0.12)] shadow-[0_14px_30px_rgba(32,81,189,0.12)]'
                        : 'border-slate-200 bg-white/78 hover:border-slate-300 hover:bg-white'
                    )}
                  >
                    <div className="flex items-center gap-3">
                      <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-slate-950 text-white">
                        <Icon className="h-5 w-5" />
                      </div>
                      <div>
                        <p className="font-semibold text-slate-950">{meta.label}</p>
                        <p className="mt-1 text-xs text-slate-500">{meta.description}</p>
                      </div>
                    </div>
                  </button>
                )
              })}
            </div>

            {channel === 'email' ? (
              <div className="mt-5">
                <label className="mb-2 block text-xs font-semibold uppercase tracking-[0.24em] text-slate-400" htmlFor="message-subject">
                  Subject
                </label>
                <input
                  id="message-subject"
                  className="input-shell w-full"
                  value={subject}
                  onChange={(event) => setSubject(event.target.value)}
                  placeholder="HR Update"
                />
              </div>
            ) : null}

            <div className="mt-5">
              <label className="mb-2 block text-xs font-semibold uppercase tracking-[0.24em] text-slate-400" htmlFor="message-body">
                Message
              </label>
              <textarea
                id="message-body"
                className="input-shell min-h-[180px] w-full resize-none"
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                placeholder="Type your message here..."
              />
            </div>

            <div className="mt-6 flex items-center justify-between gap-3">
              <p className="text-xs text-slate-500">Messages are sent immediately using the selected connected app.</p>
              <button
                type="button"
                className="primary-btn px-5 py-3"
                disabled={props.busy || !message.trim()}
                onClick={() => props.onSend({ channel, subject, message: message.trim() })}
              >
                <SendHorizontal className="h-4 w-4" />
                {props.busy ? 'Sending...' : 'Send'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
