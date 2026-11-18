import React, { useMemo, useState } from 'react'
import { downloadCsv, isNum } from '../lib.js'
import { Empty } from './ui.jsx'

/**
 * columns: [{ key, label, fmt?: (v,row)=>node, align?: 'right', width? }]
 */
export default function DataTable({ columns, rows, pageSize = 15, filename = 'table.csv', search = true, initialSort }) {
  const [q, setQ] = useState('')
  const [sort, setSort] = useState(initialSort || null) // {key, dir}
  const [page, setPage] = useState(0)

  const filtered = useMemo(() => {
    let r = rows || []
    if (q) {
      const s = q.toLowerCase()
      r = r.filter((row) => columns.some((c) => String(row[c.key] ?? '').toLowerCase().includes(s)))
    }
    if (sort) {
      const { key, dir } = sort
      r = [...r].sort((a, b) => {
        const x = a[key], y = b[key]
        if (x === y) return 0
        if (x === null || x === undefined) return 1
        if (y === null || y === undefined) return -1
        const c = isNum(x) && isNum(y) ? x - y : String(x).localeCompare(String(y))
        return dir === 'asc' ? c : -c
      })
    }
    return r
  }, [rows, q, sort, columns])

  if (!rows || !rows.length) return <Empty />
  const pages = Math.max(1, Math.ceil(filtered.length / pageSize))
  const p = Math.min(page, pages - 1)
  const shown = filtered.slice(p * pageSize, (p + 1) * pageSize)

  const toggle = (key) => {
    setPage(0)
    setSort((s) => (s && s.key === key ? { key, dir: s.dir === 'desc' ? 'asc' : 'desc' } : { key, dir: 'desc' }))
  }

  return (
    <div className="table-wrap">
      <div className="table-tools">
        {search && <input className="search" placeholder="Search…" value={q} onChange={(e) => { setQ(e.target.value); setPage(0) }} />}
        <span className="muted">{filtered.length} rows</span>
        <button className="link" onClick={() => downloadCsv(filename, columns, filtered)}>Download CSV</button>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c.key} className={c.align === 'right' ? 'r' : ''} style={c.width ? { width: c.width } : undefined}
                  onClick={() => toggle(c.key)}>
                  {c.label}{sort && sort.key === c.key ? (sort.dir === 'desc' ? ' ▾' : ' ▴') : ''}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((row, i) => (
              <tr key={i}>
                {columns.map((c) => (
                  <td key={c.key} className={c.align === 'right' ? 'r' : ''}>
                    {c.fmt ? c.fmt(row[c.key], row) : (row[c.key] ?? '–')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {pages > 1 && (
        <div className="pager">
          <button disabled={p === 0} onClick={() => setPage(p - 1)}>‹ Prev</button>
          <span>Page {p + 1} of {pages}</span>
          <button disabled={p >= pages - 1} onClick={() => setPage(p + 1)}>Next ›</button>
        </div>
      )}
    </div>
  )
}
