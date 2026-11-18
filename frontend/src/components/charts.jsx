import React, { useMemo, useRef, useState } from 'react'
import { isNum } from '../lib.js'

const W = 760
const toX = (v, type) => (type === 'date' ? new Date(String(v).slice(0, 10) + 'T00:00:00').getTime() : Number(v))

function niceTicks(min, max, n = 5) {
  if (!isFinite(min) || !isFinite(max)) return [0]
  if (min === max) { max = min + 1 }
  const span = max - min
  const step0 = span / n
  const mag = Math.pow(10, Math.floor(Math.log10(step0)))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= n) || mag * 10
  const out = []
  const end = Math.ceil(max / step - 1e-9) * step
  for (let v = Math.floor(min / step) * step; v <= end + step * 0.001; v += step) out.push(Number(v.toPrecision(12)))
  return out
}

const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const fmtDate = (ms, withYear) => { const d = new Date(ms); return `${withYear ? '' : d.getDate() + ' '}${MON[d.getMonth()]}${withYear ? ' ' + String(d.getFullYear()).slice(2) : ''}` }

function Legend({ items }) {
  return (
    <div className="legend">
      {items.map((s) => (
        <span key={s.name}><i style={{ background: s.color, opacity: s.dashed ? 0.6 : 1 }} />{s.name}</span>
      ))}
    </div>
  )
}

/** Multi-series line chart. series: [{name, color, points:[{x,y}], dashed?}], optional bands: [{color, points:[{x,lo,hi}]}] */
export function LineChart({ series, bands = [], xType = 'date', yFmt = (v) => v, height = 260, monthly, zeroBase = true, refLines = [] }) {
  const [hover, setHover] = useState(null)
  const ref = useRef(null)
  const H = height, L = 64, R = 16, T = 12, B = 30
  const all = useMemo(() => {
    const xs = [], ys = []
    series.forEach((s) => s.points.forEach((p) => { if (isNum(p.y)) { xs.push(toX(p.x, xType)); ys.push(p.y) } }))
    bands.forEach((b) => b.points.forEach((p) => { xs.push(toX(p.x, xType)); if (isNum(p.lo)) ys.push(p.lo); if (isNum(p.hi)) ys.push(p.hi) }))
    refLines.forEach((r) => ys.push(r.y))
    return { xs, ys }
  }, [series, bands, xType, refLines])
  if (!all.xs.length) return <div className="empty">No data</div>
  const x0 = Math.min(...all.xs), x1 = Math.max(...all.xs)
  let y0 = Math.min(...all.ys), y1 = Math.max(...all.ys)
  if (zeroBase && y0 > 0) y0 = 0
  const yt = niceTicks(y0, y1)
  y0 = Math.min(y0, yt[0]); y1 = Math.max(y1, yt[yt.length - 1])
  const sx = (v) => L + ((v - x0) / (x1 - x0 || 1)) * (W - L - R)
  const sy = (v) => T + (1 - (v - y0) / (y1 - y0 || 1)) * (H - T - B)
  const xTicks = xType === 'date'
    ? Array.from({ length: 6 }, (_, i) => x0 + (i * (x1 - x0)) / 5)
    : niceTicks(x0, x1, 6)
  const path = (pts) => pts.filter((p) => isNum(p.y)).map((p, i) => `${i ? 'L' : 'M'}${sx(toX(p.x, xType)).toFixed(1)},${sy(p.y).toFixed(1)}`).join(' ')
  const xsAll = [...new Set(all.xs)].sort((a, b) => a - b)

  const onMove = (e) => {
    const rect = ref.current.getBoundingClientRect()
    const px = ((e.clientX - rect.left) / rect.width) * W
    let best = null, bd = Infinity
    xsAll.forEach((x) => { const d = Math.abs(sx(x) - px); if (d < bd) { bd = d; best = x } })
    setHover(best)
  }
  const hv = hover !== null ? series.map((s) => ({ s, p: s.points.find((p) => toX(p.x, xType) === hover) })).filter((o) => o.p) : []

  return (
    <div className="chart">
      <svg ref={ref} viewBox={`0 0 ${W} ${H}`} onMouseMove={onMove} onMouseLeave={() => setHover(null)} role="img">
        {yt.map((t) => (
          <g key={t}>
            <line x1={L} x2={W - R} y1={sy(t)} y2={sy(t)} className="grid" />
            <text x={L - 6} y={sy(t) + 4} textAnchor="end" className="axis">{yFmt(t)}</text>
          </g>
        ))}
        {xTicks.map((t, i) => (
          <text key={i} x={sx(t)} y={H - 10} textAnchor="middle" className="axis">
            {xType === 'date' ? fmtDate(t, monthly) : Math.round(t)}
          </text>
        ))}
        {refLines.map((r, i) => (
          <g key={i}>
            <line x1={L} x2={W - R} y1={sy(r.y)} y2={sy(r.y)} className="ref" />
            <text x={W - R} y={sy(r.y) - 4} textAnchor="end" className="axis">{r.label}</text>
          </g>
        ))}
        {bands.map((b, i) => {
          const pts = b.points.filter((p) => isNum(p.lo) && isNum(p.hi))
          if (!pts.length) return null
          const d = pts.map((p, j) => `${j ? 'L' : 'M'}${sx(toX(p.x, xType))},${sy(p.hi)}`).join(' ') + ' ' +
            [...pts].reverse().map((p) => `L${sx(toX(p.x, xType))},${sy(p.lo)}`).join(' ') + ' Z'
          return <path key={i} d={d} fill={b.color} opacity={0.15} />
        })}
        {series.map((s) => (
          <path key={s.name} d={path(s.points)} fill="none" stroke={s.color} strokeWidth={s.width || 2}
            strokeDasharray={s.dashed ? '5 4' : undefined} />
        ))}
        {series.filter((s) => s.dots).map((s) => s.points.filter((p) => isNum(p.y)).map((p, i) => (
          <circle key={s.name + i} cx={sx(toX(p.x, xType))} cy={sy(p.y)} r={2.5} fill={s.color} />
        )))}
        {hover !== null && <line x1={sx(hover)} x2={sx(hover)} y1={T} y2={H - B} className="hover-line" />}
      </svg>
      {hover !== null && hv.length > 0 && (
        <div className="tooltip" style={{ left: `${Math.min(80, (sx(hover) / W) * 100)}%` }}>
          <div className="tt-head">{xType === 'date' ? fmtDate(hover, false) + ' ' + new Date(hover).getFullYear() : hover}</div>
          {hv.map(({ s, p }) => <div key={s.name}><i style={{ background: s.color }} />{s.name}: <b>{yFmt(p.y)}</b></div>)}
        </div>
      )}
      <Legend items={series} />
    </div>
  )
}

