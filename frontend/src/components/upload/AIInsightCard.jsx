import { useState } from 'react'
import { motion } from 'framer-motion'
import {
  Sparkles, BookOpen, GraduationCap, CheckCircle, ChevronDown, ChevronUp, Edit3,
  Files, AlertTriangle
} from 'lucide-react'
import Button from '../common/Button.jsx'
import Modal from '../common/Modal.jsx'
import { formatDocType } from '../../utils/formatters.js'
import { durations, easings, useReducedMotion } from '../../lib/motion.js'

function ConfidenceMeter({ value }) {
  const pct = Math.round((value ?? 0) * 100)
  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-caption text-muted">
        <span>AI Confidence</span>
        <span className="font-semibold text-ink">{pct}%</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-line">
        <motion.div
          className="h-full rounded-full bg-primary"
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: durations.slow, ease: easings.standard }}
        />
      </div>
    </div>
  )
}

export default function AIInsightCard({ insight, onProceed, onEdit }) {
  const [showAll, setShowAll] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const reduced = useReducedMotion()

  if (!insight) return null

  const subjects = insight.subjects_detected ?? []
  const visibleSubjects = showAll ? subjects : subjects.slice(0, 6)
  const suggestedOutputs = insight.suggested_outputs ?? ['Subject-wise Roll Number List']
  const fileCount = insight.file_count ?? 1
  const warnings = insight.warnings ?? []

  return (
    <>
      <motion.div
        initial={{ opacity: 0, y: reduced ? 0 : 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: durations.base, ease: easings.entrance }}
        className="rounded-2xl border border-line bg-highlight/30 p-6 space-y-5"
      >
        <div className="flex items-start gap-3">
          <span className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full bg-primary text-canvas">
            <Sparkles size={17} />
          </span>
          <div className="flex-1">
            <p className="text-caption font-medium uppercase tracking-wide text-muted">AI Analysis Complete</p>
            <div className="mt-0.5 flex flex-wrap items-center gap-2.5">
              <h3 className="font-display text-h2 font-medium text-ink">
                {formatDocType(insight.document_type)}
              </h3>
              {fileCount > 1 && (
                <span
                  className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface px-2.5 py-1 text-caption font-medium text-muted"
                  title={(insight.source_files ?? []).join(', ')}
                >
                  <Files size={12} />
                  Aggregated from {fileCount} files
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Per-file processing warnings — shown honestly, never hidden */}
        {warnings.length > 0 && (
          <div className="rounded-xl border border-warning/30 bg-highlight/40 px-4 py-3">
            <p className="mb-1.5 flex items-center gap-1.5 text-caption font-medium text-warning">
              <AlertTriangle size={13} />
              {warnings.length === 1 ? 'One thing to know' : `${warnings.length} things to know`}
            </p>
            <ul className="space-y-1">
              {warnings.map((w) => (
                <li key={w} className="text-caption leading-snug text-ink">
                  {w}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Metadata row */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            { icon: GraduationCap, label: 'Course', value: insight.course || '—' },
            { icon: BookOpen, label: 'Semester', value: insight.semester || '—' },
            { icon: BookOpen, label: 'Exam', value: insight.exam_name || '—' },
            { icon: CheckCircle, label: 'Students', value: insight.total_students ?? '—' },
          ].map(({ icon: Icon, label, value }) => (
            <div key={label} className="rounded-xl bg-surface/80 px-3 py-2.5 border border-line">
              <div className="flex items-center gap-1.5 text-caption text-muted mb-1">
                <Icon size={12} />
                {label}
              </div>
              <p className="text-small font-semibold text-ink truncate">{value}</p>
            </div>
          ))}
        </div>

        <ConfidenceMeter value={insight.confidence} />

        {/* Detected subjects */}
        {subjects.length > 0 && (
          <div>
            <p className="mb-2 text-caption font-medium text-muted uppercase tracking-wide">
              Detected Subjects ({subjects.length})
            </p>
            <div className="max-h-40 overflow-y-auto">
              <div className="flex flex-wrap gap-2">
                {visibleSubjects.map((s) => (
                  <span
                    key={s.code}
                    className="inline-flex items-center gap-1 rounded-full bg-surface border border-line px-2.5 py-1 text-caption font-medium text-ink"
                  >
                    <span className="font-semibold text-primary">{s.code}</span>
                    {s.name && <span className="text-muted">· {s.name}</span>}
                  </span>
                ))}
              </div>
            </div>
            {subjects.length > 6 && (
              <button
                onClick={() => setShowAll((v) => !v)}
                className="mt-2 flex items-center gap-1 text-caption font-medium text-primary hover:text-primary-hover"
              >
                {showAll ? <><ChevronUp size={12} /> Show less</> : <><ChevronDown size={12} /> Show all {subjects.length}</>}
              </button>
            )}
          </div>
        )}

        {/* AI notes — italic Fraunces pull-quote */}
        {insight.notes && (
          <div className="rounded-xl border border-line bg-surface/70 px-4 py-3">
            <p className="text-caption font-medium text-muted mb-1">AI Notes</p>
            <p className="font-display italic text-body text-ink leading-snug">&ldquo;{insight.notes}&rdquo;</p>
          </div>
        )}

        {/* Suggested outputs */}
        {suggestedOutputs.length > 0 && (
          <div>
            <p className="mb-2 text-caption font-medium text-muted uppercase tracking-wide">Suggested Outputs</p>
            <div className="flex flex-wrap gap-2">
              {suggestedOutputs.map((o) => (
                <span
                  key={o}
                  className="cursor-pointer rounded-full bg-primary px-3 py-1 text-caption font-medium text-canvas transition-colors duration-fast hover:bg-primary-hover"
                >
                  {o}
                </span>
              ))}
            </div>
          </div>
        )}

        <div className="flex gap-3 pt-1">
          <Button variant="emphasis" size="md" onClick={onProceed} className="flex-1">
            <CheckCircle size={15} />
            Looks correct, proceed
          </Button>
          <Button
            variant="secondary"
            size="md"
            onClick={() => { setEditOpen(true); onEdit?.() }}
          >
            <Edit3 size={15} />
            Edit manually
          </Button>
        </div>
      </motion.div>

      <Modal open={editOpen} onClose={() => setEditOpen(false)} title="Edit AI Findings">
        <p className="text-small text-muted mb-4">
          Manual editing of AI findings will be available in a future update. For now, you can proceed and
          adjust the export output using the Style Panel.
        </p>
        <Button variant="primary" size="md" onClick={() => { setEditOpen(false); onProceed?.() }} className="w-full">
          Proceed anyway
        </Button>
      </Modal>
    </>
  )
}
