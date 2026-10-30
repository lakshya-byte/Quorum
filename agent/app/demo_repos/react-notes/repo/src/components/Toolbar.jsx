import React from 'react'

export default function Toolbar({ query, onQuery, sort, onSort }) {
  return (
    <div className="toolbar">
      <input className="search" placeholder="Search notes" value={query} onChange={(e) => onQuery(e.target.value)} />
      <select className="sort" value={sort} onChange={(e) => onSort(e.target.value)}>
        <option value="newest">Newest</option>
        <option value="title">Title</option>
      </select>
    </div>
  )
}
