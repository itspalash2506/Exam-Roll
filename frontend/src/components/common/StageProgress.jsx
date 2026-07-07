import { useCallback, useEffect, useRef, useState } from 'react'
import { Check, Loader2, Circle, AlertTriangle, X } from 'lucide-react'
import clsx from 'clsx'

// Mirrors backend STAGE_IDS/STAGE_LABELS in processor.py — used only to seed
// the initial pending checklist. Every row's real status/detail/count still
// comes exclusively from stage events the backend actually sent.
const STAGE_DEFS = [
  { id: 'validating', label: 'Validating files' },
  { id: 'reading_document', label: 'Reading documents' },
  { id: 'extracting_rolls', label: 'Extracting roll numbers' },
  { id: 'detecting_subjects', label: 'Detecting subjects' },
  { id: 'deduplicating', label: 'Merging duplicates' },
  { id: 'ai_analysis', label: 'AI identifying document type' },
  { id: 'matching', label: 'Matching AI labels to codes' },
  { id: 'validating_data', label: 'Validating records' },
  { id: 'saving', label: 'Saving results' },
]

const STAGGER_MS = 180
const FINAL_STAGE_ID = STAGE_DEFS[STAGE_DEFS.length - 1].id

export default function StageProgress({ stages, stageError, onComplete, onRetry }) {
  const [revealed, setRevealed] = useState({})
  const [percent, setPercent] = useState(0)
  const [settled, setSettled] = useState(false)

  const queueRef = useRef([])
  const queuedRef = useRef({}) // stage_id -> last event object already queued/revealed
  const revealingRef = useRef(false)
  const timerRef = useRef(null)
  const onCompleteRef = useRef(onComplete)
  onCompleteRef.current = onComplete

  // ── STAGGER LOGIC (cosmetic only — no progress is fabricated here) ────────
  // Every item that reaches this queue is a stage event the backend already
  // sent over the WebSocket, carrying a real detail/count it computed from
  // the actual document. The rule-based extractor often finishes reading,
  // roll-extraction, and subject-detection within the same pass, so several
  // "complete" events can land in the same network tick — rendering them all
  // instantly would flash past too fast to read. This queue reveals at most
  // one already-real event every ~180ms. It never adds a stage, changes a
  // status, or invents a number; it only paces *when* a true result appears
  // on screen.
  const processQueue = useCallback(() => {
    if (revealingRef.current) return
    const step = () => {
      const next = queueRef.current.shift()
      if (!next) {
        revealingRef.current = false
        return
      }
      revealingRef.current = true
      setRevealed((prev) => ({ ...prev, [next.stage_id]: next }))
      setPercent((p) => Math.max(p, next.percent ?? p))
      timerRef.current = setTimeout(step, STAGGER_MS)
    }
    step()
  }, [])

  useEffect(() => {
    // `stages` holds one entry per stage_id, updated in place (active → complete
    // replaces the same array slot with a new object, not a new array entry) —
    // so diff by object identity per stage_id, not by array length, or in-place
    // transitions get silently dropped.
    const fresh = stages.filter((s) => queuedRef.current[s.stage_id] !== s)
    if (fresh.length === 0) return
    fresh.forEach((s) => { queuedRef.current[s.stage_id] = s })
    queueRef.current.push(...fresh)
    processQueue()
  }, [stages, processQueue])

  useEffect(() => () => clearTimeout(timerRef.current), [])

  // Success flourish: only once every real event has both arrived and been
  // visibly revealed (queue drained) do we settle and auto-advance.
  useEffect(() => {
    if (settled) return
    if (revealed[FINAL_STAGE_ID]?.status === 'complete' && queueRef.current.length === 0) {
      setSettled(true)
    }
  }, [revealed, settled])

  // Deliberately separate from the effect above: setSettled(true) there
  // triggers a re-render that re-runs any effect depending on `settled`, and
  // React fires the *previous* invocation's cleanup first — so a timer
  // started in that same effect gets cancelled by its own dependency change
  // before it can fire. Scheduling it here, in an effect that only depends
  // on `settled`, means it schedules once when settled flips true and is
  // never torn down by itself.
  useEffect(() => {
    if (!settled) return
    const t = setTimeout(() => onCompleteRef.current?.(), 600)
    return () => clearTimeout(t)
  }, [settled])

  return (
    <div className="space-y-4">
      <div className="h-1 w-full overflow-hidden rounded-full bg-line">
        <div
          className={clsx(
            'h-full rounded-full transition-[width] duration-slow ease-standard',
            settled ? 'bg-success' : 'bg-primary',
          )}
          style={{ width: `${percent}%` }}
        />
      </div>

      <ul className="space-y-3">
        {STAGE_DEFS.map((def) => {
          const event = revealed[def.id]
          const isErrored = stageError?.stageId === def.id
          const status = isErrored ? 'error' : event?.status ?? 'pending'
          return (
            <StageRow
              key={def.id}
              def={def}
              event={event}
              status={status}
              errorMessage={isErrored ? stageError.message : null}
              onRetry={onRetry}
            />
          )
        })}
      </ul>

      {settled && (
        <p className="flex items-center gap-1.5 text-caption font-medium text-success animate-stage-reveal">
          <Check size={13} strokeWidth={3} /> All steps complete
        </p>
      )}
    </div>
  )
}

