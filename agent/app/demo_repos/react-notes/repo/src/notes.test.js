import { describe, expect, it } from 'vitest'
import { addNote, filterNotes, removeNote, sortNotes, togglePin, wordCount } from './notes.js'

const base = [
  { id: 1, title: 'Alpha', body: 'first note', pinned: false, created: 1 },
  { id: 2, title: 'Beta', body: 'second note', pinned: true, created: 2 },
]

describe('notes helpers', () => {
  it('adds a note with the next id and trims text', () => {
    const next = addNote(base, '  Gamma ', ' hi ')
    expect(next[0]).toMatchObject({ id: 3, title: 'Gamma', body: 'hi' })
    expect(next).toHaveLength(3)
  })

  it('ignores blank titles', () => {
    expect(addNote(base, '   ')).toBe(base)
  })

  it('removes and pins', () => {
    expect(removeNote(base, 1)).toHaveLength(1)
    expect(togglePin(base, 1)[0].pinned).toBe(true)
  })

  it('filters by title or body', () => {
    expect(filterNotes(base, 'ALPHA')).toHaveLength(1)
    expect(filterNotes(base, 'second')).toHaveLength(1)
    expect(filterNotes(base, '')).toHaveLength(2)
  })

  it('sorts pinned first, then newest or by title', () => {
    expect(sortNotes(base).map((n) => n.id)).toEqual([2, 1])
    expect(sortNotes([{ ...base[0] }, { ...base[1], pinned: false }], 'title').map((n) => n.title)).toEqual(['Alpha', 'Beta'])
  })

  it('counts words', () => {
    expect(wordCount('a b  c')).toBe(3)
    expect(wordCount('')).toBe(0)
  })
})
