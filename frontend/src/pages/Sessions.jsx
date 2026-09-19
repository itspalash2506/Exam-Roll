import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueries, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import toast from 'react-hot-toast'
import Button from '../components/common/Button.jsx'
import ClashPanel from '../components/sessions/ClashPanel.jsx'
import {
  getSessions, createSession, getExams, getExamOfferings,
  setSessionPapers, acknowledgeClash, getRooms,
} from '../api/client.js'

function SessionForm({ onCreate, creating }) {
  const [date, setDate] = useState('')
  const [shift, setShift] = useState('Morning')

  return (
    <div className="flex flex-wrap items-end gap-3 rounded-2xl border border-line bg-surface p-4 shadow-warm">
      <div className="space-y-1.5">
        <label className="text-caption font-medium uppercase tracking-wide text-muted">Date</label>
        <input
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          className="rounded-xl border border-line px-3 py-2 text-small text-ink focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
        />
      </div>
      <div className="space-y-1.5">
        <label className="text-caption font-medium uppercase tracking-wide text-muted">Shift</label>
        <input
          value={shift}
          onChange={(e) => setShift(e.target.value)}
          className="rounded-xl border border-line px-3 py-2 text-small text-ink focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
        />
      </div>
      <Button
        variant="primary"
        disabled={!date || !shift}
        loading={creating}
        onClick={() => onCreate({ date, shift })}
      >
        <Plus size={15} /> New session
      </Button>
    </div>
  )
}

