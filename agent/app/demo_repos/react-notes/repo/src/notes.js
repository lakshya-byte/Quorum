// Pure note helpers (no React): easy to unit test.

export function createNote(id, title, body = '', pinned = false) {
  return { id, title: title.trim(), body: body.trim(), pinned, created: id }
}

export function addNote(notes, title, body = '') {
  if (!title || !title.trim()) return notes
  const id = notes.reduce((max, n) => Math.max(max, n.id), 0) + 1
  return [createNote(id, title, body), ...notes]
}

export function removeNote(notes, id) {
  return notes.filter((n) => n.id !== id)
}

export function togglePin(notes, id) {
  return notes.map((n) => (n.id === id ? { ...n, pinned: !n.pinned } : n))
}

export function filterNotes(notes, query) {
  const q = (query || '').trim().toLowerCase()
  if (!q) return notes
  return notes.filter((n) => n.title.toLowerCase().includes(q) || n.body.toLowerCase().includes(q))
}

export function sortNotes(notes, by = 'newest') {
  const copy = [...notes]
  copy.sort((a, b) => {
    if (a.pinned !== b.pinned) return a.pinned ? -1 : 1
    if (by === 'title') return a.title.localeCompare(b.title)
    return b.created - a.created
  })
  return copy
}

export function wordCount(text) {
  const t = (text || '').trim()
  return t ? t.split(/\s+/).length : 0
}
