import React, { useState } from 'react'
import { Async, Card, Kpi, KpiRow, Tabs, Select, Note, Bullets } from '../components/ui.jsx'
import DataTable from '../components/DataTable.jsx'
import { LineChart, BarChart, ColumnChart, Heatmap, Scatter, Progress } from '../components/charts.jsx'
import { inr, inrFull, rs2, num, kg, pct, spct, dt, mon, days, familyColor } from '../lib.js'

const TABS = [
  { id: 'overview', label: 'Sales & realisation' },
  { id: 'geo', label: 'Routes & customers' },
  { id: 'forecast', label: 'Forecast & seasonality' },
  { id: 'actions', label: 'Customer actions' },
]

export default function SalesPage() {
  const [tab, setTab] = useState('overview')
  return (
    <>
      <Tabs tabs={TABS} value={tab} onChange={setTab} />
      {tab === 'overview' && <Overview />}
      {tab === 'geo' && <Geo />}
      {tab === 'forecast' && <Forecast />}
      {tab === 'actions' && <Actions />}
    </>
  )
}

// ------------------------------------------------------------------ overview
function Overview() {
  return (
    <div className="grid">
      <Async path="/sales/overview">{(d) => (
        <Card wide title="Net sales" priority="Must-have" kind="KPI" item="Net sales in ₹: today, month, year, vs last year; year progress to date"
          note={`Net of GST, round-off and trade discounts. Last year = same dates last year. As of ${dt(d.as_of)}; last billing day ${dt(d.last_billing_date)}.`}>
          <KpiRow>
            <Kpi label={`Today (${dt(d.as_of)})`} value={inr(d.today.net_sales)} delta={d.today.growth_pct} sub={`LY ${inr(d.today.ly_net_sales)} · ${d.today.invoices} invoices`} />
            <Kpi label="Month to date" value={inr(d.month.net_sales)} delta={d.month.growth_pct} sub={`LY ${inr(d.month.ly_net_sales)}`} />
            <Kpi label={`${d.fy_label} to date (from 1 April)`} value={inr(d.year.net_sales)} delta={d.year.growth_pct} sub={`LY same date ${inr(d.year.ly_net_sales)}`} />
            <Kpi label="Volume, year to date" value={kg(d.year.kg)} delta={d.year.kg_growth_pct} sub={`LY ${kg(d.year.ly_kg)}`} />
          </KpiRow>
          <div className="split">
            <div>
              <h4>Year progress</h4>
              <Progress value={d.fy_progress.ytd_vs_ly_full_year_pct ?? 0} marker={d.fy_progress.days_elapsed_pct}
                label={d.fy_progress.ly_data_available
                  ? `${pct(d.fy_progress.ytd_vs_ly_full_year_pct)} of last year's full-year sales (${inr(d.fy_progress.ly_full_year_sales)}) achieved, with ${pct(d.fy_progress.days_elapsed_pct)} of the year gone (marker).`
                  : 'Last year not loaded yet'} />
              <h4>Cumulative sales: this year vs last year (by day of financial year)</h4>
              <LineChart xType="number" yFmt={(v) => inr(v, 0)}
                series={[
                  { name: 'This year', color: '#2563eb', points: d.cumulative.map((r) => ({ x: r.day, y: r.this_year })) },
                  { name: 'Last year', color: '#9ca3af', dashed: true, points: d.cumulative.map((r) => ({ x: r.day, y: r.last_year })) },
                ]} />
            </div>
            <div>
              <h4>Monthly net sales</h4>
              <ColumnChart categories={d.monthly.slice(-18).map((r) => mon(r.month))} yFmt={(v) => inr(v, 0)}
                series={[{ name: 'Net sales', color: '#2563eb', values: d.monthly.slice(-18).map((r) => r.net_sales) }]} />
            </div>
          </div>
        </Card>
      )}</Async>

      <Async path="/sales/realisation">{(d) => (
        <Card wide title="Realisation" priority="Must-have" kind="KPI" item="Realisation by SKU type, SKU group / oil type" note={d.note}>
          <div className="split">
            <div>
              <h4>₹ per kg by oil, financial year to date</h4>
              <BarChart data={d.by_family.map((r) => ({ label: r.oil_family, value: r.rs_per_kg, color: familyColor(r.oil_family), sub: `· ${rs2(r.rs_per_litre)}/L` }))} fmt={rs2} max={Math.max(...d.by_family.map((r) => r.rs_per_kg)) * 1.05} />
              <h4>Monthly ₹ per kg</h4>
              <LineChart monthly zeroBase={false} yFmt={(v) => `₹${num(v)}`}
                series={[...new Set(d.monthly.map((r) => r.oil_family))].filter((f) => f !== 'Groundnut seed').map((f) => ({
                  name: f, color: familyColor(f), points: d.monthly.filter((r) => r.oil_family === f).map((r) => ({ x: r.month, y: r.rs_per_kg })),
                }))} />
            </div>
            <div>
              <h4>By SKU type (pack)</h4>
              <DataTable filename="realisation_by_sku_type.csv" pageSize={12} columns={[
                { key: 'oil_family', label: 'Oil' }, { key: 'pack_size', label: 'Pack' },
                { key: 'net_sales', label: 'Net sales', align: 'right', fmt: inr },
                { key: 'kg', label: 'Volume', align: 'right', fmt: kg },
                { key: 'rs_per_kg', label: '₹/kg', align: 'right', fmt: rs2 },
                { key: 'rs_per_litre', label: '₹/L', align: 'right', fmt: rs2 },
              ]} rows={d.by_sku_type} />
            </div>
          </div>
          <details><summary>Realisation by individual SKU</summary>
            <DataTable filename="realisation_by_sku.csv" columns={[
              { key: 'oil_family', label: 'Oil' }, { key: 'stockitemname', label: 'SKU' },
              { key: 'qty', label: 'Units', align: 'right', fmt: num },
              { key: 'rs_per_unit', label: '₹/unit', align: 'right', fmt: rs2 },
              { key: 'rs_per_kg', label: '₹/kg', align: 'right', fmt: rs2 },
              { key: 'net_sales', label: 'Net sales', align: 'right', fmt: inr },
            ]} rows={d.by_sku} />
          </details>
        </Card>
      )}</Async>

      <Async path="/sales/mix">{(d) => {
        const fams = d.by_family.map((r) => r.oil_family)
        const packs = d.by_pack_size.map((r) => r.pack_size)
        const cell = (f, p) => d.matrix.find((m) => m.oil_family === f && m.pack_size === p)?.value_share_pct
        return (
          <Card wide title="Mix by oil type and pack size" priority="Must-have" kind="KPI" item="Mix by oil type and pack size"
            note={`Share of net sales value, ${dt(d.start)} – ${dt(d.end)}.`}>
            <div className="split">
              <div>
                <h4>Value share by oil</h4>
                <BarChart data={d.by_family.map((r) => ({ label: r.oil_family, value: r.value_share_pct, color: familyColor(r.oil_family), sub: `· vol ${pct(r.kg_share_pct)}` }))} fmt={(v) => pct(v)} />
                <h4>Value share by pack size</h4>
                <BarChart data={d.by_pack_size.map((r) => ({ label: r.pack_size, value: r.value_share_pct, sub: `· vol ${pct(r.kg_share_pct)}` }))} fmt={(v) => pct(v)} />
              </div>
              <div>
                <h4>Oil × pack (% of total value)</h4>
                <Heatmap rows={fams} cols={packs} value={cell} fmt={(v) => v.toFixed(1)} />
              </div>
            </div>
          </Card>
        )
      }}</Async>
    </div>
  )
}

