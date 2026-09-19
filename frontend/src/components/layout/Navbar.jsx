import { Link, useNavigate } from 'react-router-dom'
import { Plus, Clock, LogOut } from 'lucide-react'
import { useAuth } from '../../context/AuthContext.jsx'

function Wordmark() {
  return (
    <Link to="/" className="flex items-center gap-2.5 group">
      <span className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl bg-primary text-canvas transition-colors duration-fast group-hover:bg-primary-hover">
        <span className="font-display text-[15px] font-semibold leading-none" style={{ fontVariationSettings: "'SOFT' 20" }}>
          ER
        </span>
      </span>
      <span className="font-display text-xl font-semibold text-ink tracking-tight">ExamRoll</span>
    </Link>
  )
}

export default function Navbar() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  const handleLogout = async () => {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <nav className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-line bg-canvas px-6">
      <Wordmark />

      <div className="flex items-center gap-3">
        <Link
          to="/history"
          className="flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-small font-medium text-muted transition-colors duration-fast hover:bg-line/60 hover:text-ink"
        >
          <Clock size={15} />
          History
        </Link>
        <Link
          to="/upload"
          className="flex items-center gap-1.5 rounded-xl bg-primary px-4 py-1.5 text-small font-medium text-canvas transition-colors duration-fast hover:bg-primary-hover"
        >
          <Plus size={15} />
          New Upload
        </Link>
        {user && (
          <button
            type="button"
            onClick={handleLogout}
            title={`Sign out (${user.email})`}
            className="flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-small font-medium text-muted transition-colors duration-fast hover:bg-line/60 hover:text-ink"
          >
            <LogOut size={15} />
          </button>
        )}
      </div>
    </nav>
  )
}
