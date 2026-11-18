import React from 'react'
import { Async, Card, Kpi, KpiRow } from '../components/ui.jsx'
import DataTable from '../components/DataTable.jsx'
import { LineChart } from '../components/charts.jsx'
import { inr, rs2, num, pct, spct, dt, mon, familyColor } from '../lib.js'

export default function MarginPage() {
  return (
    <div className="grid">
      <Async path="/margin/spread">{(d) => {
        const fams = [...new Set(d.rows.map((r) => r.oil_family))]
        return (
          <Card wide title="Gross spread per kg" priority="Must-have" kind="KPI"
            item="Gross spread per kg (sale realisation minus purchase rate), monthly" note={d.note}>
            <KpiRow>{d.last_3_months.map((s) => (
              <Kpi key={s.family} label={`${s.family}, last 3 months`} value={`${rs2(s.gross_spread_per_kg)}/kg`}
                sub={`${pct(s.spread_pct)} of ₹${num(s.realisation_per_kg)} realisation · buy ₹${num(s.purchase_rate_per_kg)}`} />
            ))}</KpiRow>
            <div className="split">
              <div>
                <h4>Spread ₹/kg by month</h4>
                <LineChart monthly zeroBase={false} yFmt={(v) => `₹${num(v)}`} refLines={[{ y: 0, label: '' }]}
                  series={fams.map((f) => ({ name: f, color: familyColor(f), dots: true,
                    points: d.rows.filter((r) => r.oil_family === f).map((r) => ({ x: r.month, y: r.gross_spread_per_kg })) }))} />
              </div>
              <DataTable filename="gross_spread.csv" pageSize={10} columns={[
                { key: 'month', label: 'Month', fmt: mon }, { key: 'oil_family', label: 'Oil' },
                { key: 'realisation_per_kg', label: 'Sale ₹/kg', align: 'right', fmt: rs2 },
                { key: 'purchase_rate_per_kg', label: 'Buy ₹/kg', align: 'right', fmt: rs2 },
                { key: 'gross_spread_per_kg', label: 'Spread', align: 'right', fmt: rs2 },
                { key: 'spread_pct_of_realisation', label: '%', align: 'right', fmt: pct },
              ]} rows={d.rows} />
            </div>
          </Card>
        )
      }}</Async>

      <Async path="/margin/orders">{(d) => (
        <Card wide title="Open sales-order book and fill rate" priority="Must-have" kind="KPI" item="Open sales-order book and order fill rate" note={d.note}>
          <KpiRow>
            <Kpi label="Open orders" value={num(d.open_orders)} sub={`${num(d.open_lines)} lines`} />
            <Kpi label="Open order value" value={inr(d.open_value)} />
            <Kpi label="Fill rate (quantity)" value={pct(d.fill_rate_qty_pct)} tone={d.fill_rate_qty_pct >= 95 ? 'good' : 'warn'} />
            <Kpi label="Orders filled in full" value={pct(d.orders_fully_filled_pct)} />
          </KpiRow>
          <DataTable filename="open_orders.csv" columns={[
            { key: 'voucherno', label: 'Order' }, { key: 'order_date', label: 'Date', fmt: dt }, { key: 'party', label: 'Customer' },
            { key: 'stockitemname', label: 'SKU' }, { key: 'ordered_qty', label: 'Ordered', align: 'right', fmt: num },
            { key: 'invoiced_qty', label: 'Invoiced', align: 'right', fmt: num }, { key: 'pending_qty', label: 'Pending', align: 'right', fmt: num },
            { key: 'pending_value', label: 'Pending ₹', align: 'right', fmt: inr }, { key: 'days_past_due', label: 'Days past due', align: 'right', fmt: num },
          ]} rows={d.open_rows} />
          <details><summary>Fill rate by SKU</summary>
            <DataTable filename="fill_rate_by_sku.csv" columns={[
              { key: 'stockitemname', label: 'SKU' }, { key: 'ordered', label: 'Ordered', align: 'right', fmt: num },
              { key: 'filled', label: 'Filled', align: 'right', fmt: num }, { key: 'fill_rate_pct', label: 'Fill rate', align: 'right', fmt: pct },
            ]} rows={d.by_sku} />
          </details>
        </Card>
      )}</Async>

      <Async path="/margin/supplier-rates">{(d) => (
        <Card wide title="Supplier rate comparison, same oil, same week" priority="Important" kind="Insight"
          item="Supplier rate comparison for the same oil in the same week" note={d.note}>
          <KpiRow><Kpi label={`Paid above cheapest supplier, last ${d.weeks} weeks`} value={inr(d.extra_cost_total)} tone="warn" /></KpiRow>
          <div className="split">
            <DataTable filename="supplier_premium.csv" pageSize={10} search={false} columns={[
              { key: 'oil_family', label: 'Oil' }, { key: 'supplier', label: 'Supplier' },
              { key: 'avg_premium_pct', label: 'Avg premium', align: 'right', fmt: spct },
              { key: 'extra_cost', label: 'Extra cost', align: 'right', fmt: inr }, { key: 'weeks', label: 'Weeks', align: 'right' },
            ]} rows={d.by_supplier} />
            <DataTable filename="supplier_rates_by_week.csv" pageSize={10} columns={[
              { key: 'week', label: 'Week of', fmt: dt }, { key: 'oil_family', label: 'Oil' }, { key: 'supplier', label: 'Supplier' },
              { key: 'kg', label: 'kg', align: 'right', fmt: num }, { key: 'rate', label: '₹/kg', align: 'right', fmt: rs2 },
              { key: 'premium_vs_cheapest_pct', label: 'vs cheapest', align: 'right', fmt: spct },
            ]} rows={d.rows} />
          </div>
        </Card>
      )}</Async>

      <Async path="/margin/buy-timing">{(d) => (
        <Card wide title="Purchase price forecast and buy-timing signal" priority="Important" kind="Forecast"
          item="Purchase price forecast and buy-timing signal (with external market prices)" note={d.note}>
          {!d.rows.length && <div className="empty">No bulk-oil purchases in the last year.</div>}
          <div className="small-multiples">
            {d.rows.map((r) => (
              <div key={r.family}>
                <h4>{r.family}: <span className={`tag ${r.signal.startsWith('Buy ahead') || r.signal.startsWith('Prices rising') ? 'warn' : r.signal.startsWith('Prices easing') ? 'good' : 'info'}`}>{r.signal}</span></h4>
                <p className="muted">Last ₹{num(r.last_rate, 2)}/kg · 8-wk avg ₹{num(r.avg_8_weeks, 2)} · trend {spct(r.weekly_trend_pct, 2)}/week · week-4 forecast ₹{num(r.forecast_week_4, 2)}
                  {r.market_price_latest ? ` · market ₹${num(r.market_price_latest, 2)} (ours ${spct(r.our_premium_vs_market_pct)})` : ''}</p>
                <LineChart height={190} zeroBase={false} yFmt={(v) => `₹${num(v)}`}
                  refLines={r.market_price_latest ? [{ y: r.market_price_latest, label: 'market' }] : []}
                  series={[
                    { name: 'Purchase rate', color: familyColor(r.family), points: r.history.map((h) => ({ x: h.week, y: h.rate })) },
                    { name: 'Forecast', color: '#111827', dashed: true, dots: true, points: [r.history[r.history.length - 1], ...r.forecast].map((h) => ({ x: h.week, y: h.rate })) },
                  ]} />
              </div>
            ))}
          </div>
        </Card>
      )}</Async>
    </div>
  )
}
