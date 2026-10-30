import React, { useState } from 'react'

export default function NoteEditor({ onAdd }) {
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')

  function submit() {
    if (!title.trim()) return
    onAdd(title, body)
    setTitle('')
    setBody('')
  }

  return (
    <div className="editor">
      <input className="field" placeholder="Note title" value={title} onChange={(e) => setTitle(e.target.value)} />
      <textarea className="field" placeholder="Write something..." value={body} onChange={(e) => setBody(e.target.value)} />
      <div className="btn" onClick={submit}>Add note</div>
    </div>
  )
}
