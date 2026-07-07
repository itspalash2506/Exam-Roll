import { Users, BookOpen, FileText, Percent, Files } from 'lucide-react'
import { motion } from 'framer-motion'
import { formatDocType } from '../../utils/formatters.js'
import { cardHover, useCountUp, useReducedMotion } from '../../lib/motion.js'

function StatShell({ icon: Icon, label, children }) {
  const reduced = useReducedMotion()
  return (
    <motion.div
      whileHover={cardHover(reduced)}
      className="rounded-2xl border border-line bg-surface p-5 shadow-warm"
    >
      <Icon size={18} className="mb-3 text-muted" strokeWidth={1.75} />
      {children}
      <p className="mt-1 text-caption text-muted">{label}</p>
    </motion.div>
  )
}

function NumberStat({ icon, value, label, suffix = '' }) {
  const display = useCountUp(value)
  return (
    <StatShell icon={icon} label={label}>
      <p className="font-display text-h1 font-medium tabular-nums text-ink">
        {display}
        {suffix}
      </p>
    </StatShell>
  )
}

function TextStat({ icon, value, label }) {
  return (
    <StatShell icon={icon} label={label}>
      <p className="truncate font-display text-h2 font-medium text-ink">{value ?? '—'}</p>
    </StatShell>
  )
}

export default function StudentSummary({ extractedData, fileCount = 1 }) {
  if (!extractedData) return null

  const {
    total_students,
    subjects = [],
    document_type,
    ai_confidence,
  } = extractedData

  return (
    <div className="space-y-3">
      {fileCount > 1 && (
        <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface px-2.5 py-1 text-caption font-medium text-muted">
          <Files size={12} />
          Aggregated from {fileCount} files
        </span>
      )}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <NumberStat icon={Users} value={total_students ?? 0} label="Total Students" />
        <NumberStat icon={BookOpen} value={subjects.length} label="Subjects Detected" />
        <TextStat icon={FileText} value={formatDocType(document_type)} label="Document Type" />
        <NumberStat icon={Percent} value={Math.round((ai_confidence ?? 0) * 100)} suffix="%" label="AI Confidence" />
      </div>
    </div>
  )
}