// ------------------------------------------------------------------ geography & customers
function Geo() {
  const [dim, setDim] = useState('route')
  return (
    <div className="grid">
      <Async path="/sales/dimension" params={{ dim }}>{(d) => (
        <Card wide title="Sales by city, agent, route and zone" priority="Must-have" kind="KPI" item="City, Agent, Route-wise and zone-wise sales"
          actions={<Select value={dim} onChange={setDim} options={[{ value: 'route', label: 'Route' }, { value: 'city', label: 'City / town' }, { value: 'agent', label: 'Agent' }, { value: 'zone', label: 'Zone' }]} />}
          note={`Financial year to date vs same dates last year. Field used: ${d.field}.`}>
          {d.note && <div className="warn">{d.note}</div>}
          <div className="split">
            <BarChart data={d.rows.slice(0, 15).map((r) => ({ label: r.name, value: r.net_sales, sub: spct(r.growth_pct) }))} fmt={(v) => inr(v)} />
            <DataTable filename={`sales_by_${dim}.csv`} pageSize={10} columns={[
              { key: 'name', label: dim[0].toUpperCase() + dim.slice(1) },
              { key: 'net_sales', label: 'Net sales', align: 'right', fmt: inr },
              { key: 'growth_pct', label: 'vs LY', align: 'right', fmt: spct },
              { key: 'share_pct', label: 'Share', align: 'right', fmt: pct },
              { key: 'customers', label: 'Customers', align: 'right', fmt: num },
              { key: 'kg', label: 'Volume', align: 'right', fmt: kg },
            ]} rows={d.rows} />
          </div>
        </Card>
      )}</Async>

      <Async path="/sales/top-customers">{(d) => (
        <Card wide title="Top 20 customers" priority="Must-have" kind="KPI" item="Top 20 customers and share of top 10"
          note={`Financial year to date. Cash and counter sales (${inr(d.cash_sales)}) are excluded from the ranking but included in the total.`}>
          <KpiRow>
            <Kpi label="Top 10 share of sales" value={pct(d.top10_share_pct)} />
            <Kpi label="Top 20 share of sales" value={pct(d.top20_share_pct)} />
            <Kpi label="Customers billed" value={num(d.customers)} />
            <Kpi label="Total net sales" value={inr(d.total_net_sales)} />
          </KpiRow>
          <DataTable filename="top_customers.csv" pageSize={20} search={false} columns={[
            { key: 'party', label: 'Customer' }, { key: 'route', label: 'Route' }, { key: 'city', label: 'City' },
            { key: 'net_sales', label: 'Net sales', align: 'right', fmt: inr },
            { key: 'share_pct', label: 'Share', align: 'right', fmt: pct },
            { key: 'growth_pct', label: 'vs LY', align: 'right', fmt: spct },
            { key: 'invoices', label: 'Invoices', align: 'right', fmt: num },
          ]} rows={d.rows} />
        </Card>
      )}</Async>

      <Async path="/sales/route-productivity">{(d) => (
        <Card title="Route productivity" priority="Important" kind="KPI" item="Route productivity: customers served, average bill value"
          note={`Last ${d.days} days (${dt(d.start)} – ${dt(d.end)}), excluding cash sales.`}>
          <DataTable filename="route_productivity.csv" pageSize={15} search={false} columns={[
            { key: 'route', label: 'Route' },
            { key: 'customers', label: 'Customers served', align: 'right', fmt: num },
            { key: 'invoices', label: 'Invoices', align: 'right', fmt: num },
            { key: 'avg_bill_value', label: 'Avg bill', align: 'right', fmt: inr },
            { key: 'sales_per_customer', label: 'Sales/customer', align: 'right', fmt: inr },
            { key: 'kg_per_invoice', label: 'kg/invoice', align: 'right', fmt: (v) => num(v) },
            { key: 'net_sales', label: 'Net sales', align: 'right', fmt: inr },
          ]} rows={d.rows} />
        </Card>
      )}</Async>

      <Async path="/sales/returns">{(d) => (
        <Card title="Returns and credit notes" priority="Important" kind="KPI" item="Returns and credit-note rate by customer and SKU"
          note={`Financial year to date. ${pct(d.value_only_share_pct, 0)} of credit-note value has no stock item (rate or discount adjustments, not physical returns).`}>
          <KpiRow>
            <Kpi label="Credit notes" value={inr(d.credit_notes_value)} />
            <Kpi label="As % of sales" value={pct(d.overall_rate_pct, 2)} />
          </KpiRow>
          <h4>By customer</h4>
          <DataTable filename="credit_notes_by_customer.csv" pageSize={8} columns={[
            { key: 'party', label: 'Customer' }, { key: 'credit_notes', label: 'Credit notes', align: 'right', fmt: inr },
            { key: 'sales', label: 'Sales', align: 'right', fmt: inr }, { key: 'rate_pct', label: 'Rate', align: 'right', fmt: (v) => pct(v, 2) },
          ]} rows={d.by_customer} />
          <h4>By SKU</h4>
          <DataTable filename="credit_notes_by_sku.csv" pageSize={8} columns={[
            { key: 'stockitemname', label: 'SKU' }, { key: 'credit_notes', label: 'Credit notes', align: 'right', fmt: inr },
            { key: 'rate_pct', label: 'Rate', align: 'right', fmt: (v) => pct(v, 2) },
          ]} rows={d.by_sku} />
        </Card>
      )}</Async>
    </div>
  )
}

