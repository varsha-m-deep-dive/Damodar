import React from 'react'
import { Async, Card, Kpi, KpiRow } from '../components/ui.jsx'
import DataTable from '../components/DataTable.jsx'
import { BarChart } from '../components/charts.jsx'
import { inr, rs2, num, kg, pct, spct, dt } from '../lib.js'

export default function ControlPage() {
  return (
    <div className="grid">
      <Async path="/control/rate-outliers">{(d) => (
        <Card wide title="Rate outliers" priority="Important" kind="Anomaly detection" item="Unusual entries: rate outliers" note={d.rule}>
          <KpiRow><Kpi label="Lines flagged (last 90 days)" value={num(d.count)} tone={d.count ? 'warn' : 'good'} /></KpiRow>
          <DataTable filename="rate_outliers.csv" columns={[
            { key: 'type', label: 'Type' }, { key: 'date', label: 'Date', fmt: dt }, { key: 'voucherno', label: 'Voucher' },
            { key: 'party', label: 'Party' }, { key: 'item', label: 'Item' }, { key: 'quantity', label: 'Qty', align: 'right', fmt: num },
            { key: 'rate', label: 'Rate', align: 'right', fmt: rs2 }, { key: 'typical_rate', label: 'Typical', align: 'right', fmt: rs2 },
            { key: 'deviation_pct', label: 'Deviation', align: 'right', fmt: spct }, { key: 'value_impact', label: 'Impact', align: 'right', fmt: inr },
          ]} rows={d.rows} />
        </Card>
      )}</Async>

      <Async path="/control/backdated">{(d) => (
        <Card wide title="Back-dated vouchers" priority="Important" kind="Anomaly detection" item="Unusual entries: back-dated vouchers" note={d.rule}>
          <KpiRow><Kpi label="Vouchers flagged" value={num(d.count)} tone={d.count ? 'warn' : 'good'} /></KpiRow>
          <div className="split">
            <div>
              <h4>By user</h4>
              <BarChart data={(d.by_user || []).map((u) => ({ label: u.enteredby, value: u.vouchers, sub: `· avg ${num(u.avg_days)} days` }))} fmt={num} />
            </div>
            <DataTable filename="backdated_vouchers.csv" pageSize={10} columns={[
              { key: 'date', label: 'Voucher date', fmt: dt }, { key: 'entered_around', label: 'Entered around', fmt: dt },
              { key: 'days_backdated', label: 'Days', align: 'right', fmt: num }, { key: 'vouchertypename', label: 'Type' },
              { key: 'voucherno', label: 'No.' }, { key: 'partyledgername', label: 'Party' }, { key: 'enteredby', label: 'User' },
            ]} rows={d.rows} />
          </div>
        </Card>
      )}</Async>

      <Async path="/control/packing-loss">{(d) => (
        <Card wide title="Abnormal packing loss" priority="Important" kind="Anomaly detection" item="Unusual entries: abnormal packing loss" note={d.rule}>
          <KpiRow><Kpi label="Packing vouchers flagged" value={num(d.count)} tone={d.count ? 'warn' : 'good'} /></KpiRow>
          <DataTable filename="abnormal_packing_loss.csv" columns={[
            { key: 'date', label: 'Date', fmt: dt }, { key: 'voucherno', label: 'Voucher' }, { key: 'family', label: 'Oil' },
            { key: 'output_item', label: 'Packed' }, { key: 'consumed_kg', label: 'Consumed', align: 'right', fmt: kg },
            { key: 'output_kg', label: 'Output', align: 'right', fmt: kg }, { key: 'loss_kg', label: 'Loss kg', align: 'right', fmt: (v) => num(v, 1) },
            { key: 'loss_pct', label: 'Loss %', align: 'right', fmt: (v) => pct(v, 2) }, { key: 'enteredby', label: 'User' },
          ]} rows={d.rows} />
        </Card>
      )}</Async>
    </div>
  )
}
