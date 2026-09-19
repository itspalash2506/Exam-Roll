import { describe, it, expect } from 'vitest'
import { validateGenerateForm } from './GenerateRoomsDialog.jsx'

const VALID = { count: 5, columns: 4, seatsPerColumn: 10, namePattern: 'Room No {n}' }

describe('validateGenerateForm', () => {
  it('accepts a well-formed form', () => {
    expect(validateGenerateForm(VALID)).toEqual({})
  })

  it('rejects a count below 1', () => {
    const errors = validateGenerateForm({ ...VALID, count: 0 })
    expect(errors.count).toBeTruthy()
  })

  it('rejects a non-integer count', () => {
    const errors = validateGenerateForm({ ...VALID, count: 2.5 })
    expect(errors.count).toBeTruthy()
  })

  it('rejects columns below 1', () => {
    const errors = validateGenerateForm({ ...VALID, columns: 0 })
    expect(errors.columns).toBeTruthy()
  })

  it('rejects seatsPerColumn below 1', () => {
    const errors = validateGenerateForm({ ...VALID, seatsPerColumn: 0 })
    expect(errors.seatsPerColumn).toBeTruthy()
  })

  it("rejects a name pattern missing '{n}'", () => {
    const errors = validateGenerateForm({ ...VALID, namePattern: 'Room' })
    expect(errors.namePattern).toBeTruthy()
  })

  it('reports every invalid field at once', () => {
    const errors = validateGenerateForm({
      count: 0, columns: 0, seatsPerColumn: 0, namePattern: 'Room',
    })
    expect(Object.keys(errors).sort()).toEqual(
      ['columns', 'count', 'namePattern', 'seatsPerColumn'].sort(),
    )
  })
})