/** Horizontal bars. data: [{label, value, color?, sub?}] */
export function BarChart({ data, fmt = (v) => v, color = '#2563eb', max: maxIn, labelWidth = 200 }) {
  if (!data || !data.length) return <div className="empty">No data</div>
  const vals = data.map((d) => d.value).filter(isNum)
  const max = maxIn ?? Math.max(...vals.map(Math.abs), 1)
  const hasNeg = vals.some((v) => v < 0 && Math.abs(v) > max * 0.005)
  return (
    <div className="hbars">
      {data.map((d, i) => {
        const w = isNum(d.value) && (hasNeg || d.value > 0) ? (Math.abs(d.value) / max) * (hasNeg ? 50 : 100) : 0
        return (
          <div className="hbar" key={i} title={`${d.label}: ${fmt(d.value)}`}>
            <span className="hbar-label" style={{ width: labelWidth }}>{d.label}</span>
            <span className="hbar-track">
              <span className="hbar-fill" style={{
                width: `${Math.max(w, 0.5)}%`, background: d.color || color,
                marginLeft: hasNeg ? (d.value < 0 ? `${50 - w}%` : '50%') : 0,
              }} />
            </span>
            <span className="hbar-val">{fmt(d.value)}{d.sub ? <em> {d.sub}</em> : null}</span>
          </div>
        )
      })}
    </div>
  )
}

