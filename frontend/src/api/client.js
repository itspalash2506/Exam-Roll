import axios from 'axios'

// Single source of truth for where the backend lives.
// - Deployed (Cloudflare Pages / Vercel): set VITE_API_BASE_URL to the backend
//   origin, e.g. https://examroll-api.onrender.com (no trailing slash needed).
// - Local dev: leave it unset — paths stay relative ('/api/v1', '/ws/...') and
//   the Vite dev proxy forwards them to http://localhost:8000 (vite.config.js),
//   so the local workflow is unchanged.
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '')

const api = axios.create({
  baseURL: `${API_BASE_URL}/api/v1`,
  // Free-tier hosts (Render) sleep on idle and can take ~a minute to cold-start;
  // a 60s timeout made the very first request after a sleep fail spuriously.
  timeout: 120_000,
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    const message =
      err.response?.data?.detail ||
      err.response?.data?.error ||
      err.message ||
      'Request failed'
    return Promise.reject(new Error(message))
  },
)

// Multi-file upload: repeated "files" fields, one Job for the whole batch.
export const uploadFiles = (files, onProgress) => {
  const form = new FormData()
  files.forEach((file) => form.append('files', file))
  return api.post('/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (e) =>
      onProgress?.(Math.round((e.loaded * 100) / (e.total || 1))),
  })
}

// Back-compat single-file wrapper — just the n=1 case of uploadFiles.
export const uploadFile = (file, onProgress) => uploadFiles([file], onProgress)

export const getJobs = (skip = 0, limit = 50) =>
  api.get('/jobs', { params: { skip, limit } })

export const fetchJobs = getJobs

export const getJob = (jobId) => api.get(`/jobs/${jobId}`)

export const fetchJob = getJob

export const deleteJob = (jobId) => api.delete(`/jobs/${jobId}`)

export const exportExcel = async (
  jobId,
  styleConfig,
  filename = 'Subject-wise-Roll-Number-List',
) => {
  const res = await api.post(
    '/export',
    { job_id: jobId, style_config: styleConfig, filename },
    { responseType: 'blob' },
  )
  const url = URL.createObjectURL(res.data)
  const a = document.createElement('a')
  a.href = url
  a.download = `${filename}.xlsx`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
  return res.data
}

export const exportJob = (payload) =>
  api.post('/export', payload, { responseType: 'blob' })

// WebSocket URL is derived from the same API base (http→ws, https→wss) so there
// is exactly one env var to configure per deployment.
export const createWebSocket = (jobId) => {
  if (API_BASE_URL) {
    const wsBase = API_BASE_URL.replace(/^http/, 'ws')
    return new WebSocket(`${wsBase}/ws/jobs/${jobId}`)
  }
  // Dev fallback: same-origin, routed to the backend by the Vite '/ws' proxy.
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return new WebSocket(`${scheme}://${window.location.host}/ws/jobs/${jobId}`)
}

export default api