// ------------------------------------------------------------------ forecast
function Forecast() {
  const [horizon, setHorizon] = useState('12')
  const [measure, setMeasure] = useState('net_sales')
  const [scen, setScen] = useState('last_year')
  const yf = measure === 'kg' ? kg : (v) => inr(v)
  return (
    <div className="grid">
      <Async path="/sales/forecast" params={{ horizon, measure }}>{(d) => (
        <Card wide title="Sales forecast by oil family" priority="Must-have" kind="Forecast"
          item="Sales forecast for the next 4–12 weeks by oil family, with a range (two assumptions: last year, last 5 years)"
          actions={<>
            <Select label="Weeks" value={horizon} onChange={setHorizon} options={['4', '6', '8', '12']} />
            <Select label="Measure" value={measure} onChange={setMeasure} options={[{ value: 'net_sales', label: '₹ net sales' }, { value: 'kg', label: 'kg' }]} />
            <Select label="Assumption" value={scen} onChange={setScen} options={[{ value: 'last_year', label: "Last year's pattern" }, { value: 'five_year', label: 'Up to 5 years' }]} />
          </>}
          note={d.note}>
          <table className="mini">
            <thead><tr><th>Oil</th><th className="r">Last year's pattern</th><th className="r">Range</th><th className="r">Up to 5 years</th><th className="r">Range</th><th className="r">Years used</th><th className="r">Backtest error</th></tr></thead>
            <tbody>{d.families.map((f) => {
              const a = f.scenarios.last_year, b = f.scenarios.five_year
              return (
                <tr key={f.family}>
                  <td><i className="dot" style={{ background: familyColor(f.family) }} />{f.family}</td>
                  <td className="r"><b>{yf(a.total)}</b></td><td className="r muted">{yf(a.total_low)} – {yf(a.total_high)}</td>
                  <td className="r"><b>{yf(b.total)}</b></td><td className="r muted">{yf(b.total_low)} – {yf(b.total_high)}</td>
                  <td className="r">{a.years_used} / {b.years_used}</td>
                  <td className="r">{pct(f.scenarios[scen].backtest_error_pct, 0)}</td>
                </tr>
              )
            })}</tbody>
          </table>
          <div className="small-multiples">
            {d.families.map((f) => {
              const s = f.scenarios[scen]
              const other = f.scenarios[scen === 'last_year' ? 'five_year' : 'last_year']
              return (
                <div key={f.family}>
                  <h4>{f.family}</h4>
                  <LineChart height={200} yFmt={yf}
                    bands={[{ color: familyColor(f.family), points: s.weeks.map((w) => ({ x: w.week, lo: w.low, hi: w.high })) }]}
                    series={[
                      { name: 'Actual', color: '#374151', points: f.history.map((h) => ({ x: h.week, y: h.actual })) },
                      { name: s.label, color: familyColor(f.family), dots: true, points: s.weeks.map((w) => ({ x: w.week, y: w.forecast })) },
                      { name: other.label, color: '#9ca3af', dashed: true, points: other.weeks.map((w) => ({ x: w.week, y: w.forecast })) },
                    ]} />
                </div>
              )
            })}
          </div>
        </Card>
      )}</Async>

      <Async path="/sales/festivals">{(d) => {
        const fests = [...new Set(d.rows.map((r) => r.festival))]
        const fams = [...new Set(d.rows.map((r) => r.family))]
        const get = (f, fam, k) => d.rows.find((r) => r.festival === f && r.family === fam)?.[k]
        return (
          <Card wide title="Festival and seasonal effect" priority="Important" kind="Insight"
            item="Festival and seasonal effect on demand (last year, and last 5 years)" note={d.note}>
            {d.upcoming && d.upcoming.length > 0 && <div className="info">Next festivals: {d.upcoming.map((u) => `${u.festival} ${dt(u.date)}`).join(' · ')}</div>}
            <div className="split">
              <div><h4>Uplift, last occurrence (%)</h4><Heatmap rows={fests} cols={fams} value={(f, c) => get(f, c, 'uplift_last_year_pct')} fmt={(v) => spct(v, 0)} diverging /></div>
              <div><h4>Uplift, average of up to 5 years (%)</h4><Heatmap rows={fests} cols={fams} value={(f, c) => get(f, c, 'uplift_5yr_avg_pct')} fmt={(v) => spct(v, 0)} diverging /></div>
            </div>
          </Card>
        )
      }}</Async>

      <Async path="/sales/elasticity">{(d) => (
        <Card wide title="Price vs volume response" priority="Important" kind="Data science" item="Price vs volume response (elasticity) by oil type" note={d.note}>
          <div className="split">
            <table className="mini">
              <thead><tr><th>Oil</th><th className="r">Elasticity</th><th className="r">± s.e.</th><th className="r">Weeks</th><th>Confidence</th></tr></thead>
              <tbody>{d.rows.map((r) => (
                <tr key={r.family}><td>{r.family}</td><td className="r"><b>{r.elasticity === null ? '–' : r.elasticity.toFixed(2)}</b></td>
                  <td className="r">{r.std_error ? r.std_error.toFixed(2) : '–'}</td><td className="r">{r.weeks}</td><td className="muted">{r.confidence}</td></tr>
              ))}</tbody>
            </table>
            <Scatter xLabel="₹ per kg (price index)" yLabel="kg per week" xFmt={(v) => `₹${num(v)}`} yFmt={kg}
              points={d.points.map((p) => ({ x: p.price, y: p.kg, color: familyColor(p.family), label: `${p.family} ${dt(p.week)}: ${rs2(p.price)}/kg, ${kg(p.kg)}` }))} />
          </div>
        </Card>
      )}</Async>
    </div>
  )
}

