import { useState, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Trash2, Eye, Clock, FileText } from 'lucide-react'
import { getJobs, deleteJob } from '../api/client.js'
import Badge from '../components/common/Badge.jsx'
import LoadingSkeleton from '../components/common/LoadingSkeleton.jsx'
import Modal from '../components/common/Modal.jsx'
import Button from '../components/common/Button.jsx'
import { formatDate, formatDocType } from '../utils/formatters.js'
import { staggerContainer, staggerItem, useReducedMotion } from '../lib/motion.js'
import toast from 'react-hot-toast'

const PAGE_SIZE = 20

export default function History() {
  useEffect(() => {
    document.title = 'History | ExamRoll'
  }, [])

  const [page, setPage] = useState(0)
  const [deleting, setDeleting] = useState(null)
  const [confirmId, setConfirmId] = useState(null)
  const queryClient = useQueryClient()
  const reduced = useReducedMotion()

  const { data: jobs = [], isLoading } = useQuery({
    queryKey: ['jobs', page],
    queryFn: async () => {
      const res = await getJobs(page * PAGE_SIZE, PAGE_SIZE)
      return res.data ?? []
    },
    staleTime: 30_000,
  })

  const handleDelete = async (jobId) => {
    setDeleting(jobId)
    try {
      await deleteJob(jobId)
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
      toast.success('Job deleted')
    } catch (err) {
      toast.error(err.message || 'Delete failed')
    } finally {
      setDeleting(null)
      setConfirmId(null)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Clock size={20} className="text-primary" />
        <h1 className="font-display text-h1 font-medium text-ink">Job History</h1>
      </div>

      <div className="rounded-2xl border border-line bg-surface shadow-warm overflow-hidden">
        {isLoading ? (
          <LoadingSkeleton rows={8} />
        ) : jobs.length === 0 ? (
          <div className="flex flex-col items-center py-16 text-center">
            <FileText size={40} className="mb-4 text-muted/30" strokeWidth={1.5} />
            <p className="font-display text-h3 font-medium text-ink">Nothing here yet</p>
            <p className="mt-1.5 text-small text-muted">
              <Link to="/upload" className="text-primary hover:underline">Upload your first file</Link> to see it here
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-line">
              <thead>
                <tr className="bg-canvas">
                  {['Filename', 'Type', 'Students', 'Status', 'Date', 'Actions'].map((h) => (
                    <th
                      key={h}
                      className="px-5 py-3 text-left text-caption font-semibold uppercase tracking-wide text-muted"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <motion.tbody
                variants={staggerContainer(reduced)}
                initial="hidden"
                animate="show"
                className="divide-y divide-line"
              >
                {jobs.map((job) => (
                  <motion.tr key={job.id} variants={staggerItem(reduced)} className="transition-colors duration-fast hover:bg-highlight/10">
                    <td className="px-5 py-3.5">
                      <p className="max-w-[200px] truncate text-small font-medium text-ink">
                        {job.filename}
                      </p>
                      <p className="mt-0.5 font-mono text-caption text-muted">{job.id.slice(0, 8)}…</p>
                    </td>
                    <td className="px-5 py-3.5 text-small text-muted">
                      {formatDocType(job.document_type) || '—'}
                    </td>
                    <td className="px-5 py-3.5 text-small text-muted">
                      {job.total_students ?? '—'}
                    </td>
                    <td className="px-5 py-3.5">
                      <Badge status={job.status} />
                    </td>
                    <td className="px-5 py-3.5 text-small text-muted whitespace-nowrap">
                      {formatDate(job.created_at)}
                    </td>
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-2">
                        <Link
                          to={`/jobs/${job.id}`}
                          className="inline-flex items-center gap-1 rounded-xl border border-line px-2.5 py-1.5 text-caption font-medium text-primary transition-colors duration-fast hover:bg-highlight/30"
                        >
                          <Eye size={12} /> View
                        </Link>
                        <button
                          onClick={() => setConfirmId(job.id)}
                          disabled={deleting === job.id}
                          className="inline-flex items-center gap-1 rounded-xl border border-error/25 px-2.5 py-1.5 text-caption font-medium text-error transition-colors duration-fast hover:bg-error/10 disabled:opacity-50"
                        >
                          <Trash2 size={12} /> Delete
                        </button>
                      </div>
                    </td>
                  </motion.tr>
                ))}
              </motion.tbody>
            </table>
          </div>
        )}
      </div>

      {/* Pagination */}
      {!isLoading && jobs.length > 0 && (
        <div className="flex items-center justify-between">
          <p className="text-caption text-muted">
            Page {page + 1} · Showing {jobs.length} jobs
          </p>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
            >
              ← Previous
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setPage((p) => p + 1)}
              disabled={jobs.length < PAGE_SIZE}
            >
              Next →
            </Button>
          </div>
        </div>
      )}

      {/* Delete confirmation modal */}
      <Modal
        open={!!confirmId}
        onClose={() => setConfirmId(null)}
        title="Delete Job"
      >
        <p className="text-small text-muted mb-5">
          Are you sure you want to delete this job? The uploaded file and any generated outputs will also be removed.
          This action cannot be undone.
        </p>
        <div className="flex gap-3">
          <Button
            variant="danger"
            size="md"
            className="flex-1"
            onClick={() => handleDelete(confirmId)}
            loading={deleting === confirmId}
          >
            Delete Job
          </Button>
          <Button
            variant="ghost"
            size="md"
            onClick={() => setConfirmId(null)}
          >
            Cancel
          </Button>
        </div>
      </Modal>
    </div>
  )
}
