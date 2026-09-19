import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ClashPanel from './ClashPanel.jsx'

const SEEDED_CLASHES = [
  { student_id: 's1', roll_number: '80001', exam_codes: ['MBAN301', 'MBAN302'], acknowledged: false },
  { student_id: 's2', roll_number: '80002', exam_codes: ['MBAN303', 'MBAN304'], acknowledged: true },
]

describe('ClashPanel', () => {
  it('renders nothing when there are no clashes', () => {
    const { container } = render(<ClashPanel clashes={[]} onAcknowledge={() => {}} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders every seeded clash with its roll number and exam codes', () => {
    render(<ClashPanel clashes={SEEDED_CLASHES} onAcknowledge={() => {}} />)
    expect(screen.getByText('2 timetable clashes')).toBeInTheDocument()
    expect(screen.getByText(/80001/)).toBeInTheDocument()
    expect(screen.getByText(/MBAN301 and MBAN302/)).toBeInTheDocument()
    expect(screen.getByText(/80002/)).toBeInTheDocument()
  })

  it('shows an Acknowledge button for an unresolved clash and Acknowledged for a resolved one', () => {
    render(<ClashPanel clashes={SEEDED_CLASHES} onAcknowledge={() => {}} />)
    expect(screen.getByRole('button', { name: /acknowledge/i })).toBeInTheDocument()
    expect(screen.getByText('Acknowledged')).toBeInTheDocument()
  })

  it('calls onAcknowledge with the right student id when clicked', async () => {
    const onAcknowledge = vi.fn()
    render(<ClashPanel clashes={SEEDED_CLASHES} onAcknowledge={onAcknowledge} />)
    await userEvent.click(screen.getByRole('button', { name: /acknowledge/i }))
    expect(onAcknowledge).toHaveBeenCalledWith('s1')
  })
})
