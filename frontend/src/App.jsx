import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'react-hot-toast'
import { AuthProvider } from './context/AuthContext.jsx'
import { JobProvider } from './context/JobContext.jsx'
import ErrorBoundary from './components/common/ErrorBoundary.jsx'
import PageWrapper from './components/layout/PageWrapper.jsx'
import RequireAuth from './components/layout/RequireAuth.jsx'
import Dashboard from './pages/Dashboard.jsx'
import Login from './pages/Login.jsx'
import Upload from './pages/Upload.jsx'
import JobDetail from './pages/JobDetail.jsx'
import History from './pages/History.jsx'
import Settings from './pages/Settings.jsx'
import Rooms from './pages/Rooms.jsx'
import Sessions from './pages/Sessions.jsx'
import NotFound from './pages/NotFound.jsx'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 30_000 },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <JobProvider>
          <BrowserRouter>
            <Toaster
              position="top-right"
              toastOptions={{
                duration: 4000,
                style: {
                  fontFamily: "'Bricolage Grotesque Variable', sans-serif",
                  fontSize: '14px',
                  borderRadius: '12px',
                  background: '#FFFFFF',
                  color: '#1F1B16',
                  border: '1px solid #EDE8E0',
                  boxShadow: '0 1px 2px rgba(31,27,22,.04), 0 8px 24px rgba(31,27,22,.05)',
                },
                success: { iconTheme: { primary: '#2E8168', secondary: '#fff' } },
                error: { iconTheme: { primary: '#B4442E', secondary: '#fff' } },
              }}
            />
            <ErrorBoundary>
              <Routes>
                <Route path="/login" element={<Login />} />
                <Route element={<RequireAuth />}>
                  <Route element={<PageWrapper />}>
                    <Route path="/" element={<Dashboard />} />
                    <Route path="/upload" element={<Upload />} />
                    <Route path="/jobs/:jobId" element={<JobDetail />} />
                    <Route path="/history" element={<History />} />
                    <Route path="/settings" element={<Settings />} />
                    <Route path="/rooms" element={<Rooms />} />
                    <Route path="/sessions" element={<Sessions />} />
                    <Route path="*" element={<NotFound />} />
                  </Route>
                </Route>
              </Routes>
            </ErrorBoundary>
          </BrowserRouter>
        </JobProvider>
      </AuthProvider>
    </QueryClientProvider>
  )
}
