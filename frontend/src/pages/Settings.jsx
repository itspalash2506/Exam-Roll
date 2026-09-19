import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import Button from '../components/common/Button.jsx'
import { getOrgSettings, updateOrgSettings } from '../api/client.js'

export default function Settings() {
  useEffect(() => {
    document.title = 'Settings | ExamRoll'
  }, [])

  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['orgSettings'],
    queryFn: async () => (await getOrgSettings()).data,
  })

  const [form, setForm] = useState(null)

  useEffect(() => {
    if (data) setForm(data)
  }, [data])

  const mutation = useMutation({
    mutationFn: (payload) => updateOrgSettings(payload),
    onSuccess: (res) => {
      queryClient.setQueryData(['orgSettings'], res.data)
      setForm(res.data)
      toast.success('Settings saved')
    },
    onError: (err) => toast.error(err.message || 'Could not save settings'),
  })

  if (isLoading || !form) {
    return <p className="text-small text-muted">Loading…</p>
  }

  const handleSave = () => {
    mutation.mutate({
      name: form.name,
      centre_code: form.centre_code,
      university_name: form.university_name,
      ai_processing_enabled: form.ai_processing_enabled,
    })
  }

  return (
    <div className="mx-auto max-w-xl space-y-6">
      <div>
        <h1 className="font-display text-h1 font-medium text-ink">Settings</h1>
        <p className="mt-1 text-small text-muted">Organization details and AI processing</p>
      </div>

      <div className="rounded-2xl border border-line bg-surface p-5 shadow-warm space-y-4">
        <div className="space-y-1.5">
          <label className="text-caption font-medium uppercase tracking-wide text-muted">
            Organization name
          </label>
          <input
            type="text"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className="w-full rounded-xl border border-line px-3 py-2 text-small text-ink focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>

        <div className="space-y-1.5">
          <label className="text-caption font-medium uppercase tracking-wide text-muted">
            Centre code
          </label>
          <input
            type="text"
            value={form.centre_code ?? ''}
            onChange={(e) => setForm({ ...form, centre_code: e.target.value })}
            className="w-full rounded-xl border border-line px-3 py-2 text-small text-ink focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>

        <div className="space-y-1.5">
          <label className="text-caption font-medium uppercase tracking-wide text-muted">
            University name
          </label>
          <input
            type="text"
            value={form.university_name ?? ''}
            onChange={(e) => setForm({ ...form, university_name: e.target.value })}
            className="w-full rounded-xl border border-line px-3 py-2 text-small text-ink focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>
      </div>

      <div className="rounded-2xl border border-line bg-surface p-5 shadow-warm space-y-3">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-small font-semibold text-ink">AI-assisted classification</p>
            <p className="mt-1 text-caption text-muted">
              When enabled, a sample of each uploaded document is sent to Groq's API for
              document-type detection and subject-name enrichment. When disabled, only
              rule-based extraction runs and nothing leaves this server.
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={form.ai_processing_enabled}
            onClick={() => setForm({ ...form, ai_processing_enabled: !form.ai_processing_enabled })}
            className={`relative h-6 w-11 flex-shrink-0 rounded-full transition-colors duration-fast ${
              form.ai_processing_enabled ? 'bg-primary' : 'bg-line'
            }`}
          >
            <span
              className={`absolute top-0.5 h-5 w-5 rounded-full bg-surface shadow transition-transform duration-fast ${
                form.ai_processing_enabled ? 'translate-x-5' : 'translate-x-0.5'
              }`}
            />
          </button>
        </div>
      </div>

      <Button variant="primary" size="lg" onClick={handleSave} loading={mutation.isPending}>
        Save changes
      </Button>
    </div>
  )
}
