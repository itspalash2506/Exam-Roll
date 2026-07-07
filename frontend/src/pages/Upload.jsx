import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { Check } from 'lucide-react'
import clsx from 'clsx'
import DropZone from '../components/upload/DropZone.jsx'
import FileList from '../components/upload/FileList.jsx'
import AIInsightCard from '../components/upload/AIInsightCard.jsx'
import StageProgress from '../components/common/StageProgress.jsx'
import ConfirmExtraction from '../components/preview/ConfirmExtraction.jsx'
import StylePanel, { DEFAULT_STYLE } from '../components/customize/StylePanel.jsx'
import OutputTypeSelector from '../components/customize/OutputTypeSelector.jsx'
import Button from '../components/common/Button.jsx'
import { useUpload } from '../hooks/useUpload.js'
import { useJobStatus } from '../hooks/useJobStatus.js'
import { useExport } from '../hooks/useExport.js'
import { getJob } from '../api/client.js'
import { durations, easings, useReducedMotion } from '../lib/motion.js'
import toast from 'react-hot-toast'

const STEPS = [
  { n: 1, label: 'Select Files' },
  { n: 2, label: 'Processing' },
  { n: 3, label: 'AI Insight' },
  { n: 4, label: 'Review' },
  { n: 5, label: 'Export' },
]

