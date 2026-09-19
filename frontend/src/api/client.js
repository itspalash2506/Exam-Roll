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
  // Required for the httpOnly session cookie to actually be sent (DECISIONS.md,
  // 2026-09-19) — without this, axios never attaches examroll_session even
  // though the browser has it, and every authenticated call 401s.
  withCredentials: true,
})

// A 401 means the session is missing/expired/revoked — send the user to
// /login rather than surfacing it as a generic error toast. Skips the
// login/me endpoints themselves so a wrong-password attempt or the initial
// "am I logged in?" check on app load can still handle their own 401
// without an unwanted redirect loop.
const AUTH_ENDPOINTS = ['/auth/login', '/auth/me']

// No ExamRoll API response is ever HTML — every real endpoint returns JSON
// or an xlsx blob. An HTML body with a 2xx status means the request never
// actually reached the backend (a misconfigured VITE_API_BASE_URL landing on
// a static host's own page, a same-origin SPA catch-all swallowing a typo'd
// path, ...) — axios otherwise treats that as a "successful" response, and
// calling code then fails confusingly trying to read JSON fields off an
// HTML string (P1-24).
api.interceptors.response.use(
  (res) => {
    const contentType = res.headers?.['content-type'] || ''
    if (contentType.includes('text/html')) {
      return Promise.reject(
        new Error(
          `Expected a response from the API but got an HTML page instead (${res.config?.url}). ` +
          'This usually means the app is misconfigured to talk to the wrong server.',
        ),
      )
    }
    return res
  },
  (err) => {
    const path = err.config?.url || ''
    const isAuthEndpoint = AUTH_ENDPOINTS.some((p) => path.includes(p))
    if (err.response?.status === 401 && !isAuthEndpoint && window.location.pathname !== '/login') {
      window.location.assign('/login')
      return Promise.reject(new Error('Not authenticated'))
    }
    const message =
      err.response?.data?.detail ||
      err.response?.data?.error ||
      err.message ||
      'Request failed'
    return Promise.reject(new Error(message))
  },
)

// ── Auth ──────────────────────────────────────────────────────────────────

export const login = (email, password) =>
  api.post('/auth/login', { email, password })

export const logout = () => api.post('/auth/logout')

export const me = () => api.get('/auth/me')

// ── Exams / Colleges (§14.3 upload picker) ──────────────────────────────────

export const getExams = () => api.get('/exams')
export const createExam = (payload) => api.post('/exams', payload)
export const getColleges = () => api.get('/colleges')
export const createCollege = (payload) => api.post('/colleges', payload)

// ── Org settings (P10, FUTURE_UNIFIED.md §8.4 item 2 — AI opt-out) ─────────

export const getOrgSettings = () => api.get('/settings')
export const updateOrgSettings = (payload) => api.patch('/settings', payload)

// Multi-file upload: repeated "files" fields, one Job for the whole batch.
// examId/collegeId are optional (an upload predating the picker is still
// valid — see upload.py) but, when the caller has them, are attached so
// the pipeline's persisting_rows stage has something to write real
// Student/SubjectOffering/Enrollment rows against.
export const uploadFiles = (files, onProgress, { examId, collegeId } = {}) => {
  const form = new FormData()
  files.forEach((file) => form.append('files', file))
  if (examId) form.append('exam_id', examId)
  if (collegeId) form.append('college_id', collegeId)
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
