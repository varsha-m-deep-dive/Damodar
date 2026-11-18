import React, { useState } from 'react'
import { Async, Card, Kpi, KpiRow, NumberInput, Select, Bullets } from '../components/ui.jsx'
import DataTable from '../components/DataTable.jsx'
import { ColumnChart, LineChart } from '../components/charts.jsx'
import { inr, dt, useDebounced } from '../lib.js'

export default function CashPage() {
  const [opening, setOpening] = useState('0')
  const [other, setOther] = useState('0')
  const [scenario, setScenario] = useState('last_year')
  const o = useDebounced(opening), x = useDebounced(other)
  return (
    <div className="grid">
      <Async path="/cash/forecast" params={{ opening: o, other: x, scenario }}>{(d) => (
        <Card wide title="13-week cash-flow forecast" priority="Must-have" kind="Forecast"
          item="13-week cash-flow forecast: predicted collections minus supplier dues"
          actions={<>
            <NumberInput label="Opening cash & bank ₹" value={opening} onChange={setOpening} />
            <NumberInput label="Other outflows / week ₹" value={other} onChange={setOther} />
            <Select label="Sales assumption" value={scenario} onChange={setScenario}
              options={[{ value: 'last_year', label: "Last year's pattern" }, { value: 'five_year', label: 'Up to 5 years' }]} />
          </>}>
          <KpiRow>
            <Kpi label="Cash in, 13 weeks" value={inr(d.total_in)} />
            <Kpi label="Cash out, 13 weeks" value={inr(d.total_out)} />
            <Kpi label="Net" value={inr(d.total_in - d.total_out)} tone={d.total_in - d.total_out >= 0 ? 'good' : 'bad'} />
            <Kpi label={`Lowest balance (week ${d.lowest_week})`} value={inr(d.lowest_balance)} tone={d.lowest_balance < 0 ? 'bad' : ''} />
          </KpiRow>
          <div className="split">
            <div>
              <h4>Weekly inflows and outflows</h4>
              <ColumnChart categories={d.rows.map((r) => `W${r.week}`)} yFmt={(v) => inr(v, 0)}
                series={[
                  { name: 'Collections', color: '#2563eb', values: d.rows.map((r) => r.collections_open_bills + r.collections_new_sales) },
                  { name: 'Payments', color: '#f97316', values: d.rows.map((r) => -(r.supplier_dues_open_bills + r.supplier_new_purchases + r.other_outflows)) },
                ]} />
            </div>
            <div>
              <h4>Closing cash balance</h4>
              <LineChart zeroBase={false} yFmt={(v) => inr(v, 0)} refLines={[{ y: 0, label: 'zero' }]}
                series={[{ name: 'Closing cash', color: '#111827', dots: true, points: d.rows.map((r) => ({ x: r.week_start, y: r.closing_cash })) }]} />
            </div>
          </div>
          <DataTable filename="cash_forecast_13w.csv" pageSize={13} search={false} columns={[
            { key: 'week', label: 'Week' }, { key: 'week_start', label: 'Starts', fmt: dt },
            { key: 'collections_open_bills', label: 'From open bills', align: 'right', fmt: inr },
            { key: 'collections_new_sales', label: 'From new sales', align: 'right', fmt: inr },
            { key: 'supplier_dues_open_bills', label: 'Supplier bills', align: 'right', fmt: inr },
            { key: 'supplier_new_purchases', label: 'New purchases', align: 'right', fmt: inr },
            { key: 'other_outflows', label: 'Other', align: 'right', fmt: inr },
            { key: 'net', label: 'Net', align: 'right', fmt: (v) => <span className={v < 0 ? 'neg' : 'pos'}>{inr(v)}</span> },
            { key: 'closing_cash', label: 'Closing cash', align: 'right', fmt: inr },
          ]} rows={d.rows} />
          <h4>Assumptions</h4>
          <Bullets items={d.assumptions} />
        </Card>
      )}</Async>
    </div>
  )
}
