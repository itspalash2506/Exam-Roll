import { describe, it, expect } from 'vitest'
import { getJobRefetchInterval } from './JobDetail.jsx'

// P1-20 — react-query v5 passes the Query object, not the raw data. The
// callback must read query.state.data and return false once the job is
// terminal, or polling never stops.
describe('getJobRefetchInterval', () => {
  it('keeps polling when there is no data yet', () => {
    expect(getJobRefetchInterval({ state: { data: undefined } })).toBe(3000)
  })

  it('keeps polling while the job is processing', () => {
    expect(getJobRefetchInterval({ state: { data: { status: 'processing' } } })).toBe(3000)
  })

  it('stops polling once the job has completed', () => {
    expect(getJobRefetchInterval({ state: { data: { status: 'completed' } } })).toBe(false)
  })

  it('stops polling once the job has failed', () => {
    expect(getJobRefetchInterval({ state: { data: { status: 'failed' } } })).toBe(false)
  })
})
