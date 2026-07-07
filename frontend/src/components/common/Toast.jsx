import { Toaster } from 'react-hot-toast'

export default function Toast() {
  return (
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
  )
}
