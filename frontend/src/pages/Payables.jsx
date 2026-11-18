import React, { useState } from 'react'
import { Async, Card, Kpi, KpiRow, NumberInput } from '../components/ui.jsx'
import DataTable from '../components/DataTable.jsx'
import { BarChart } from '../components/charts.jsx'
import { inr, num, pct, dt, days, useDebounced } from '../lib.js'

export default function PayablesPage() {
  const [cash, setCash] = useState('')
  const cashQ = useDebounced(cash)
  return (
    <div className="grid">
      <Async path="/payables/summary">{(d) => (
        <Card wide title="Payables and upcoming dues" priority="Must-have" kind="KPI" item="Payable, overdue, and dues in the next 7/15/30 days"
          note={`Current company. Dues are counted from ${dt(d.as_of)}.`}>
          <KpiRow>
            <Kpi label="Payable (open bills)" value={inr(d.payable)} sub={`Net of advances ${inr(d.net_payable)}`} />
            <Kpi label="Overdue" value={inr(d.overdue)} tone="bad" />
            <Kpi label="Due next 7 days" value={inr(d.due_next_7)} sub={`today ${inr(d.due_today)}`} />
            <Kpi label="Due next 15 days" value={inr(d.due_next_15)} />
            <Kpi label="Due next 30 days" value={inr(d.due_next_30)} />
          </KpiRow>
          <div className="split">
            <div>
              <h4>Ageing</h4>
              <BarChart data={d.ageing.map((a) => ({ label: a.bucket, value: a.amount, sub: `· ${num(a.bills)} bills` }))} fmt={(v) => inr(v)} />
            </div>
            <DataTable filename="payables_by_supplier.csv" pageSize={8} columns={[
              { key: 'supplier', label: 'Supplier' }, { key: 'payable', label: 'Payable', align: 'right', fmt: inr },
              { key: 'overdue', label: 'Overdue', align: 'right', fmt: inr }, { key: 'next_due', label: 'Earliest due', fmt: dt },
            ]} rows={d.by_supplier} />
          </div>
        </Card>
      )}</Async>

      <Async path="/payables/days-to-pay">{(d) => (
        <Card title="Days taken to pay suppliers" priority="Must-have" kind="KPI" item="Average days taken to pay suppliers, and open supplier advances">
          <KpiRow>
            <Kpi label="Average days to pay" value={days(d.overall_avg_days_to_pay)} />
            <Kpi label="Average delay beyond due" value={days(d.overall_avg_delay_days)} />
          </KpiRow>
          <DataTable filename="supplier_days_to_pay.csv" pageSize={10} columns={[
            { key: 'ledgername', label: 'Supplier' }, { key: 'avg_days_to_pay', label: 'Avg days', align: 'right', fmt: days },
            { key: 'avg_delay_days', label: 'Delay', align: 'right', fmt: days }, { key: 'terms_days', label: 'Terms', align: 'right', fmt: days },
            { key: 'paid_365d', label: 'Paid (12 m)', align: 'right', fmt: inr },
          ]} rows={d.rows} />
        </Card>
      )}</Async>

      <Async path="/payables/summary">{(d) => (
        <Card title="Open supplier advances" priority="Must-have" kind="KPI" item="Open supplier advances">
          <KpiRow><Kpi label="Advances paid, not yet adjusted" value={inr(d.advances)} /></KpiRow>
          <DataTable filename="supplier_advances.csv" pageSize={10} columns={[
            { key: 'supplier', label: 'Supplier' }, { key: 'advance', label: 'Advance', align: 'right', fmt: inr },
            { key: 'oldest', label: 'Oldest', fmt: dt }, { key: 'age_days', label: 'Age', align: 'right', fmt: days },
          ]} rows={d.advances_by_supplier} />
        </Card>
      )}</Async>

      <Async path="/payables/concentration">{(d) => (
        <Card wide title="Supplier concentration and dependence" priority="Important" kind="Insight" item="Supplier concentration and dependence"
          note={`Purchases in the last ${d.days} days (ex-GST). ${d.hhi_note}`}>
          <KpiRow>
            <Kpi label="Purchases" value={inr(d.total_purchases)} sub={`${d.suppliers} suppliers`} />
            <Kpi label="Largest supplier" value={pct(d.top1_share_pct, 0)} />
            <Kpi label="Top 3 suppliers" value={pct(d.top3_share_pct, 0)} />
            <Kpi label="Concentration (HHI)" value={num(d.hhi)} tone={d.hhi > 2500 ? 'bad' : d.hhi > 1500 ? 'warn' : 'good'} />
          </KpiRow>
          <div className="split">
            <BarChart data={d.rows.slice(0, 12).map((r) => ({ label: r.supplier, value: r.share_pct }))} fmt={(v) => pct(v)} labelWidth={240} />
            <DataTable filename="material_dependence.csv" pageSize={10} search={false} columns={[
              { key: 'material', label: 'Material' }, { key: 'suppliers', label: 'Suppliers', align: 'right' },
              { key: 'top_supplier', label: 'Main supplier' }, { key: 'top_supplier_share_pct', label: 'Share', align: 'right', fmt: (v) => pct(v, 0) },
              { key: 'dependence', label: 'Dependence', fmt: (v) => <span className={`tag ${v === 'Single source' ? 'bad' : v === 'High' ? 'warn' : 'good'}`}>{v}</span> },
            ]} rows={d.by_material} />
          </div>
        </Card>
      )}</Async>

      <Async path="/payables/schedule" params={{ cash: cashQ }}>{(d) => (
        <Card wide title="Suggested payment schedule for the week" priority="Important" kind="Recommendation"
          item="Suggested payment schedule for the week" note={d.rule}
          actions={<NumberInput label="Cash available ₹" value={cash} onChange={setCash} />}>
          <KpiRow>
            <Kpi label="Overdue + due in 7 days" value={inr(d.total_due)} />
            <Kpi label="Cash available" value={inr(d.cash_available)} sub={d.cash_source} />
            <Kpi label="Suggested to pay" value={inr(d.pay_this_week)} />
          </KpiRow>
          <DataTable filename="payment_schedule.csv" columns={[
            { key: 'supplier', label: 'Supplier' }, { key: 'billname', label: 'Bill' }, { key: 'duedate', label: 'Due', fmt: dt },
            { key: 'dpd', label: 'Days overdue', align: 'right', fmt: (v) => (v > 0 ? num(v) : `due in ${-v}`) },
            { key: 'pendingamount', label: 'Amount', align: 'right', fmt: inr },
            { key: 'critical_supplier', label: 'Critical', fmt: (v) => (v ? '★' : '') },
            { key: 'supplier_advance_held', label: 'Advance held', align: 'right', fmt: (v) => (v ? inr(v) : '–') },
            { key: 'action', label: 'Action', fmt: (v) => <span className={`tag ${v === 'Pay this week' ? 'good' : v.startsWith('Adjust') ? 'info' : 'warn'}`}>{v}</span> },
          ]} rows={d.rows} />
        </Card>
      )}</Async>
    </div>
  )
}
