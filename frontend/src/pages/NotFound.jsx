import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import { Home, Upload } from 'lucide-react'

export default function NotFound() {
  useEffect(() => {
    document.title = '404 Not Found | ExamRoll'
  }, [])

  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] text-center space-y-6">
      <p className="font-display text-[7rem] font-medium leading-none text-primary/90" style={{ fontVariationSettings: "'SOFT' 40" }}>
        404
      </p>
      <div className="space-y-2">
        <p className="font-display text-h2 font-medium text-ink">Page not found</p>
        <p className="max-w-xs text-small text-muted">
          The page you&rsquo;re looking for doesn&rsquo;t exist or has been moved.
        </p>
      </div>
      <div className="flex gap-3">
        <Link
          to="/"
          className="inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2 text-small font-medium text-canvas transition-colors duration-fast hover:bg-primary-hover"
        >
          <Home size={16} /> Go Home
        </Link>
        <Link
          to="/upload"
          className="inline-flex items-center gap-2 rounded-xl border border-primary px-4 py-2 text-small font-medium text-primary transition-colors duration-fast hover:bg-highlight/20"
        >
          <Upload size={16} /> Upload File
        </Link>
      </div>
    </div>
  )
}
