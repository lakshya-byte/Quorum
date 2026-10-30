import React, { useState } from 'react'

export default function NoteEditor({ onAdd }) {
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')

  function submit(event) {
    event.preventDefault()
    if (!title.trim()) return
    onAdd(title, body)
    setTitle('')
    setBody('')
  }

  return (
    <form className="editor" onSubmit={submit}>
      <label htmlFor="note-title">Title</label>
      <input
        id="note-title"
        className="field"
        placeholder="Note title"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
      />
      <label htmlFor="note-body">Note</label>
      <textarea
        id="note-body"
        className="field"
        placeholder="Write something..."
        value={body}
        onChange={(e) => setBody(e.target.value)}
      />
      <button type="submit" className="btn">
        Add note
      </button>
    </form>
  )
}
