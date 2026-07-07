import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Download, RefreshCw } from 'lucide-react'
import { getJob } from '../api/client.js'
import { useJobStatus } from '../hooks/useJobStatus.js'
import { useExport } from '../hooks/useExport.js'
import ProgressBar from '../components/common/ProgressBar.jsx'
import StudentSummary from '../components/preview/StudentSummary.jsx'
import SubjectTable from '../components/preview/SubjectTable.jsx'
import StylePanel, { DEFAULT_STYLE } from '../components/customize/StylePanel.jsx'
import Badge from '../components/common/Badge.jsx'
import Button from '../components/common/Button.jsx'
import LoadingSkeleton from '../components/common/LoadingSkeleton.jsx'
import { formatDate } from '../utils/formatters.js'

export default function JobDetail() {
  const { jobId } = useParams()
  const { status: wsStatus, progress, message } = useJobStatus(jobId)
  const { triggerExport, exporting } = useExport()
  const [style, setStyle] = useState(DEFAULT_STYLE)
  const [filename, setFilename] = useState('Subject-wise-Roll-Number-List')

  useEffect(() => {
    document.title = 'Job Detail | ExamRoll'
  }, [])

  const { data: job, isLoading, refetch } = useQuery({
    queryKey: ['job', jobId],
    queryFn: async () => {
      const res = await getJob(jobId)
      return res.data
    },
    refetchInterval: (data) => {
      if (!data) return 3000
      if (data.status === 'completed' || data.status === 'failed') return false
      return 3000
    },
  })

  const isDone = job?.status === 'completed'
  const isFailed = job?.status === 'failed'
  const isProcessing = job?.status === 'processing' || job?.status === 'queued'

  if (isLoading) {
    return (
      <div className="space-y-4">
        <LoadingSkeleton rows={3} />
      </div>
    )
  }

  if (!job) {
    return (
      <div className="rounded-2xl border border-error/25 bg-error/5 p-6 text-small text-error">
        Job not found.{' '}
        <Link to="/history" className="underline">View history</Link>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start gap-4">
        <Link
          to="/history"
          className="mt-0.5 flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl border border-line bg-surface text-muted transition-colors duration-fast hover:bg-highlight/20 hover:text-ink"
        >
          <ArrowLeft size={16} />
        </Link>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 flex-wrap">
            <h1 className="truncate font-display text-h1 font-medium text-ink">{job.filename}</h1>
            <Badge status={job.status} />
          </div>
          <p className="mt-1 text-caption text-muted">
            Job ID: <code>{job.id.slice(0, 8)}…</code> · Created {formatDate(job.created_at)}
          </p>
        </div>
        <button
          onClick={() => refetch()}
          className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl border border-line bg-surface text-muted transition-colors duration-fast hover:bg-highlight/20 hover:text-ink"
          title="Refresh"
        >
          <RefreshCw size={15} />
        </button>
      </div>

      {/* Progress bar when processing */}
      {isProcessing && (
        <div className="rounded-2xl border border-line bg-surface p-6 shadow-warm">
          <ProgressBar
            value={progress || job.progress || 0}
            status={wsStatus || job.status}
            message={message || `Job is ${job.status}…`}
          />
        </div>
      )}

      {/* Error state */}
      {isFailed && (
        <div className="rounded-2xl border border-error/25 bg-error/5 p-5">
          <p className="text-small font-medium text-error mb-1">Processing Failed</p>
          <p className="text-small text-error/80">{job.error_message || 'An unknown error occurred.'}</p>
        </div>
      )}

      {/* Completed state */}
      {isDone && job.extracted_data && (
        <>
          <StudentSummary extractedData={job.extracted_data} fileCount={job.file_count ?? 1} />
          <SubjectTable extractedData={job.extracted_data} />

          <StylePanel style={style} onChange={setStyle} />

          {/* Previously generated files */}
          {job.output_files?.length > 0 && (
            <div className="rounded-2xl border border-line bg-surface p-5 shadow-warm space-y-3">
              <h3 className="text-small font-semibold text-ink">Previous Downloads</h3>
              <ul className="space-y-2">
                {job.output_files.map((f) => (
                  <li key={f.id} className="flex items-center justify-between rounded-xl bg-canvas px-4 py-2.5">
                    <div>
                      <p className="text-small font-medium text-ink">{f.filename}</p>
                      <p className="text-caption text-muted">{f.file_size_kb} KB · {formatDate(f.created_at)}</p>
                    </div>
                    <a
                      href={`/api/v1/export/${job.id}/download/${f.id}`}
                      className="flex items-center gap-1.5 text-caption font-medium text-primary hover:text-primary-hover"
                    >
                      <Download size={13} /> Re-download
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Export panel */}
          <div className="rounded-2xl border border-line bg-surface p-5 shadow-warm space-y-4">
            <h3 className="text-small font-semibold text-ink">Generate Excel Output</h3>
            <div className="space-y-2">
              <label className="text-caption text-muted">Output Filename</label>
              <input
                type="text"
                value={filename}
                onChange={(e) => setFilename(e.target.value.replace(/[^a-zA-Z0-9_\- ]/g, ''))}
                className="w-full rounded-xl border border-line px-3 py-2 text-small focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </div>
            <Button
              variant="primary"
              size="lg"
              className="w-full"
              onClick={() => triggerExport(jobId, style, filename)}
              loading={exporting}
            >
              <Download size={16} />
              Download Excel
            </Button>
          </div>
        </>
      )}
    </div>
  )
}