// ------------------------------------------------------------------ customer actions
function Actions() {
  const [months, setMonths] = useState('12')
  return (
    <div className="grid">
      <Async path="/sales/call-list">{(d) => (
        <Card wide title="Call list: customers due to reorder" priority="Must-have" kind="Recommendation" item="Call list: customers past their usual reorder gap" note={d.rule}>
          <KpiRow><Kpi label="Customers to call" value={num(d.count)} /><Kpi label="Typical order value at stake" value={inr(d.expected_value)} /></KpiRow>
          <DataTable filename="call_list.csv" columns={[
            { key: 'party', label: 'Customer' }, { key: 'route', label: 'Route' }, { key: 'mobile', label: 'Mobile' },
            { key: 'last_date', label: 'Last bill', fmt: dt },
            { key: 'days_since_last', label: 'Days since', align: 'right', fmt: num },
            { key: 'usual_gap_days', label: 'Usual gap', align: 'right', fmt: days },
            { key: 'expected_order_value', label: 'Typical order', align: 'right', fmt: inr },
            { key: 'overdue_outstanding', label: 'Overdue dues', align: 'right', fmt: (v) => (v ? <span className="neg">{inr(v)}</span> : '–') },
          ]} rows={d.rows} />
        </Card>
      )}</Async>

      <Async path="/sales/lapsed">{(d) => (
        <Card wide title="Customers who stopped or sharply reduced buying" priority="Must-have" kind="Insight" item="Customers who stopped or sharply reduced buying" note={d.rule}>
          <KpiRow>
            <Kpi label="Stopped buying" value={num(d.stopped)} tone="bad" />
            <Kpi label="Sharp drop" value={num(d.sharp_drop)} tone="warn" />
            <Kpi label="Sales lost vs previous 90 days" value={inr(d.lost_value_90d)} />
          </KpiRow>
          <DataTable filename="lapsed_customers.csv" columns={[
            { key: 'party', label: 'Customer' }, { key: 'status', label: 'Status', fmt: (v) => <span className={v === 'Stopped buying' ? 'tag bad' : 'tag warn'}>{v}</span> },
            { key: 'route', label: 'Route' }, { key: 'last_date', label: 'Last bill', fmt: dt },
            { key: 'last_90d', label: 'Last 90 d', align: 'right', fmt: inr }, { key: 'prev_90d', label: 'Prev 90 d', align: 'right', fmt: inr },
            { key: 'same_90d_last_year', label: 'Same 90 d LY', align: 'right', fmt: inr },
            { key: 'change_vs_prev_90d_pct', label: 'Change', align: 'right', fmt: spct }, { key: 'mobile', label: 'Mobile' },
          ]} rows={d.rows} />
        </Card>
      )}</Async>

      <Async path="/sales/churn">{(d) => (
        <Card wide title="Churn probability" priority="Important" kind="Prediction" item="Churn probability per customer"
          note={`Chance of no order in the next ${d.horizon_days} days. Method: ${d.method}.${d.holdout_auc ? ` Tested on the latest month it was not trained on: AUC ${d.holdout_auc.toFixed(2)} (0.5 = guessing, 1 = perfect).` : ''}`}>
          <KpiRow>{d.bands.map((b) => <Kpi key={b.risk_band} label={`${b.risk_band} risk`} value={`${b.customers} customers`} sub={`${inr(b.value_at_risk)} yearly sales at risk`} tone={b.risk_band === 'High' ? 'bad' : b.risk_band === 'Medium' ? 'warn' : ''} />)}</KpiRow>
          <DataTable filename="churn.csv" columns={[
            { key: 'party', label: 'Customer' }, { key: 'route', label: 'Route' },
            { key: 'churn_probability', label: 'Churn prob.', align: 'right', fmt: (v) => pct(v * 100, 0) },
            { key: 'risk_band', label: 'Band' }, { key: 'days_since_last', label: 'Days since', align: 'right', fmt: num },
            { key: 'usual_gap_days', label: 'Usual gap', align: 'right', fmt: days },
            { key: 'sales_365d', label: 'Sales 12 m', align: 'right', fmt: inr },
            { key: 'value_at_risk_365d', label: 'Value at risk', align: 'right', fmt: inr },
          ]} rows={d.rows} />
        </Card>
      )}</Async>

      <Async path="/sales/rfm" params={{ months }}>{(d) => (
        <Card wide title="Customer segments (recency, frequency, value)" priority="Important" kind="Data science"
          item="Customer segments by recency, frequency and value (last year, and last 3 years)"
          actions={<Select label="Window" value={months} onChange={setMonths} options={[{ value: '12', label: 'Last 1 year' }, { value: '36', label: 'Last 3 years' }]} />}
          note={d.window_note || 'Scores 1–5 by quintile. Champions: bought recently, often, a lot. At risk: used to buy a lot, not recently.'}>
          <div className="split">
            <BarChart data={d.segments.map((s) => ({ label: `${s.segment} (${s.customers})`, value: s.value_share_pct }))} fmt={(v) => pct(v)} />
            <DataTable filename={`rfm_${months}m.csv`} pageSize={10} columns={[
              { key: 'party', label: 'Customer' }, { key: 'segment', label: 'Segment' },
              { key: 'recency_days', label: 'Recency', align: 'right', fmt: days }, { key: 'frequency', label: 'Billing days', align: 'right', fmt: num },
              { key: 'value', label: 'Value', align: 'right', fmt: inr }, { key: 'R', label: 'R', align: 'right' }, { key: 'F', label: 'F', align: 'right' }, { key: 'M', label: 'M', align: 'right' },
            ]} rows={d.rows} />
          </div>
        </Card>
      )}</Async>

      <Async path="/sales/cross-sell">{(d) => (
        <Card wide title="Cross-sell gaps" priority="Important" kind="Recommendation" item="Cross-sell gaps: customers buying one oil but not the others" note={d.rule}>
          {d.summary && <BarChart data={d.summary.map((s) => ({ label: `${s.missing_family} (${s.customers} customers)`, value: s.potential_value, color: familyColor(s.missing_family) }))} fmt={(v) => inr(v)} />}
          <DataTable filename="cross_sell.csv" columns={[
            { key: 'party', label: 'Customer' }, { key: 'route', label: 'Route' }, { key: 'buys', label: 'Buys now' },
            { key: 'missing_family', label: 'Not buying' }, { key: 'route_penetration_pct', label: 'Route buys it', align: 'right', fmt: (v) => pct(v, 0) },
            { key: 'current_sales', label: 'Customer sales', align: 'right', fmt: inr }, { key: 'potential_value', label: 'Potential', align: 'right', fmt: inr },
          ]} rows={d.rows} />
        </Card>
      )}</Async>
    </div>
  )
}
