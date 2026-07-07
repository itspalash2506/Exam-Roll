import { Link, useLocation } from 'react-router-dom'
import { LayoutDashboard, Upload, Clock } from 'lucide-react'
import clsx from 'clsx'

const items = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/upload', icon: Upload, label: 'Upload' },
  { to: '/history', icon: Clock, label: 'History' },
]

export default function Sidebar() {
  const { pathname } = useLocation()
  return (
    <aside className="hidden w-60 flex-shrink-0 border-r border-line bg-canvas md:flex md:flex-col">
      <nav className="mt-6 space-y-1 px-3">
        {items.map(({ to, icon: Icon, label }) => {
          const active = pathname === to || (to !== '/' && pathname.startsWith(to))
          return (
            <Link
              key={to}
              to={to}
              className={clsx(
                'flex items-center gap-3 rounded-xl px-3 py-2.5 text-small font-medium transition-colors duration-fast',
                active
                  ? 'bg-primary text-canvas'
                  : 'text-muted hover:bg-line/50 hover:text-ink',
              )}
            >
              <Icon size={17} />
              {label}
            </Link>
          )
        })}
      </nav>
    </aside>
  )
}
