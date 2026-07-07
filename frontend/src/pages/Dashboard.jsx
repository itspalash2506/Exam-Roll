import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Upload, FileText, Users, Clock, ArrowRight, BarChart2 } from 'lucide-react'
import { getJobs } from '../api/client.js'
import Badge from '../components/common/Badge.jsx'
import LoadingSkeleton from '../components/common/LoadingSkeleton.jsx'
import { formatDate, formatDocType } from '../utils/formatters.js'
import { cardHover, staggerContainer, staggerItem, useCountUp, useReducedMotion } from '../lib/motion.js'

function Stat({ icon: Icon, label, value }) {
  const reduced = useReducedMotion()
  const display = useCountUp(value)
  return (
    <motion.div
      variants={staggerItem(reduced)}
      whileHover={cardHover(reduced)}
      className="rounded-2xl border border-line bg-surface p-5 shadow-warm"
    >
      <div className="mb-3 inline-flex h-10 w-10 items-center justify-center rounded-xl bg-highlight/50">
        <Icon size={19} className="text-primary" strokeWidth={1.75} />
      </div>
      <p className="font-display text-h1 font-medium tabular-nums text-ink">{display}</p>
      <p className="mt-0.5 text-caption text-muted">{label}</p>
    </motion.div>
  )
}

function StatsBar({ jobs }) {
  const reduced = useReducedMotion()
  const total = jobs.length
  const totalStudents = jobs.reduce((s, j) => s + (j.total_students || 0), 0)
  const completed = jobs.filter((j) => j.status === 'completed').length

  return (
    <motion.div
      variants={staggerContainer(reduced)}
      initial="hidden"
      animate="show"
      className="grid grid-cols-3 gap-4"
    >
      <Stat icon={FileText} label="Files Processed" value={total} />
      <Stat icon={Users} label="Students Processed" value={totalStudents} />
      <Stat icon={BarChart2} label="Completed Jobs" value={completed} />
    </motion.div>
  )
}

export default function Dashboard() {
  useEffect(() => {
    document.title = 'Dashboard | ExamRoll'
  }, [])

  const reduced = useReducedMotion()

  const { data: jobs = [], isLoading } = useQuery({
    queryKey: ['jobs'],
    queryFn: async () => {
      const res = await getJobs(0, 50)
      return res.data ?? []
    },
    staleTime: 30_000,
  })

  const recentJobs = jobs.slice(0, 5)

  return (
    <div className="space-y-8">
      {/* Welcome header */}
      <div>
        <h1 className="font-display text-h1 font-medium text-ink">Welcome to ExamRoll</h1>
        <p className="mt-1 text-small text-muted">
          Upload attestation sheets to auto-extract roll numbers and generate styled Excel reports.
        </p>
      </div>

      {/* Quick upload card */}
      <Link
        to="/upload"
        className="group flex items-center gap-5 rounded-2xl border-2 border-dashed border-primary/40 bg-surface p-6 shadow-warm transition-all duration-base ease-standard hover:border-primary hover:shadow-warm-lift"
      >
        <span className="flex h-14 w-14 flex-shrink-0 items-center justify-center rounded-xl bg-primary shadow-warm transition-colors duration-fast group-hover:bg-primary-hover">
          <Upload size={26} className="text-canvas" />
        </span>
        <div className="flex-1">
          <p className="font-display text-h3 font-medium text-ink">
            Upload a new document
          </p>
          <p className="mt-0.5 text-small text-muted">
            PDF or Excel attestation sheet · AI-powered extraction · Export to styled Excel
          </p>
        </div>
        <ArrowRight size={20} className="text-muted transition-colors duration-fast group-hover:text-primary" />
      </Link>

      {/* Stats row */}
      {!isLoading && jobs.length > 0 && <StatsBar jobs={jobs} />}

      {/* Recent jobs */}
      <div className="rounded-2xl border border-line bg-surface shadow-warm overflow-hidden">
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <div className="flex items-center gap-2">
            <Clock size={16} className="text-primary" />
            <h2 className="text-small font-semibold text-ink">Recent Jobs</h2>
          </div>
          <Link
            to="/history"
            className="text-caption font-medium text-primary hover:text-primary-hover"
          >
            View all →
          </Link>
        </div>

        {isLoading ? (
          <LoadingSkeleton rows={5} />
        ) : recentJobs.length === 0 ? (
          <div className="flex flex-col items-center py-16 text-center">
            <FileText size={36} className="mb-4 text-muted/30" strokeWidth={1.5} />
            <p className="font-display text-h3 font-medium text-ink">Nothing here yet</p>
            <p className="mt-1.5 text-small text-muted">
              <Link to="/upload" className="text-primary hover:underline">Upload your first file</Link> to get started
            </p>
          </div>
        ) : (
          <motion.ul
            variants={staggerContainer(reduced)}
            initial="hidden"
            animate="show"
            className="divide-y divide-line"
          >
            {recentJobs.map((job) => (
              <motion.li
                key={job.id}
                variants={staggerItem(reduced)}
                className="flex items-center gap-4 px-5 py-3.5 transition-colors duration-fast hover:bg-highlight/10"
              >
                <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg border border-line bg-canvas">
                  <FileText size={16} className="text-muted" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="truncate text-small font-medium text-ink">{job.filename}</p>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className="text-caption text-muted">{formatDate(job.created_at)}</span>
                    {job.document_type && (
                      <>
                        <span className="text-line">·</span>
                        <span className="text-caption text-muted">{formatDocType(job.document_type)}</span>
                      </>
                    )}
                    {job.total_students != null && (
                      <>
                        <span className="text-line">·</span>
                        <span className="text-caption text-muted">{job.total_students} students</span>
                      </>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-3 flex-shrink-0">
                  <Badge status={job.status} />
                  <Link
                    to={`/jobs/${job.id}`}
                    className="text-caption font-medium text-primary hover:text-primary-hover"
                  >
                    View →
                  </Link>
                </div>
              </motion.li>
            ))}
          </motion.ul>
        )}
      </div>
    </div>
  )
}
