import React from 'react'

export default function Toolbar({ query, onQuery, sort, onSort }) {
  return (
    <div className="toolbar" role="search">
      <label className="visually-label" htmlFor="search-notes">
        Search notes
      </label>
      <input
        id="search-notes"
        className="search"
        placeholder="Search notes"
        value={query}
        onChange={(e) => onQuery(e.target.value)}
      />
      <label className="visually-label" htmlFor="sort-notes">
        Sort by
      </label>
      <select id="sort-notes" className="sort" value={sort} onChange={(e) => onSort(e.target.value)}>
        <option value="newest">Newest</option>
        <option value="title">Title</option>
      </select>
    </div>
  )
}
