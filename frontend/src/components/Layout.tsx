import { Link, useLocation } from 'react-router-dom'
import { BookOpen, LogOut } from 'lucide-react'
import { useAuth } from '../auth'
import BrandMark from './BrandMark'
import LicenseNotice from './LicenseNotice'

export default function Layout({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth()
  const loc = useLocation()
  const isWritePage = /\/write\/\d+/.test(loc.pathname)

  return (
    <div className={`min-h-screen ${isWritePage ? 'bg-white' : 'bg-gradient-to-br from-slate-50 via-white to-brand-50'}`}>
      <header className="sticky top-0 z-40 border-b border-slate-200/80 bg-white/80 backdrop-blur">
        <div className={`flex items-center justify-between px-4 py-3 ${isWritePage ? 'w-full' : 'mx-auto max-w-7xl'}`}>
          <Link to="/dashboard" className="flex items-center gap-2 font-semibold text-brand-900">
            <BrandMark className="h-8 w-8 rounded-lg shadow-sm ring-1 ring-slate-200/80" />
            <span>NovFlow</span>
          </Link>
          <nav className="hidden items-center gap-6 text-sm text-slate-600 md:flex">
            <Link to="/dashboard" className={loc.pathname.startsWith('/dashboard') ? 'text-brand-700 font-medium' : 'hover:text-brand-700'}>
              书库
            </Link>
            <Link to="/new" className={loc.pathname === '/new' ? 'text-brand-700 font-medium' : 'hover:text-brand-700'}>
              新建书籍
            </Link>
            <Link to="/settings" className={loc.pathname === "/settings" ? "text-brand-700 font-medium" : "hover:text-brand-700"}>
              设置
            </Link>
          </nav>
          <div className="flex items-center gap-3 text-sm">
            <span className="hidden text-slate-500 sm:inline">{user?.display_name}</span>
            <button onClick={logout} className="btn-secondary py-1.5 px-3">
              <LogOut className="h-4 w-4" /> 退出
            </button>
          </div>
        </div>
      </header>
      <LicenseNotice />
      <main className={isWritePage ? 'h-[calc(100vh-57px)] overflow-hidden' : 'mx-auto max-w-7xl px-4 py-6'}>
        {children}
      </main>
    </div>
  )
}

export function PageHeader({ title, desc, action }: { title: string; desc?: string; action?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">{title}</h1>
        {desc && <p className="mt-1 text-sm text-slate-500">{desc}</p>}
      </div>
      {action}
    </div>
  )
}

export function EmptyState({ icon: Icon = BookOpen, title, desc, action }: {
  icon?: React.ComponentType<{ className?: string }>
  title: string
  desc: string
  action?: React.ReactNode
}) {
  return (
    <div className="card flex flex-col items-center px-6 py-16 text-center">
      <Icon className="mb-4 h-12 w-12 text-slate-300" />
      <h3 className="text-lg font-semibold">{title}</h3>
      <p className="mt-2 max-w-md text-sm text-slate-500">{desc}</p>
      {action && <div className="mt-6">{action}</div>}
    </div>
  )
}

export function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="card p-4">
      <div className="text-sm text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-bold text-brand-900">{value}</div>
      {sub && <div className="mt-1 text-xs text-slate-400">{sub}</div>}
    </div>
  )
}

export function Badge({ children, color = 'slate' }: { children: React.ReactNode; color?: string }) {
  const colors: Record<string, string> = {
    slate: 'bg-slate-100 text-slate-700',
    green: 'bg-emerald-100 text-emerald-700',
    amber: 'bg-amber-100 text-amber-700',
    red: 'bg-red-100 text-red-700',
    blue: 'bg-blue-100 text-blue-700',
  }
  return <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${colors[color] || colors.slate}`}>{children}</span>
}
