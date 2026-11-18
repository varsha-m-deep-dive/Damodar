import React, { useState } from 'react'
import { Async, Card, Kpi, KpiRow, Select } from '../components/ui.jsx'
import DataTable from '../components/DataTable.jsx'
import { ColumnChart, LineChart, BarChart } from '../components/charts.jsx'
import { num, kg, pct, spct, dt, mon, familyColor } from '../lib.js'

export default function ProductionPage() {
  const [days, setDays] = useState('90')
  return (
    <div className="grid">
      <Async path="/production/volume" params={{ days }}>{(d) => (
        <Card wide title="Packed volume by SKU" priority="Must-have" kind="KPI" item="Packed volume by SKU, daily and monthly"
          actions={<Select label="Period" value={days} onChange={setDays} options={[{ value: '30', label: '30 days' }, { value: '90', label: '90 days' }, { value: '365', label: '1 year' }]} />}
          note="Primary packing (bulk oil into pouches, cans and tins) counts towards volume. Boxing pouches into cartons is shown per SKU but not added again.">
          <KpiRow><Kpi label={`Oil packed, last ${d.days} days`} value={kg(d.total_kg)} /></KpiRow>
          <div className="split">
            <div>
              <h4>Daily kg packed</h4>
              <LineChart yFmt={kg} series={(d.families || []).map((f) => ({ name: f, color: familyColor(f), points: d.daily.map((r) => ({ x: r.date, y: r[f] || 0 })) }))} />
            </div>
            <div>
              <h4>Monthly kg packed</h4>
              {(() => {
                const months = [...new Set(d.monthly.map((r) => r.month))]
                return <ColumnChart categories={months.map(mon)} yFmt={kg}
                  series={(d.families || []).map((f) => ({ name: f, color: familyColor(f), values: months.map((m) => d.monthly.find((r) => r.month === m && r.oil_family === f)?.kg ?? 0) }))} />
              })()}
            </div>
          </div>
          <DataTable filename="packed_by_sku.csv" columns={[
            { key: 'stockitemname', label: 'SKU' }, { key: 'oil_family', label: 'Oil' }, { key: 'stage', label: 'Stage' },
            { key: 'units', label: 'Units', align: 'right', fmt: num }, { key: 'actualuom', label: 'Unit' },
            { key: 'kg', label: 'Oil kg', align: 'right', fmt: kg }, { key: 'days_packed', label: 'Days packed', align: 'right' },
          ]} rows={d.rows} />
        </Card>
      )}</Async>

      <Async path="/production/loss" params={{ days }}>{(d) => (
        <Card wide title="Packing loss" priority="Must-have" kind="KPI" item="Packing loss %: bulk oil consumed vs packed output" note={d.note}>
          <KpiRow>
            <Kpi label="Bulk oil consumed" value={kg(d.consumed_kg)} />
            <Kpi label="Oil in packed output" value={kg(d.output_kg)} />
            <Kpi label="Packing loss" value={pct(d.loss_pct, 2)} />
            <Kpi label="Vouchers booked at BOM standard" value={pct(d.standard_booking_pct, 0)} tone={d.standard_booking_pct > 60 ? 'warn' : ''} />
          </KpiRow>
          <div className="split">
            <DataTable filename="packing_loss_by_oil.csv" search={false} columns={[
              { key: 'family', label: 'Oil' }, { key: 'consumed_kg', label: 'Consumed', align: 'right', fmt: kg },
              { key: 'output_kg', label: 'Packed', align: 'right', fmt: kg }, { key: 'loss_pct', label: 'Loss', align: 'right', fmt: (v) => pct(v, 2) },
              { key: 'vouchers', label: 'Vouchers', align: 'right', fmt: num },
            ]} rows={d.by_family} />
            <LineChart zeroBase={false} yFmt={(v) => `${v.toFixed(2)}%`}
              series={[{ name: 'Daily loss %', color: '#dc2626', dots: true, points: d.daily.map((r) => ({ x: r.date, y: r.loss_pct })) }]} />
          </div>
        </Card>
      )}</Async>

      <Async path="/production/vs-sales" params={{ days }}>{(d) => (
        <Card wide title="Production vs sales gap by SKU" priority="Must-have" kind="Insight" item="Production vs sales gap by SKU" note={`${d.note} Window: ${dt(d.start)} – ${dt(d.as_of)} (${d.days} days).`}>
          <DataTable filename="production_vs_sales.csv" columns={[
            { key: 'stockitemname', label: 'SKU' }, { key: 'produced', label: 'Packed', align: 'right', fmt: num },
            { key: 'used_in_boxing', label: 'Used in boxes', align: 'right', fmt: num },
            { key: 'net_produced_for_sale', label: 'Net for sale', align: 'right', fmt: num }, { key: 'sold', label: 'Sold', align: 'right', fmt: num },
            { key: 'gap_units', label: 'Gap', align: 'right', fmt: (v) => <span className={v < 0 ? 'neg' : 'pos'}>{num(v)}</span> },
            { key: 'gap_pct_of_sales', label: 'Gap %', align: 'right', fmt: spct },
            { key: 'closing_stock', label: 'Stock now', align: 'right', fmt: num },
            { key: 'weeks_of_cover', label: 'Weeks cover', align: 'right', fmt: (v) => num(v, 1) },
            { key: 'flag', label: 'Flag', fmt: (v) => (v ? <span className="tag warn">{v}</span> : '') },
          ]} rows={d.rows} />
        </Card>
      )}</Async>

      <Async path="/production/plan">{(d) => (
        <Card wide title="Suggested weekly packing plan" priority="Important" kind="Recommendation" item="Suggested weekly packing plan from the sales forecast" note={d.method}>
          <KpiRow>{d.bulk_oil_by_family.map((b) => <Kpi key={b.oil_family} label={`${b.oil_family} oil needed`} value={kg(b.bulk_oil_kg)} />)}</KpiRow>
          <div className="split">
            <DataTable filename="packing_plan.csv" columns={[
              { key: 'oil_family', label: 'Oil' }, { key: 'stockitemname', label: 'SKU' },
              { key: 'forecast_units', label: 'Forecast', align: 'right', fmt: num }, { key: 'stock_units', label: 'In stock', align: 'right', fmt: num },
              { key: 'safety_units', label: 'Safety', align: 'right', fmt: num }, { key: 'to_pack_units', label: 'To pack', align: 'right', fmt: (v) => <b>{num(v)}</b> },
              { key: 'bulk_oil_kg', label: 'Oil kg', align: 'right', fmt: kg },
            ]} rows={d.rows} />
            <div>
              <h4>Packing materials and pouches needed</h4>
              <DataTable filename="packing_materials.csv" pageSize={12} search={false} columns={[
                { key: 'componentstockitemname', label: 'Material' }, { key: 'qty', label: 'Qty', align: 'right', fmt: (v) => num(v, 1) }, { key: 'uom', label: 'Unit' },
              ]} rows={d.materials} />
            </div>
          </div>
        </Card>
      )}</Async>

      <Async path="/production/packaging" params={{ days }}>{(d) => (
        <Card wide title="Packaging material used per unit packed" priority="Important" kind="KPI" item="Packaging material used per unit packed" note={d.note}>
          <BarChart data={d.rows.filter((r) => r.variance_pct !== null).slice(0, 12).map((r) => ({ label: `${r.component}`, value: r.variance_pct, color: r.variance_pct > 2 ? '#dc2626' : '#9ca3af' }))}
            fmt={(v) => spct(v)} labelWidth={260} />
          <DataTable filename="packaging_per_unit.csv" columns={[
            { key: 'stockitemname', label: 'Packed SKU' }, { key: 'component', label: 'Material' }, { key: 'uom', label: 'Unit' },
            { key: 'units_packed', label: 'Units packed', align: 'right', fmt: num },
            { key: 'std_per_unit', label: 'BOM per unit', align: 'right', fmt: (v) => num(v, 4) },
            { key: 'actual_per_unit', label: 'Actual per unit', align: 'right', fmt: (v) => num(v, 4) },
            { key: 'variance_pct', label: 'Variance', align: 'right', fmt: (v) => <span className={v > 2 ? 'neg' : ''}>{spct(v)}</span> },
          ]} rows={d.rows} />
        </Card>
      )}</Async>
    </div>
  )
}
