import { useEffect, useState, useRef, useCallback } from 'react'
import { createWebSocket, getJob } from '../api/client.js'

const MAX_RETRIES = 3
const FINAL_STAGE_ID = 'saving'
const POLL_INTERVAL_MS = 3000

export function useJobStatus(jobId) {
  const [status, setStatus] = useState(null)
  const [progress, setProgress] = useState(0)
  const [message, setMessage] = useState('')
  const [stages, setStages] = useState([])
  const [stageError, setStageError] = useState(null)
  const [aiInsight, setAiInsight] = useState(null)
  const wsRef = useRef(null)
  const retriesRef = useRef(0)
  const doneRef = useRef(false)
  // The pending setTimeout id from a scheduled reconnect — without storing
  // this, a component unmount or a jobId change couldn't cancel it, so a
  // stale reconnect could fire later and open a WebSocket for the WRONG job
  // (P1-22, cross-job contamination — reproduced: doneRef is a single ref
  // shared across renders, so a new effect run for a new jobId resets it to
  // false before the old timer fires, and the old timer's closure still
  // holds the old jobId).
  const reconnectTimerRef = useRef(null)
  // Fallback poller once WS retries are exhausted (P1-21) — plain
  // GET /jobs/{id} every POLL_INTERVAL_MS until a terminal status.
  const pollTimerRef = useRef(null)

  const clearReconnectTimer = () => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current)
      reconnectTimerRef.current = null
    }
  }

  const clearPoller = () => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current)
      pollTimerRef.current = null
    }
  }

  const startPolling = useCallback((id) => {
    if (pollTimerRef.current || doneRef.current) return
    const tick = async () => {
      try {
        const res = await getJob(id)
        const job = res.data
        if (job.status !== undefined) setStatus(job.status)
        if (job.progress !== undefined) setProgress(job.progress)
        if (job.status === 'completed' || job.status === 'failed') {
          doneRef.current = true
          clearPoller()
        }
      } catch (_) {
        // A transient network error shouldn't stop polling — the next tick
        // tries again. If the job/session is genuinely gone the UI's own
        // 401 handling (client.js) or a subsequent getJob 404 elsewhere
        // covers that.
      }
    }
    tick()
    pollTimerRef.current = setInterval(tick, POLL_INTERVAL_MS)
  }, [])

  const connect = useCallback(() => {
    if (!jobId || doneRef.current) return

    const ws = createWebSocket(jobId)
    wsRef.current = ws

    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)

        // Granular stage event: {type:'stage', stage_id, label, status, detail, count, percent, warning?}
        if (data.type === 'stage') {
          setStages((prev) => {
            const idx = prev.findIndex((s) => s.stage_id === data.stage_id)
            if (idx === -1) return [...prev, data]
            const next = [...prev]
            next[idx] = data
            return next
          })
          if (typeof data.percent === 'number') setProgress(data.percent)
          setMessage(data.detail ? `${data.label} — ${data.detail}` : data.label)
          setStatus('processing')
          if (data.stage_id === FINAL_STAGE_ID && data.status === 'complete') {
            setStatus('completed')
            doneRef.current = true
            clearPoller()
            ws.close()
          }
          return
        }

        // Stage-level failure: {type:'error', stage_id, message}
        if (data.type === 'error') {
          setStageError({ stageId: data.stage_id, message: data.message })
          setStatus('failed')
          setMessage(data.message)
          doneRef.current = true
          clearPoller()
          ws.close()
          return
        }

        // Legacy/plain snapshot payload (e.g. connect-time job state)
        if (data.status !== undefined) setStatus(data.status)
        if (data.progress !== undefined) setProgress(data.progress)
        if (data.message) setMessage(data.message)
        if (data.ai_insight) setAiInsight(data.ai_insight)
        if (data.status === 'completed' || data.status === 'failed') {
          doneRef.current = true
          clearPoller()
          ws.close()
        }
      } catch (_) {}
    }

    ws.onclose = () => {
      if (doneRef.current) return
      if (retriesRef.current < MAX_RETRIES) {
        retriesRef.current += 1
        reconnectTimerRef.current = setTimeout(() => {
          reconnectTimerRef.current = null
          connect()
        }, 1500 * retriesRef.current)
      } else {
        // Live updates are gone for this job; keep the UI moving via polling
        // instead of leaving it stuck on whatever the last WS message said.
        startPolling(jobId)
      }
    }

    ws.onerror = () => {
      setStatus('error')
    }
  }, [jobId, startPolling])

  useEffect(() => {
    if (!jobId) return
    doneRef.current = false
    retriesRef.current = 0
    setStages([])
    setStageError(null)
    connect()
    return () => {
      doneRef.current = true
      clearReconnectTimer()
      clearPoller()
      wsRef.current?.close()
    }
  }, [jobId, connect])

  return { progress, message, status, stages, stageError, aiInsight }
}
