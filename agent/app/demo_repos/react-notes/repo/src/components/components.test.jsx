import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import App from '../App.jsx'
import NoteList from './NoteList.jsx'
import NoteEditor from './NoteEditor.jsx'

describe('components', () => {
  it('renders the sample notes', () => {
    const html = renderToStaticMarkup(<App />)
    expect(html).toContain('Groceries')
    expect(html).toContain('Reading list')
    expect(html).toContain('3 notes')
  })

  it('shows the empty state', () => {
    expect(renderToStaticMarkup(<NoteList notes={[]} onRemove={() => {}} onPin={() => {}} />)).toContain('No notes yet')
  })

  it('renders an editor with an add button', () => {
    const html = renderToStaticMarkup(<NoteEditor onAdd={() => {}} />)
    expect(html).toContain('Add note')
    expect(html).toContain('Note title')
  })

  it('shows word counts', () => {
    const notes = [{ id: 1, title: 'T', body: 'one two three', pinned: false, created: 1 }]
    expect(renderToStaticMarkup(<NoteList notes={notes} onRemove={() => {}} onPin={() => {}} />)).toContain('3 words')
  })
})