function StageRow({ def, event, status, errorMessage, onRetry }) {
  const hasWarning = Boolean(event?.warning) && status !== 'error'

  return (
    <li
      aria-live="polite"
      className={clsx(
        'flex items-start gap-3 transition-opacity duration-base ease-standard',
        status === 'pending' ? 'opacity-50' : 'opacity-100',
      )}
    >
      <div className="mt-0.5 flex h-5 w-5 flex-shrink-0 items-center justify-center">
        {status === 'pending' && <Circle size={16} className="text-muted/40" />}
        {status === 'active' && <Loader2 size={16} className="animate-spin text-secondary" />}
        {status === 'complete' && !hasWarning && (
          <span className="flex h-4 w-4 items-center justify-center rounded-full bg-success text-canvas animate-stage-pop">
            <Check size={11} strokeWidth={3} />
          </span>
        )}
        {status === 'complete' && hasWarning && (
          <span className="flex h-4 w-4 items-center justify-center rounded-full bg-warning text-canvas animate-stage-pop">
            <AlertTriangle size={10} strokeWidth={3} />
          </span>
        )}
        {status === 'error' && (
          <span className="flex h-4 w-4 items-center justify-center rounded-full bg-error text-canvas animate-stage-pop">
            <X size={11} strokeWidth={3} />
          </span>
        )}
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
          <span
            className={clsx(
              'text-small',
              status === 'pending' && 'text-muted',
              status === 'active' && 'font-medium text-ink',
              status === 'complete' && 'text-ink',
              status === 'error' && 'font-medium text-error',
            )}
          >
            {def.label}
          </span>
          {/* Active rows show live per-file detail ("File 2 of 3 · 158 pages")
              — real backend-computed text, updated in place as files finish. */}
          {event?.detail && status === 'active' && (
            <span className="text-caption text-muted">{event.detail}</span>
          )}
          {event?.detail && status === 'complete' && !hasWarning && (
            <span className="text-caption text-muted animate-stage-reveal">{event.detail}</span>
          )}
        </div>

        {hasWarning && (
          <p className="mt-0.5 text-caption text-warning animate-stage-reveal">{event.warning}</p>
        )}

        {status === 'error' && (
          <div className="mt-1.5 flex flex-wrap items-center gap-2 animate-stage-reveal">
            <p className="text-caption text-error">{errorMessage}</p>
            <button
              onClick={onRetry}
              className="rounded-lg border border-error/30 bg-surface px-2.5 py-1 text-caption font-medium text-error transition-colors duration-fast hover:bg-error/10"
            >
              Try again
            </button>
          </div>
        )}
      </div>
    </li>
  )
}
