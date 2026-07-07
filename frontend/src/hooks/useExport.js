import { useState, useCallback } from 'react'
import { exportExcel } from '../api/client.js'
import toast from 'react-hot-toast'

export function useExport() {
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState(null)

  const triggerExport = useCallback(async (jobId, styleConfig, filename) => {
    setExporting(true)
    setExportError(null)
    try {
      await exportExcel(jobId, styleConfig, filename)
      toast.success('Download started')
    } catch (err) {
      const msg = err.message || 'Export failed'
      setExportError(msg)
      toast.error(msg)
    } finally {
      setExporting(false)
    }
  }, [])

  return { triggerExport, exporting, exportError, clearExportError: () => setExportError(null) }
}
