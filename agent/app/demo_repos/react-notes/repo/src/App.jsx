import React, { useState } from 'react'
import Toolbar from './components/Toolbar.jsx'
import NoteEditor from './components/NoteEditor.jsx'
import NoteList from './components/NoteList.jsx'
import { addNote, filterNotes, removeNote, sortNotes, togglePin } from './notes.js'

const SAMPLE = [
  { id: 1, title: 'Groceries', body: 'milk, eggs, bread', pinned: false, created: 1 },
  { id: 2, title: 'Ideas', body: 'ship the swarm demo', pinned: true, created: 2 },
  { id: 3, title: 'Reading list', body: 'three books for the trip', pinned: false, created: 3 },
]

export default function App() {
  const [notes, setNotes] = useState(SAMPLE)
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState('newest')
  const visible = sortNotes(filterNotes(notes, query), sort)

  return (
    <div className="layout">
      <div className="header">
        <img src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='32' height='32'%3E%3Crect width='32' height='32' fill='%23ccc'/%3E%3C/svg%3E" width="32" height="32" />
        <h3 className="brand">Notes</h3>
      </div>
      <Toolbar query={query} onQuery={setQuery} sort={sort} onSort={setSort} />
      <NoteEditor onAdd={(title, body) => setNotes((n) => addNote(n, title, body))} />
      <NoteList notes={visible} onRemove={(id) => setNotes((n) => removeNote(n, id))} onPin={(id) => setNotes((n) => togglePin(n, id))} />
      <div className="footer">{notes.length} notes</div>
    </div>
  )
}