function SeatsBar({ required, available }) {
  const short = available < required
  const pct = required > 0 ? Math.min(100, Math.round((available / required) * 100)) : 100
  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-caption text-muted">
        <span>Required seats / available seats</span>
        <span className={short ? 'font-semibold text-error' : 'font-semibold text-success'}>
          {required} / {available}
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-line">
        <div
          className={`h-full rounded-full ${short ? 'bg-error' : 'bg-success'}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

export default function Sessions() {
  useEffect(() => {
    document.title = 'Sessions | ExamRoll'
  }, [])

  const queryClient = useQueryClient()
  const { data: sessions } = useQuery({
    queryKey: ['sessions'],
    queryFn: async () => (await getSessions()).data,
  })
  const { data: exams } = useQuery({
    queryKey: ['exams'],
    queryFn: async () => (await getExams()).data,
  })
  const { data: rooms } = useQuery({
    queryKey: ['rooms'],
    queryFn: async () => (await getRooms()).data,
  })

  const offeringQueries = useQueries({
    queries: (exams ?? []).map((exam) => ({
      queryKey: ['offerings', exam.id],
      queryFn: async () => (await getExamOfferings(exam.id)).data.map((o) => ({ ...o, examTitle: exam.title })),
      enabled: !!exams,
    })),
  })
  const allOfferings = useMemo(
    () => offeringQueries.flatMap((q) => q.data ?? []),
    [offeringQueries],
  )

  const [selectedSessionId, setSelectedSessionId] = useState(null)
  const [checkedOfferingIds, setCheckedOfferingIds] = useState(new Set())
  const [checkedRoomIds, setCheckedRoomIds] = useState(new Set())
  const [acknowledging, setAcknowledging] = useState(null)

  const selectedSession = sessions?.find((s) => s.id === selectedSessionId)

  useEffect(() => {
    if (selectedSession) setCheckedOfferingIds(new Set(selectedSession.offering_ids))
  }, [selectedSession?.id])

  const createMutation = useMutation({
    mutationFn: (payload) => createSession(payload),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
      setSelectedSessionId(res.data.id)
      toast.success('Session created')
    },
    onError: (err) => toast.error(err.message || 'Could not create session'),
  })

  const savePapersMutation = useMutation({
    mutationFn: () => setSessionPapers(selectedSessionId, [...checkedOfferingIds]),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
      toast.success('Papers saved')
    },
    onError: (err) => toast.error(err.message || 'Could not save papers'),
  })

  const handleAcknowledge = async (studentId) => {
    setAcknowledging(studentId)
    try {
      await acknowledgeClash(selectedSessionId, studentId)
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
    } catch (err) {
      toast.error(err.message || 'Could not acknowledge clash')
    } finally {
      setAcknowledging(null)
    }
  }

  // Grouped by exam, then course — §15.2 step 3.
  const groupedOfferings = useMemo(() => {
    const byExam = new Map()
    for (const o of allOfferings) {
      if (!byExam.has(o.examTitle)) byExam.set(o.examTitle, new Map())
      const byCourse = byExam.get(o.examTitle)
      const courseKey = o.course_name || 'Other'
      if (!byCourse.has(courseKey)) byCourse.set(courseKey, [])
      byCourse.get(courseKey).push(o)
    }
    return byExam
  }, [allOfferings])

  const toggleOffering = (id) => {
    setCheckedOfferingIds((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const toggleRoom = (id) => {
    setCheckedRoomIds((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const requiredSeats = allOfferings
    .filter((o) => checkedOfferingIds.has(o.id))
    .reduce((sum, o) => sum + o.enrollment_count, 0)
  const availableSeats = (rooms ?? [])
    .filter((r) => checkedRoomIds.has(r.id))
    .reduce((sum, r) => sum + r.capacity, 0)

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-h1 font-medium text-ink">Sessions</h1>
        <p className="mt-1 text-small text-muted">One centre day-shift, and which papers sit in it</p>
      </div>

      <SessionForm onCreate={(p) => createMutation.mutate(p)} creating={createMutation.isPending} />

      <div className="space-y-2">
        {sessions?.map((s) => (
          <button
            key={s.id}
            onClick={() => setSelectedSessionId(s.id)}
            className={`w-full rounded-xl border px-4 py-3 text-left text-small transition-colors duration-fast ${selectedSessionId === s.id ? 'border-primary bg-primary/5' : 'border-line bg-surface hover:bg-highlight/20'}`}
          >
            <span className="font-medium text-ink">{s.date}</span>
            <span className="ml-2 text-muted">{s.shift}</span>
            <span className="ml-2 text-caption text-muted">· {s.offering_ids.length} paper(s)</span>
            {s.clashes?.some((c) => !c.acknowledged) && (
              <span className="ml-2 text-caption font-medium text-warning">· unresolved clash</span>
            )}
          </button>
        ))}
      </div>

      {selectedSession && (
        <div className="space-y-4 rounded-2xl border border-line bg-surface p-5 shadow-warm">
          <h2 className="text-small font-semibold text-ink">
            Papers for {selectedSession.date} · {selectedSession.shift}
          </h2>

          {[...groupedOfferings.entries()].map(([examTitle, byCourse]) => (
            <div key={examTitle} className="space-y-2">
              <p className="text-caption font-medium uppercase tracking-wide text-muted">{examTitle}</p>
              {[...byCourse.entries()].map(([courseName, offerings]) => (
                <div key={courseName} className="pl-3">
                  <p className="text-caption text-muted">{courseName}</p>
                  <div className="flex flex-wrap gap-2 pt-1">
                    {offerings.map((o) => (
                      <label
                        key={o.id}
                        className={`flex cursor-pointer items-center gap-1.5 rounded-full border px-3 py-1 text-caption ${checkedOfferingIds.has(o.id) ? 'border-primary bg-primary/10 text-primary' : 'border-line text-muted'}`}
                      >
                        <input
                          type="checkbox"
                          className="hidden"
                          checked={checkedOfferingIds.has(o.id)}
                          onChange={() => toggleOffering(o.id)}
                        />
                        {o.exam_code} · {o.enrollment_count} enrolled
                      </label>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          ))}

          <Button variant="primary" size="sm" onClick={() => savePapersMutation.mutate()} loading={savePapersMutation.isPending}>
            Save papers
          </Button>

          <ClashPanel
            clashes={selectedSession.clashes}
            onAcknowledge={handleAcknowledge}
            acknowledging={acknowledging}
          />

          <div className="space-y-2 border-t border-line pt-4">
            <p className="text-small font-semibold text-ink">Rooms for this session</p>
            <div className="flex flex-wrap gap-2">
              {rooms?.filter((r) => r.is_active).map((r) => (
                <label
                  key={r.id}
                  className={`flex cursor-pointer items-center gap-1.5 rounded-full border px-3 py-1 text-caption ${checkedRoomIds.has(r.id) ? 'border-primary bg-primary/10 text-primary' : 'border-line text-muted'}`}
                >
                  <input
                    type="checkbox"
                    className="hidden"
                    checked={checkedRoomIds.has(r.id)}
                    onChange={() => toggleRoom(r.id)}
                  />
                  {r.name} ({r.capacity})
                </label>
              ))}
            </div>
            <SeatsBar required={requiredSeats} available={availableSeats} />
            <p className="text-caption text-muted">
              A live estimate only — the actual room assignment is created when a seating plan is published.
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
