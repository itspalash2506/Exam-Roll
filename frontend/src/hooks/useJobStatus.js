import { useEffect, useState, useRef, useCallback } from 'react'
import { createWebSocket } from '../api/client.js'

const MAX_RETRIES = 3
const FINAL_STAGE_ID = 'saving'

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
          ws.close()
        }
      } catch (_) {}
    }

    ws.onclose = () => {
      if (!doneRef.current && retriesRef.current < MAX_RETRIES) {
        retriesRef.current += 1
        setTimeout(connect, 1500 * retriesRef.current)
      }
    }

    ws.onerror = () => {
      setStatus('error')
    }
  }, [jobId])

  useEffect(() => {
    if (!jobId) return
    doneRef.current = false
    retriesRef.current = 0
    setStages([])
    setStageError(null)
    connect()
    return () => {
      doneRef.current = true
      wsRef.current?.close()
    }
  }, [jobId, connect])

  return { progress, message, status, stages, stageError, aiInsight }
}
