import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'react-hot-toast'
import { JobProvider } from './context/JobContext.jsx'
import PageWrapper from './components/layout/PageWrapper.jsx'
import Dashboard from './pages/Dashboard.jsx'
import Upload from './pages/Upload.jsx'
import JobDetail from './pages/JobDetail.jsx'
import History from './pages/History.jsx'
import NotFound from './pages/NotFound.jsx'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 30_000 },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
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
          <Routes>
            <Route element={<PageWrapper />}>
              <Route path="/" element={<Dashboard />} />
              <Route path="/upload" element={<Upload />} />
              <Route path="/jobs/:jobId" element={<JobDetail />} />
              <Route path="/history" element={<History />} />
              <Route path="*" element={<NotFound />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </JobProvider>
    </QueryClientProvider>
  )
}
