import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { LogIn } from 'lucide-react'
import Button from '../components/common/Button.jsx'
import { useAuth } from '../context/AuthContext.jsx'

const INPUT_CLASS =
  'w-full rounded-xl border border-line bg-surface px-3 py-2 text-small text-ink focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary'

export default function Login() {
  const { login, isAuthenticated, isLoading: authLoading } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    document.title = 'Sign in | ExamRoll'
  }, [])

  // Already logged in (e.g. a valid cookie from a previous visit) — skip
  // straight past the login form to wherever they were headed, or home.
  useEffect(() => {
    if (!authLoading && isAuthenticated) {
      const from = location.state?.from?.pathname || '/'
      navigate(from, { replace: true })
    }
  }, [authLoading, isAuthenticated, location.state, navigate])

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    try {
      await login(email, password)
      const from = location.state?.from?.pathname || '/'
      navigate(from, { replace: true })
    } catch (err) {
      toast.error(err.message || 'Invalid email or password')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-6">
      <div className="w-full max-w-sm space-y-8">
        <div className="flex flex-col items-center gap-3 text-center">
          <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-primary text-canvas">
            <span
              className="font-display text-[17px] font-semibold leading-none"
              style={{ fontVariationSettings: "'SOFT' 20" }}
            >
              ER
            </span>
          </span>
          <div>
            <h1 className="font-display text-h2 font-medium text-ink">ExamRoll</h1>
            <p className="text-small text-muted">Sign in to your exam centre workspace</p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4 rounded-2xl border border-line bg-surface p-6 shadow-warm">
          <label className="block space-y-1.5">
            <span className="text-caption text-muted">Email</span>
            <input
              type="email"
              required
              autoComplete="username"
              autoFocus
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className={INPUT_CLASS}
              placeholder="you@example.com"
            />
          </label>

          <label className="block space-y-1.5">
            <span className="text-caption text-muted">Password</span>
            <input
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={INPUT_CLASS}
              placeholder="••••••••"
            />
          </label>

          <Button type="submit" variant="primary" size="md" loading={submitting} className="w-full">
            <LogIn size={15} />
            Sign in
          </Button>
        </form>

        <p className="text-center text-caption text-muted">
          Accounts are created by your centre administrator — there is no self-signup.
        </p>
      </div>
    </div>
  )
}