function StepIndicator({ current }) {
  const reduced = useReducedMotion()
  return (
    <div className="flex items-center gap-0">
      {STEPS.map((step, idx) => {
        const isDone = step.n < current
        const isActive = step.n === current
        return (
          <div key={step.n} className="flex items-center">
            <div className="flex flex-col items-center">
              <div
                className={clsx(
                  'flex h-8 w-8 items-center justify-center rounded-full text-caption font-bold transition-colors duration-base ease-standard',
                  isDone && 'bg-primary text-canvas',
                  isActive && 'bg-surface text-secondary ring-2 ring-secondary',
                  !isDone && !isActive && 'bg-line text-muted',
                )}
              >
                {isDone ? <Check size={14} /> : step.n}
              </div>
              <span
                className={clsx(
                  'text-caps mt-1.5 text-caption whitespace-nowrap',
                  isActive ? 'font-semibold text-ink' : 'text-muted',
                )}
              >
                {step.label}
              </span>
            </div>
            {idx < STEPS.length - 1 && (
              <div className="relative mb-5 h-0.5 w-6 sm:w-10 lg:w-16 overflow-hidden rounded-full bg-line">
                <motion.div
                  className="absolute inset-y-0 left-0 bg-primary"
                  initial={false}
                  animate={{ width: isDone ? '100%' : '0%' }}
                  transition={{ duration: reduced ? 0 : durations.slow, ease: easings.standard }}
                />
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

export default function Upload() {
  useEffect(() => {
    document.title = 'Upload | ExamRoll'
  }, [])

  const [step, setStep] = useState(1)
  const [files, setFiles] = useState([])
  const [jobId, setJobId] = useState(null)
  const [style, setStyle] = useState(DEFAULT_STYLE)
  const [outputType, setOutputType] = useState('subject_wise')
  const [filename, setFilename] = useState('Subject-wise-Roll-Number-List')

  const { upload, uploading, progress: uploadProgress } = useUpload()
  const { stages, stageError, status: wsStatus } = useJobStatus(step === 2 ? jobId : null)
  const { triggerExport, exporting, exportError } = useExport()
  const navigate = useNavigate()
  const [visuallyDone, setVisuallyDone] = useState(false)

  useEffect(() => {
    setVisuallyDone(false)
  }, [jobId])

  // Fetch job detail when WS reports completed
  const { data: jobDetail } = useQuery({
    queryKey: ['job', jobId],
    queryFn: async () => {
      const res = await getJob(jobId)
      return res.data
    },
    enabled: !!jobId && wsStatus === 'completed',
    staleTime: Infinity,
  })

  // Advance to step 3 once the job is done AND the stage checklist has
  // visibly finished settling (StageProgress's onComplete) — not the instant
  // the backend reports completion, so the user actually sees the last step.
  useEffect(() => {
    if (wsStatus === 'completed' && jobDetail && visuallyDone && step === 2) {
      setStep(3)
    }
  }, [wsStatus, jobDetail, visuallyDone, step])

  // Append newly dropped/picked files; never replace the queue, never add the
  // same filename twice. Dedupe + toast happen OUTSIDE the state updater —
  // updaters must stay side-effect free (StrictMode double-invokes them).
  const handleAddFiles = (incoming) => {
    const existing = new Set(files.map((f) => f.name))
    const fresh = []
    for (const f of incoming) {
      if (existing.has(f.name)) {
        toast(`"${f.name}" is already in the list`, { icon: 'ℹ️' })
      } else {
        existing.add(f.name)
        fresh.push(f)
      }
    }
    if (fresh.length > 0) setFiles((prev) => [...prev, ...fresh])
  }

  const handleRemoveFile = (name) =>
    setFiles((prev) => prev.filter((f) => f.name !== name))

  const handleUpload = async () => {
    if (files.length === 0) return
    try {
      const resp = await upload(files)
      setJobId(resp.job_id)
      setStep(2)
    } catch (_) {
      // error shown by hook
    }
  }

  const handleExport = () => {
    if (!jobId) return
    triggerExport(jobId, style, filename)
  }

  const insight = jobDetail?.extracted_data
    ? {
        document_type: jobDetail.extracted_data.document_type,
        course: jobDetail.extracted_data.course,
        semester: jobDetail.extracted_data.semester,
        exam_name: jobDetail.extracted_data.exam_name,
        total_students: jobDetail.extracted_data.total_students,
        subjects_detected: jobDetail.extracted_data.subjects ?? [],
        confidence: jobDetail.extracted_data.ai_confidence,
        notes: jobDetail.extracted_data.ai_notes,
        suggested_outputs: ['Subject-wise Roll Number List'],
        file_count: jobDetail.file_count ?? 1,
        source_files: jobDetail.source_files ?? [],
        warnings: jobDetail.warnings ?? [],
      }
    : null

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      {/* Header */}
      <div>
        <h1 className="font-display text-h1 font-medium text-ink">Upload Attestation Sheet</h1>
        <p className="mt-1 text-small text-muted">AI-powered roll number extraction and Excel generation</p>
      </div>

      {/* Step indicator */}
      <div className="-mx-1 overflow-x-auto px-1 py-1">
        <StepIndicator current={step} />
      </div>

      {/* Step 1: Select files (one or many — dropping again appends) */}
      {step === 1 && (
        <div className="space-y-4">
          <DropZone onFiles={handleAddFiles} compact={files.length > 0} />
          <FileList
            files={files}
            onAddFiles={handleAddFiles}
            onRemove={handleRemoveFile}
            onClearAll={() => setFiles([])}
            onUpload={handleUpload}
            uploading={uploading}
            uploadProgress={uploadProgress}
          />
        </div>
      )}

      {/* Step 2: Processing */}
      {step === 2 && (
        <div className="rounded-2xl border border-line bg-surface p-8 shadow-warm space-y-5">
          <div className="text-center space-y-1">
            <h3 className="font-display text-h3 font-medium text-ink">Processing your document…</h3>
            <p className="text-small text-muted">Each step below reflects real work happening on your file.</p>
          </div>
          <StageProgress
            stages={stages}
            stageError={stageError}
            onComplete={() => setVisuallyDone(true)}
            onRetry={() => { setStep(1); setFiles([]); setJobId(null) }}
          />
        </div>
      )}

      {/* Step 3: AI Insight */}
      {step === 3 && insight && (
        <AIInsightCard
          insight={insight}
          onProceed={() => setStep(4)}
          onEdit={() => {}}
        />
      )}

      {/* Step 4: Review + Confirm */}
      {step === 4 && jobDetail?.extracted_data && (
        <ConfirmExtraction
          extractedData={jobDetail.extracted_data}
          fileCount={jobDetail.file_count ?? 1}
          onCustomize={() => setStep(5)}
          onReupload={() => { setStep(1); setFiles([]); setJobId(null) }}
        />
      )}

      {/* Step 5: Style + Export */}
      {step === 5 && (
        <div className="space-y-5">
          <OutputTypeSelector value={outputType} onChange={setOutputType} />
          <StylePanel style={style} onChange={setStyle} />

          <div className="rounded-2xl border border-line bg-surface p-5 shadow-warm space-y-4">
            <h3 className="text-small font-semibold text-ink">Output Filename</h3>
            <input
              type="text"
              value={filename}
              onChange={(e) => setFilename(e.target.value.replace(/[^a-zA-Z0-9_\- ]/g, ''))}
              placeholder="Subject-wise-Roll-Number-List"
              className="w-full rounded-xl border border-line px-3 py-2 text-small text-ink focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
            />
            <p className="text-caption text-muted">The file will be saved as <code className="font-medium text-ink">{filename || 'output'}.xlsx</code></p>
          </div>

          {exportError && (
            <div className="rounded-xl border border-error/25 bg-error/5 p-4 text-small text-error flex items-center justify-between gap-3">
              <span>{exportError}</span>
              <Button variant="danger" size="sm" onClick={handleExport} loading={exporting}>
                Retry
              </Button>
            </div>
          )}

          <div className="flex gap-3">
            <Button
              variant="primary"
              size="lg"
              className="flex-1"
              onClick={handleExport}
              loading={exporting}
            >
              Download Excel
            </Button>
            <Button
              variant="ghost"
              size="lg"
              onClick={() => navigate(`/jobs/${jobId}`)}
            >
              View Job
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
