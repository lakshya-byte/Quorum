import React from 'react'
import { wordCount } from '../notes.js'

export default function NoteList({ notes, onRemove, onPin }) {
  if (notes.length === 0) return <p className="empty">No notes yet</p>
  return (
    <ul className="grid">
      {notes.map((n) => (
        <li className="note" key={n.id}>
          <div className="note-head">
            <h2 className="note-title">{n.title}</h2>
            <button
              type="button"
              className="icon"
              aria-pressed={n.pinned}
              aria-label={`${n.pinned ? 'Unpin' : 'Pin'} note ${n.title}`}
              onClick={() => onPin(n.id)}
            >
              <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true" focusable="false">
                <path d="M7 1l2 4 4 .5-3 3 .8 4.5L7 11l-3.8 2 .8-4.5-3-3L5 5z" fill={n.pinned ? '#b45309' : '#6b7280'} />
              </svg>
            </button>
            <button type="button" className="icon x" aria-label={`Delete note ${n.title}`} onClick={() => onRemove(n.id)}>
              <span aria-hidden="true">x</span>
            </button>
          </div>
          <p className="note-body">{n.body}</p>
          <div className="meta">{wordCount(n.body)} words</div>
        </li>
      ))}
    </ul>
  )
}
