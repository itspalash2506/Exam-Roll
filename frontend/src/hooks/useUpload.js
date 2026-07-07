import { useState, useCallback } from 'react'
import { uploadFiles } from '../api/client.js'
import { useJobContext } from '../context/JobContext.jsx'
import toast from 'react-hot-toast'

export function useUpload() {
  const [progress, setProgress] = useState(0)
  const [uploading, setUploading] = useState(false)
  const { setCurrentJob, refreshJobs } = useJobContext()

  const upload = useCallback(
    async (fileOrFiles) => {
      const files = Array.isArray(fileOrFiles) ? fileOrFiles : [fileOrFiles]
      setUploading(true)
      setProgress(0)
      try {
        const res = await uploadFiles(files, setProgress)
        const uploadResp = res.data // { job_id, message, ai_insight }
        const label = files.length === 1 ? files[0].name : `${files.length} files`
        setCurrentJob({ id: uploadResp.job_id, filename: label, status: 'queued' })
        refreshJobs()
        toast.success('Upload started — processing in background')
        return uploadResp
      } catch (err) {
        toast.error(err.message)
        throw err
      } finally {
        setUploading(false)
      }
    },
    [setCurrentJob, refreshJobs],
  )

  return { upload, uploading, progress }
}
