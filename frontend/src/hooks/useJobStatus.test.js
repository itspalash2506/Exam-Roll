import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useJobStatus } from './useJobStatus.js'

const sockets = []

vi.mock('../api/client.js', () => ({
  createWebSocket: vi.fn(() => {
    const socket = { close: vi.fn(), onmessage: null, onclose: null, onerror: null }
    sockets.push(socket)
    return socket
  }),
  getJob: vi.fn(() => Promise.resolve({ data: { status: 'processing', progress: 50 } })),
}))

import { createWebSocket } from '../api/client.js'

beforeEach(() => {
  vi.useFakeTimers()
  sockets.length = 0
  createWebSocket.mockClear()
})

afterEach(() => {
  vi.useRealTimers()
})

// P1-22 — a WS disconnect schedules a reconnect via setTimeout; the id was
// never stored, so unmounting (or the jobId changing) couldn't cancel it.
// A stale reconnect firing later opened a WebSocket for a job the component
// had already moved on from.
describe('useJobStatus reconnect timer cleanup', () => {
  it('does not reconnect after unmount even if the socket closes first', () => {
    const { unmount } = renderHook(() => useJobStatus('job-1'))
    expect(createWebSocket).toHaveBeenCalledTimes(1)

    // Simulate the server dropping the connection.
    act(() => {
      sockets[0].onclose()
    })

    unmount()

    // Advance past every possible reconnect delay (1500ms * retry count).
    act(() => {
      vi.advanceTimersByTime(10_000)
    })

    expect(createWebSocket).toHaveBeenCalledTimes(1)
  })

  it('reconnects on close while still mounted (control case)', () => {
    renderHook(() => useJobStatus('job-1'))
    expect(createWebSocket).toHaveBeenCalledTimes(1)

    act(() => {
      sockets[0].onclose()
    })
    act(() => {
      vi.advanceTimersByTime(2000)
    })

    expect(createWebSocket).toHaveBeenCalledTimes(2)
  })
})
