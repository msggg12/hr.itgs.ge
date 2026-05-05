import {
  Activity,
  AppWindow,
  BadgeCheck,
  BriefcaseBusiness,
  CalendarRange,
  CircleHelp,
  DollarSign,
  GitBranchPlus,
  HardDrive,
  LayoutDashboard,
  LogOut,
  MessagesSquare,
  Settings,
  Users
} from 'lucide-react'

import { ka } from '../i18n/ka'
import type { FeatureFlags } from '../types'
import type { TenantBranding } from '../tenantBranding'
import { classNames } from '../utils'
import { CompanyBadge } from './CompanyBadge'

const navigation = [
  { key: 'dashboard', label: ka.dashboard, icon: LayoutDashboard },
  { key: 'employees', label: ka.employees, icon: Users },
  { key: 'attendance', label: ka.attendance, icon: Activity, feature: 'attendance_enabled' },
  { key: 'leave', label: ka.leaveHub, icon: CalendarRange },
  { key: 'payroll', label: ka.payroll, icon: DollarSign, feature: 'payroll_enabled' },
  { key: 'ats', label: ka.ats, icon: BriefcaseBusiness, feature: 'ats_enabled' },
  { key: 'assets', label: ka.assets, icon: HardDrive, feature: 'assets_enabled' },
  { key: 'org_chart', label: 'Org Chart', icon: GitBranchPlus, feature: 'org_chart_enabled' },
  { key: 'okrs', label: ka.okrs, icon: BadgeCheck, feature: 'performance_enabled' },
  { key: 'team_chat', label: ka.teamChat, icon: MessagesSquare, feature: 'chat_enabled' }
] as const

const utilityRows = [
  { key: 'settings', label: ka.settings, icon: Settings },
  { key: 'integrations', label: 'Apps & Integration', icon: AppWindow },
  { key: 'support', label: 'Help & Support', icon: CircleHelp }
] as const

type SidebarProps = {
  collapsed: boolean
  activeKey: string
  branding: TenantBranding
  featureFlags: FeatureFlags
  allowedSections: string[]
  onSelect: (key: string) => void
  onToggle: () => void
  onLogout: () => void
  mobileOpen?: boolean
  onCloseMobile?: () => void
}

function NavButton(props: {
  label: string
  collapsed: boolean
  active?: boolean
  icon: typeof LayoutDashboard
  onClick: () => void
}) {
  const Icon = props.icon

  return (
    <button
      type="button"
      onClick={props.onClick}
      className={classNames(
        'group relative flex w-full items-center gap-3 rounded-2xl px-3 py-2.5 text-[13px] transition-all duration-200',
        props.active
          ? 'bg-white/[0.06] text-white'
          : 'text-slate-300 hover:bg-white/[0.025] hover:text-white'
      )}
    >
      {props.active ? (
        <span className="absolute left-0 top-2.5 bottom-2.5 w-[3px] rounded-r-full bg-[linear-gradient(180deg,#93C5FD_0%,#60A5FA_100%)]" />
      ) : null}
      <span
        className={classNames(
          'flex h-9 w-9 shrink-0 items-center justify-center rounded-xl transition',
          props.active ? 'text-white' : 'text-slate-400 group-hover:text-slate-100'
        )}
      >
        <Icon className="h-[18px] w-[18px]" />
      </span>
      {!props.collapsed ? (
        <span className={classNames('truncate font-medium', props.active && 'pl-1')}>{props.label}</span>
      ) : null}
    </button>
  )
}

export function Sidebar(props: SidebarProps) {
  const items = navigation.filter((item) => props.allowedSections.includes(item.key) && (!item.feature || props.featureFlags[item.feature]))

  return (
    <aside
      className={classNames(
        'shrink-0 flex-col overflow-hidden border border-white/10 bg-[linear-gradient(180deg,rgba(2,6,23,0.92)_0%,rgba(15,23,42,0.94)_52%,rgba(24,24,27,0.94)_100%)] text-slate-50 backdrop-blur-2xl',
        props.collapsed ? 'w-[88px]' : 'w-[268px]',
        'shadow-[0_28px_70px_rgba(2,8,23,0.48)] max-lg:fixed max-lg:inset-y-0 max-lg:left-0 max-lg:z-50 max-lg:transition-transform',
        props.mobileOpen ? 'flex max-lg:translate-x-0' : 'hidden max-lg:-translate-x-full',
        'lg:fixed lg:bottom-3 lg:left-3 lg:top-3 lg:z-30 lg:flex lg:translate-x-0'
      )}
    >
      <div className="border-b border-white/10 px-4 pb-3 pt-4">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            {!props.collapsed ? (
              <CompanyBadge branding={props.branding} nameOnly inverted toggleable collapsed={props.collapsed} onToggle={props.onToggle} />
            ) : (
              <CompanyBadge branding={props.branding} compact toggleable collapsed={props.collapsed} onToggle={props.onToggle} />
            )}
          </div>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden px-3 py-3">
        <div className="space-y-1">
          {items.map((item) => (
            <NavButton
              key={item.key}
              label={item.label}
              collapsed={props.collapsed}
              active={props.activeKey === item.key}
              icon={item.icon}
              onClick={() => {
                props.onSelect(item.key)
                props.onCloseMobile?.()
              }}
            />
          ))}
        </div>

        <div className="mt-4 border-t border-white/10 pt-3">
          <div className="space-y-1">
            {utilityRows.map((row) => (
              <NavButton
                key={row.key}
                label={row.label}
                collapsed={props.collapsed}
                active={props.activeKey === row.key}
                icon={row.icon}
                onClick={() => {
                  props.onSelect(row.key)
                  props.onCloseMobile?.()
                }}
              />
            ))}
          </div>
        </div>
      </div>

      <div className="border-t border-white/10 p-3">
        {!props.collapsed ? (
          <div className="space-y-2.5">
            <div className="rounded-2xl border border-white/10 bg-white/[0.05] px-3 py-2.5 backdrop-blur-xl">
              <p className="truncate text-sm font-semibold text-white">{props.branding.companyName}</p>
              <p className="mt-1 text-xs text-slate-300">ადმინისტრატორის სივრცე</p>
            </div>
            <button
              type="button"
              className="flex w-full items-center justify-center gap-2 rounded-2xl border border-white/10 bg-white/[0.05] px-4 py-2.5 text-sm font-semibold text-slate-100 transition hover:border-white/20 hover:bg-white/[0.1]"
              onClick={props.onLogout}
            >
              <LogOut className="h-4 w-4" />
              გასვლა
            </button>
          </div>
        ) : (
          <button
            type="button"
            className="flex w-full items-center justify-center rounded-2xl border border-white/10 bg-white/[0.04] p-3 text-slate-100 transition hover:border-white/15 hover:bg-white/[0.08]"
            onClick={props.onLogout}
          >
            <LogOut className="h-4 w-4" />
          </button>
        )}
      </div>
    </aside>
  )
}
