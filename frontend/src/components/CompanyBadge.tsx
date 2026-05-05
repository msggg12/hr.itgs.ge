import { ChevronLeft } from 'lucide-react'

import type { TenantBranding } from '../tenantBranding'

export function CompanyBadge(props: {
  branding: TenantBranding
  compact?: boolean
  inverted?: boolean
  nameOnly?: boolean
  toggleable?: boolean
  collapsed?: boolean
  onToggle?: () => void
}) {
  return (
    <div className="flex min-w-0 items-center gap-3 py-0.5">
      {props.toggleable ? (
        <button
          type="button"
          onClick={props.onToggle}
          className="group flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-white/12 text-sm font-bold text-white shadow-[0_16px_30px_rgba(15,23,42,0.28)] transition-transform duration-300 hover:scale-[1.02]"
          style={{ background: props.branding.primaryColor }}
          aria-label={props.collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          <span className="flex items-center gap-1">
            <span>{props.branding.logoText}</span>
            <ChevronLeft className={`h-3.5 w-3.5 transition-transform duration-300 ${props.collapsed ? 'rotate-180' : 'rotate-0'}`} />
          </span>
        </button>
      ) : (
        <div
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-white/12 text-sm font-bold text-white shadow-[0_16px_30px_rgba(15,23,42,0.28)]"
          style={{ background: props.branding.primaryColor }}
        >
          {props.branding.logoText}
        </div>
      )}
      {!props.compact ? (
        <div className="min-w-0 leading-tight">
          {!props.nameOnly ? (
            <p className={`text-[10px] font-semibold uppercase tracking-[0.2em] ${props.inverted ? 'text-slate-400/90' : 'text-slate-400'}`}>ITGS HR</p>
          ) : null}
          <p className={`${props.nameOnly ? '' : 'mt-1'} truncate text-[15px] font-semibold tracking-[-0.02em] ${props.inverted ? 'text-slate-50' : 'text-slate-900'}`}>
            {props.branding.companyName}
          </p>
        </div>
      ) : null}
    </div>
  )
}
