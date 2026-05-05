import type { ReactNode } from 'react'

import { Building2, Globe2, MapPinned, MonitorCog, Plug, Shield } from 'lucide-react'

import { classNames } from '../utils'

const navItems: Array<{ id: string; label: string; icon: typeof Building2 }> = [
  { id: 'settings-platform', label: 'Platform & tenants', icon: Globe2 },
  { id: 'settings-branding', label: 'Branding & policies', icon: Building2 },
  { id: 'settings-geo', label: 'Worksites & API keys', icon: MapPinned },
  { id: 'settings-permissions', label: 'Permissions & roles', icon: Shield },
  { id: 'settings-devices', label: 'Device registry', icon: MonitorCog },
]

type SettingsCategorizedLayoutProps = {
  onOpenIntegrations: () => void
  children: ReactNode
}

export function SettingsCategorizedLayout(props: SettingsCategorizedLayoutProps) {
  function scrollTo(id: string) {
    const el = document.getElementById(id)
    el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <div className="flex flex-col gap-6 xl:flex-row xl:items-start">
      <nav
        className="flex shrink-0 gap-2 overflow-x-auto pb-1 xl:sticky xl:top-4 xl:w-56 xl:flex-col xl:gap-1 xl:overflow-visible xl:pb-0"
        aria-label="Settings sections"
      >
        {navItems.map((item) => {
          const Icon = item.icon
          return (
            <button
              key={item.id}
              type="button"
              className={classNames(
                'flex min-w-[9.5rem] items-center gap-2 rounded-xl border px-3 py-2.5 text-left text-sm font-semibold transition xl:min-w-0',
                'border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-50'
              )}
              onClick={() => scrollTo(item.id)}
            >
              <Icon className="h-4 w-4 shrink-0 text-slate-500" />
              {item.label}
            </button>
          )
        })}
        <button
          type="button"
          className="flex min-w-[9.5rem] items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-left text-sm font-semibold text-slate-700 transition hover:border-slate-300 hover:bg-slate-50 xl:min-w-0"
          onClick={() => props.onOpenIntegrations()}
        >
          <Plug className="h-4 w-4 shrink-0 text-slate-500" />
          Integrations
        </button>
      </nav>
      <div className="min-w-0 flex-1 space-y-6">{props.children}</div>
    </div>
  )
}
