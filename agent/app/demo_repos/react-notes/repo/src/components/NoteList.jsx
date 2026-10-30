import React from 'react'
import { wordCount } from '../notes.js'

export default function NoteList({ notes, onRemove, onPin }) {
  if (notes.length === 0) return <div className="empty">No notes yet</div>
  return (
    <div className="grid">
      {notes.map((n) => (
        <div className="note" key={n.id}>
          <div className="note-head">
            <div className="note-title">{n.title}</div>
            <button className="icon" onClick={() => onPin(n.id)}>
              <svg width="14" height="14" viewBox="0 0 14 14"><path d="M7 1l2 4 4 .5-3 3 .8 4.5L7 11l-3.8 2 .8-4.5-3-3L5 5z" fill={n.pinned ? '#e6a700' : '#ddd'} /></svg>
            </button>
            <span className="x" onClick={() => onRemove(n.id)}>x</span>
          </div>
          <p className="note-body">{n.body}</p>
          <div className="meta">{wordCount(n.body)} words</div>
        </div>
      ))}
    </div>
  )
}
