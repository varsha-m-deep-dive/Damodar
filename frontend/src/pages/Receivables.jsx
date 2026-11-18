import React from 'react'
import { Async, Card, Kpi, KpiRow, Bullets } from '../components/ui.jsx'
import DataTable from '../components/DataTable.jsx'
import { BarChart, ColumnChart } from '../components/charts.jsx'
import { inr, num, pct, spct, dt, mon, days } from '../lib.js'

const bandTag = (v) => (v ? <span className={`tag ${v === 'High' ? 'bad' : v === 'Medium' ? 'warn' : 'good'}`}>{v}</span> : '–')

export default function ReceivablesPage() {
  return (
    <div className="grid">
      <Async path="/receivables/summary">{(d) => (
        <Card wide title="Outstanding, overdue and ageing" priority="Must-have" kind="KPI"
          item="Outstanding, overdue and ageing buckets – days, amount, pattern, risk; due today, last 7 days, last 30 days"
          note={`Current company only; days past due counted to ${dt(d.as_of)}. Bills with a placeholder due date use the bill date.`}>
          <KpiRow>
            <Kpi label="Outstanding (open bills)" value={inr(d.outstanding)} sub={`Advances ${inr(d.advances)} · net ${inr(d.net_outstanding)}`} />
            <Kpi label="Overdue" value={inr(d.overdue)} sub={`${pct(d.overdue_pct, 0)} of outstanding · ${d.customers_with_overdue} customers`} tone="bad" />
            <Kpi label="Due today" value={inr(d.due_today)} sub={`Due next 7 days ${inr(d.due_next_7_days)}`} />
            <Kpi label="Fell due in last 7 days" value={inr(d.became_due_last_7_days)} sub={`Last 30 days ${inr(d.became_due_last_30_days)}`} />
            <Kpi label="Avg days past due" value={days(d.avg_days_past_due_weighted)} sub="weighted by amount" />
          </KpiRow>
          <div className="split">
            <div>
              <h4>Ageing by days past due</h4>
              <BarChart data={d.ageing.map((a) => ({ label: a.bucket, value: a.amount, sub: `· ${num(a.bills)} bills`,
                color: a.bucket === 'Not due' ? '#9ca3af' : a.bucket.startsWith('180') || a.bucket.startsWith('91') ? '#dc2626' : '#f59e0b' }))} fmt={(v) => inr(v)} />
              <h4>Patterns and risk</h4>
              <Bullets items={d.patterns} />
            </div>
            <div>
              <h4>Overdue by route</h4>
              <DataTable filename="overdue_by_route.csv" pageSize={8} search={false} columns={[
                { key: 'route', label: 'Route' }, { key: 'outstanding', label: 'Outstanding', align: 'right', fmt: inr },
                { key: 'overdue', label: 'Overdue', align: 'right', fmt: inr }, { key: 'over_90', label: '> 90 days', align: 'right', fmt: inr },
              ]} rows={d.by_route} />
            </div>
          </div>
          <h4>By customer</h4>
          <DataTable filename="receivables_by_customer.csv" columns={[
            { key: 'customer', label: 'Customer' }, { key: 'route', label: 'Route' },
            { key: 'outstanding', label: 'Outstanding', align: 'right', fmt: inr }, { key: 'overdue', label: 'Overdue', align: 'right', fmt: inr },
            { key: 'overdue_share_pct', label: 'Overdue %', align: 'right', fmt: (v) => pct(v, 0) },
            { key: 'max_dpd', label: 'Oldest (days past due)', align: 'right', fmt: num }, { key: 'bills', label: 'Bills', align: 'right' },
          ]} rows={d.by_customer} />
        </Card>
      )}</Async>

      <Async path="/receivables/collections">{(d) => (
        <Card title="Collections vs billing this month" priority="Must-have" kind="KPI" item="Received collection vs total billing amount this month" note={d.note}>
          <KpiRow>
            <Kpi label={`Billed in ${mon(d.month)}`} value={inr(d.billing_this_month)} />
            <Kpi label="Collected" value={inr(d.collections_this_month)} />
            <Kpi label="Collected ÷ billed" value={pct(d.collection_ratio_pct, 0)} tone={d.collection_ratio_pct >= 100 ? 'good' : 'warn'} />
          </KpiRow>
          <ColumnChart categories={d.trend.map((t) => mon(t.month))} yFmt={(v) => inr(v, 0)}
            series={[{ name: 'Billing', color: '#9ca3af', values: d.trend.map((t) => t.billing) }, { name: 'Collections', color: '#2563eb', values: d.trend.map((t) => t.collections) }]} />
        </Card>
      )}</Async>

      <Async path="/receivables/expected">{(d) => (
        <Card title="Expected collections, next 4 weeks" priority="Must-have" kind="Forecast" item="Expected collections for the next 4 weeks" note={d.note}>
          <KpiRow>
            <Kpi label="Expected (probability-weighted)" value={inr(d.expected_total)} />
            <Kpi label="Bills falling in these weeks" value={inr(d.gross_total)} />
          </KpiRow>
          <ColumnChart categories={d.by_week.map((w) => `Wk ${w.week} (${dt(w.week_start).slice(0, -5)})`)} yFmt={(v) => inr(v, 0)}
            series={[{ name: 'Bills due', color: '#cbd5e1', values: d.by_week.map((w) => w.gross) }, { name: 'Expected', color: '#2563eb', values: d.by_week.map((w) => w.expected) }]} />
          <p className="note">Collection probability by days past due: {d.probabilities.map((p) => `≤${p.max_days_past_due > 9999 ? '∞' : p.max_days_past_due} d: ${Math.round(p.probability * 100)}%`).join(' · ')}</p>
        </Card>
      )}</Async>

      <Async path="/receivables/days-to-pay">{(d) => (
        <Card wide title="Days to pay vs agreed credit period" priority="Must-have" kind="KPI"
          item="Average days-to-pay vs agreed credit period, per customer (average ageing and deviation)" note={d.note}>
          <KpiRow>
            <Kpi label="Average days to pay" value={days(d.overall_avg_days_to_pay)} />
            <Kpi label="Average delay beyond due date" value={days(d.overall_avg_delay_days)} />
            <Kpi label="Customers with receipts" value={num(d.customers)} />
          </KpiRow>
          <DataTable filename="days_to_pay.csv" columns={[
            { key: 'ledgername', label: 'Customer' },
            { key: 'avg_days_to_pay', label: 'Avg days to pay', align: 'right', fmt: days },
            { key: 'median_days_to_pay', label: 'Median', align: 'right', fmt: days },
            { key: 'agreed_credit_days', label: 'Agreed', align: 'right', fmt: days },
            { key: 'deviation_days', label: 'Deviation', align: 'right', fmt: (v) => <span className={v > 0 ? 'neg' : 'pos'}>{v === null ? '–' : `${v > 0 ? '+' : ''}${v.toFixed(0)} d`}</span> },
            { key: 'paid_365d', label: 'Paid (12 m)', align: 'right', fmt: inr }, { key: 'settlements', label: 'Receipts', align: 'right', fmt: num },
          ]} rows={d.rows} />
        </Card>
      )}</Async>

      <Async path="/receivables/risk">{(d) => (
        <Card wide title="Payment-risk score" priority="Must-have" kind="Prediction" item="Payment-risk score per customer" note={d.method}>
          <KpiRow>{d.bands.map((b) => <Kpi key={b.band} label={`${b.band} risk`} value={`${b.customers} customers`} sub={`${inr(b.outstanding)} outstanding`} tone={b.band === 'High' ? 'bad' : b.band === 'Medium' ? 'warn' : 'good'} />)}</KpiRow>
          <DataTable filename="payment_risk.csv" columns={[
            { key: 'customer', label: 'Customer' }, { key: 'score', label: 'Score', align: 'right', fmt: (v) => num(v, 0) },
            { key: 'band', label: 'Band', fmt: bandTag }, { key: 'outstanding', label: 'Outstanding', align: 'right', fmt: inr },
            { key: 'over_60', label: '> 60 d past due', align: 'right', fmt: inr }, { key: 'avg_delay_days', label: 'Avg delay', align: 'right', fmt: days },
            { key: 'months_of_billing_outstanding', label: 'Months of billing o/s', align: 'right', fmt: (v) => num(v, 1) },
          ]} rows={d.rows} />
        </Card>
      )}</Async>

      <Async path="/receivables/priority">{(d) => (
        <Card wide title="Collections priority list" priority="Must-have" kind="Recommendation"
          item="Collections priority list, and customers overdue but still being supplied" note={d.rule}>
          <h4>Overdue but still being supplied ({d.overdue_but_supplied.length})</h4>
          <DataTable filename="overdue_but_supplied.csv" pageSize={8} columns={[
            { key: 'customer', label: 'Customer' }, { key: 'overdue', label: 'Overdue', align: 'right', fmt: inr },
            { key: 'max_dpd', label: 'Oldest (days)', align: 'right', fmt: num }, { key: 'supplied_value', label: 'Supplied recently', align: 'right', fmt: inr },
            { key: 'last_supply', label: 'Last supply', fmt: dt }, { key: 'band', label: 'Risk', fmt: bandTag }, { key: 'mobile', label: 'Mobile' },
          ]} rows={d.overdue_but_supplied} />
          <h4>Who to chase first</h4>
          <DataTable filename="collections_priority.csv" columns={[
            { key: 'customer', label: 'Customer' }, { key: 'route', label: 'Route' }, { key: 'overdue', label: 'Overdue', align: 'right', fmt: inr },
            { key: 'max_dpd', label: 'Oldest (days)', align: 'right', fmt: num }, { key: 'score', label: 'Risk score', align: 'right', fmt: (v) => num(v, 0) },
            { key: 'band', label: 'Band', fmt: bandTag }, { key: 'mobile', label: 'Mobile' },
          ]} rows={d.rows} />
        </Card>
      )}</Async>

      <Async path="/receivables/predicted-dates">{(d) => (
        <Card wide title="Predicted payment date per invoice" priority="Important" kind="Prediction" item="Predicted payment date per invoice"
          note={`${num(d.count)} open bills. Prediction = bill date + the customer's median days to pay; bills already past that day are rescheduled 1–4 weeks out depending on how late they are.`}>
          <DataTable filename="predicted_payment_dates.csv" columns={[
            { key: 'customer', label: 'Customer' }, { key: 'billname', label: 'Bill' }, { key: 'billdate', label: 'Bill date', fmt: dt },
            { key: 'duedate', label: 'Due', fmt: dt }, { key: 'pendingamount', label: 'Pending', align: 'right', fmt: inr },
            { key: 'predicted_date', label: 'Predicted payment', fmt: dt }, { key: 'probability', label: 'Chance in 4 wks', align: 'right', fmt: (v) => pct(v * 100, 0) },
            { key: 'basis', label: 'Basis' },
          ]} rows={d.rows} />
        </Card>
      )}</Async>

      <Async path="/receivables/credit">{(d) => (
        <Card wide title="Suggested credit limit and period" priority="Important" kind="Recommendation" item="Suggested credit limit and credit period per customer" note={d.method}>
          <DataTable filename="credit_suggestions.csv" columns={[
            { key: 'customer', label: 'Customer' }, { key: 'band', label: 'Risk', fmt: bandTag },
            { key: 'avg_monthly_billing', label: 'Monthly billing', align: 'right', fmt: inr },
            { key: 'p75_days_to_pay', label: 'Days to pay (p75)', align: 'right', fmt: days },
            { key: 'current_credit_days', label: 'Current days', align: 'right', fmt: days },
            { key: 'suggested_credit_days', label: 'Suggested days', align: 'right', fmt: days },
            { key: 'current_credit_limit', label: 'Current limit', align: 'right', fmt: (v) => (v ? inr(v) : 'none') },
            { key: 'suggested_credit_limit', label: 'Suggested limit', align: 'right', fmt: inr },
            { key: 'change', label: 'Action' },
          ]} rows={d.rows} />
        </Card>
      )}</Async>
    </div>
  )
}