/** Grouped columns. categories: [...], series: [{name, color, values: []}] */
export function ColumnChart({ categories, series, yFmt = (v) => v, height = 240 }) {
  if (!categories || !categories.length) return <div className="empty">No data</div>
  const H = height, L = 64, R = 10, T = 14, B = 34
  const vals = series.flatMap((s) => s.values).filter(isNum)
  const yt = niceTicks(Math.min(0, ...vals), Math.max(0, ...vals))
  const y0 = yt[0], y1 = yt[yt.length - 1]
  const sy = (v) => T + (1 - (v - y0) / (y1 - y0 || 1)) * (H - T - B)
  const band = (W - L - R) / categories.length
  const bw = Math.min(28, (band * 0.75) / series.length)
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img">
        {yt.map((t) => (
          <g key={t}>
            <line x1={L} x2={W - R} y1={sy(t)} y2={sy(t)} className={t === 0 ? 'zero' : 'grid'} />
            <text x={L - 6} y={sy(t) + 4} textAnchor="end" className="axis">{yFmt(t)}</text>
          </g>
        ))}
        {categories.map((c, i) => {
          const cx = L + band * i + band / 2
          return (
            <g key={i}>
              {series.map((s, j) => {
                const v = s.values[i]
                if (!isNum(v)) return null
                const x = cx - (series.length * bw) / 2 + j * bw
                return (
                  <rect key={j} x={x} width={bw - 2} y={Math.min(sy(v), sy(0))} height={Math.abs(sy(v) - sy(0))} fill={s.color}>
                    <title>{`${c} – ${s.name}: ${yFmt(v)}`}</title>
                  </rect>
                )
              })}
              <text x={cx} y={H - 12} textAnchor="middle" className="axis">{c}</text>
            </g>
          )
        })}
      </svg>
      {series.length > 1 && <Legend items={series} />}
    </div>
  )
}

/** Scatter: points [{x, y, color, label}] */
export function Scatter({ points, xFmt = (v) => v, yFmt = (v) => v, xLabel, yLabel, height = 260 }) {
  if (!points || !points.length) return <div className="empty">No data</div>
  const H = height, L = 64, R = 16, T = 26, B = 40
  const xs = points.map((p) => p.x), ys = points.map((p) => p.y)
  const xt = niceTicks(Math.min(...xs), Math.max(...xs)), yt = niceTicks(Math.min(...ys), Math.max(...ys))
  const sx = (v) => L + ((v - xt[0]) / (xt[xt.length - 1] - xt[0] || 1)) * (W - L - R)
  const sy = (v) => T + (1 - (v - yt[0]) / (yt[yt.length - 1] - yt[0] || 1)) * (H - T - B)
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img">
        {yt.map((t) => <g key={t}><line x1={L} x2={W - R} y1={sy(t)} y2={sy(t)} className="grid" /><text x={L - 6} y={sy(t) + 4} textAnchor="end" className="axis">{yFmt(t)}</text></g>)}
        {xt.map((t) => <text key={t} x={sx(t)} y={H - 22} textAnchor="middle" className="axis">{xFmt(t)}</text>)}
        {xLabel && <text x={(W + L) / 2} y={H - 4} textAnchor="middle" className="axis">{xLabel}</text>}
        {yLabel && <text x={4} y={12} className="axis">{yLabel}</text>}
        {points.map((p, i) => <circle key={i} cx={sx(p.x)} cy={sy(p.y)} r={3.5} fill={p.color || '#2563eb'} opacity={0.7}><title>{p.label}</title></circle>)}
      </svg>
    </div>
  )
}

/** Heat-map table. rows: [..], cols: [..], value(r,c) -> number */
export function Heatmap({ rows, cols, value, fmt = (v) => v, color = '37,99,235', diverging }) {
  const vals = rows.flatMap((r) => cols.map((c) => value(r, c))).filter(isNum)
  const max = Math.max(...vals.map(Math.abs), 1)
  return (
    <div className="table-scroll">
      <table className="heat">
        <thead><tr><th />{cols.map((c) => <th key={c} className="r">{c}</th>)}</tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r}>
              <th>{r}</th>
              {cols.map((c) => {
                const v = value(r, c)
                const a = isNum(v) ? Math.min(Math.abs(v) / max, 1) * 0.75 : 0
                const rgb = diverging && v < 0 ? '220,38,38' : color
                return <td key={c} className="r" style={{ background: `rgba(${rgb},${a})`, color: a > 0.45 ? '#fff' : undefined }}>{isNum(v) ? fmt(v) : ''}</td>
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Progress bar */
export function Progress({ value, marker, label }) {
  return (
    <div className="progress">
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${Math.min(100, Math.max(0, value))}%` }} />
        {isNum(marker) && <div className="progress-marker" style={{ left: `${Math.min(100, marker)}%` }} />}
      </div>
      {label && <div className="progress-label">{label}</div>}
    </div>
  )
}
