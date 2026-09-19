import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Sparkles, Trash2 } from 'lucide-react'
import toast from 'react-hot-toast'
import Button from '../components/common/Button.jsx'
import Badge from '../components/common/Badge.jsx'
import GenerateRoomsDialog from '../components/rooms/GenerateRoomsDialog.jsx'
import RoomEditor from '../components/rooms/RoomEditor.jsx'
import { getRooms, createRoom, updateRoom, deleteRoom, generateRooms } from '../api/client.js'

const BLANK_ROOM = {
  name: 'New Room',
  seat_columns: [{ label: 'Col 1', seats: 1 }],
  blocked_seats: [],
  seats_per_bench: 1,
}

export default function Rooms() {
  useEffect(() => {
    document.title = 'Rooms | ExamRoll'
  }, [])

  const queryClient = useQueryClient()
  const { data: rooms, isLoading } = useQuery({
    queryKey: ['rooms'],
    queryFn: async () => (await getRooms()).data,
  })

  const [generateOpen, setGenerateOpen] = useState(false)
  const [selectedId, setSelectedId] = useState(null)

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['rooms'] })

  const createMutation = useMutation({
    mutationFn: () => createRoom(BLANK_ROOM),
    onSuccess: (res) => {
      invalidate()
      setSelectedId(res.data.id)
    },
    onError: (err) => toast.error(err.message || 'Could not create room'),
  })

  const generateMutation = useMutation({
    mutationFn: (payload) => generateRooms(payload),
    onSuccess: (res) => {
      invalidate()
      setGenerateOpen(false)
      toast.success(`${res.data.length} rooms created`)
    },
    onError: (err) => toast.error(err.message || 'Could not generate rooms'),
  })

  const updateMutation = useMutation({
    mutationFn: (payload) => updateRoom(selectedId, payload),
    onSuccess: () => {
      invalidate()
      toast.success('Room saved')
    },
    onError: (err) => toast.error(err.message || 'Could not save room'),
  })

  const deleteMutation = useMutation({
    mutationFn: (roomId) => deleteRoom(roomId),
    onSuccess: () => {
      invalidate()
      if (selectedId) setSelectedId(null)
    },
    onError: (err) => toast.error(err.message || 'Could not delete room'),
  })

  const selectedRoom = rooms?.find((r) => r.id === selectedId)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-h1 font-medium text-ink">Rooms</h1>
          <p className="mt-1 text-small text-muted">The room library used to build seating plans</p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => setGenerateOpen(true)}>
            <Sparkles size={15} /> Generate rooms
          </Button>
          <Button variant="primary" onClick={() => createMutation.mutate()} loading={createMutation.isPending}>
            <Plus size={15} /> New room
          </Button>
        </div>
      </div>

      <div className="overflow-x-auto rounded-2xl border border-line bg-surface shadow-warm">
        <table className="w-full text-left text-small">
          <thead>
            <tr className="border-b border-line text-caption font-medium uppercase tracking-wide text-muted">
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Building</th>
              <th className="px-4 py-3">Columns</th>
              <th className="px-4 py-3">Capacity</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr><td colSpan={6} className="px-4 py-6 text-center text-muted">Loading…</td></tr>
            )}
            {!isLoading && rooms?.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-6 text-center text-muted">No rooms yet</td></tr>
            )}
            {rooms?.map((room) => (
              <tr
                key={room.id}
                onClick={() => setSelectedId(room.id)}
                className={`cursor-pointer border-b border-line last:border-0 transition-colors duration-fast hover:bg-highlight/20 ${selectedId === room.id ? 'bg-highlight/30' : ''}`}
              >
                <td className="px-4 py-3 font-medium text-ink">{room.name}</td>
                <td className="px-4 py-3 text-muted">{room.building || '—'}</td>
                <td className="px-4 py-3 text-muted">{room.seat_columns.length}</td>
                <td className="px-4 py-3 text-muted">{room.capacity}</td>
                <td className="px-4 py-3">
                  <Badge status={room.is_active ? 'completed' : 'queued'} label={room.is_active ? 'Active' : 'Inactive'} />
                </td>
                <td className="px-4 py-3">
                  <button
                    onClick={(e) => { e.stopPropagation(); deleteMutation.mutate(room.id) }}
                    className="text-muted hover:text-error"
                    title="Delete room"
                  >
                    <Trash2 size={15} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {selectedRoom && (
        <div className="rounded-2xl border border-line bg-surface p-5 shadow-warm">
          <h2 className="mb-4 text-small font-semibold text-ink">Editing {selectedRoom.name}</h2>
          <RoomEditor
            key={selectedRoom.id}
            room={selectedRoom}
            onSave={(payload) => updateMutation.mutate(payload)}
            saving={updateMutation.isPending}
          />
        </div>
      )}

      <GenerateRoomsDialog
        open={generateOpen}
        onClose={() => setGenerateOpen(false)}
        onGenerate={(payload) => generateMutation.mutate(payload)}
        generating={generateMutation.isPending}
      />
    </div>
  )
}
