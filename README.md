# Damodara Oil Mill – KPI Dashboard

A React dashboard with a Python (FastAPI) backend that implements the 38 items on the KPI sheet. It reads the existing views in the **easyreport** Neon database and never writes to the database.

```
damodara-dashboard/
├── backend/                FastAPI + pandas
│   ├── app/
│   │   ├── config.py       every business assumption in one place
│   │   ├── sql.py          every SQL statement (read-only, against the views)
│   │   ├── loaders.py      loads + cleans data; company de-duplication; demo mode
│   │   ├── sku.py          pack size, oil family, kg per unit from item names
│   │   ├── kpi/            sales, customers, forecast, receivables, payables, cash, margin, production, control
│   │   ├── api.py          list of all /api routes
│   │   └── main.py         FastAPI app (also serves the built frontend)
│   ├── data/festivals.json, market_prices.csv
│   ├── tests/test_core.py
│   ├── requirements.txt, .env.example
└── frontend/               React 18 + Vite, charts drawn in SVG (no chart library)
    └── src/pages/          Sales, Receivables, Payables, Cash, Margin, Production, Control
```

## 1. Run it

Needs Python 3.10+ and Node.js 18+.

### Running it again (already set up)

You need **two terminals** (PowerShell), one for the backend and one for the frontend.

**Terminal 1: backend**

```powershell
cd C:\Users\Varsha\OneDrive\projects\damodara-dashboard\damodara-dashboard\backend
.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8000
```

**Terminal 2: frontend**

```powershell
cd C:\Users\Varsha\OneDrive\projects\damodara-dashboard\damodara-dashboard\frontend
npm run dev
```

Then open <http://localhost:5173>. To stop either server, press `Ctrl+C` in its terminal.

**If you see `uvicorn : The term 'uvicorn' is not recognized`**, the virtual environment isn't active. Every new terminal starts without it. Run `.venv\Scripts\Activate.ps1` first; the prompt then starts with `(.venv)`. Or skip activating and run it directly:

```powershell
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

**If `Activate.ps1` is blocked** ("running scripts is disabled on this system"), run this once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

### First-time setup

**Backend**

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows   (Mac/Linux: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env            # Mac/Linux: cp .env.example .env
#   -> open .env and put the database password in PGPASSWORD
uvicorn app.main:app --reload --port 8000
```

Check it: <http://localhost:8000/api/health> should show `"source": "postgres"` and the database name `easyreport`. <http://localhost:8000/docs> lists every endpoint.

**Frontend (development)**

```bash
cd frontend
npm install
npm run dev                       # opens http://localhost:5173, /api is proxied to port 8000
```

**Production (one server)**: `cd frontend && npm run build`, then restart uvicorn. FastAPI serves the built dashboard at <http://localhost:8000/>.

**Offline demo**: set `DEMO_EXCEL=path/to/Latest_views_10_Nov.xlsx` in `.env` to run on the Excel extract without a database. The extract has no `araptransbillwise`, so in demo mode payment-behaviour figures (days to pay, risk, expected collections, cash forecast) are rebuilt approximately from the outstanding views and are indicative only.

**Tests**: `cd backend && pytest -q` (set `DEMO_EXCEL` as well to call every endpoint end to end).

## 2. Where each KPI is and how it is calculated

| # | Item | Page / tab | Endpoint | How |
|---|---|---|---|---|
| 1 | Net sales today, month, year vs last year, year progress | Sales › Sales & realisation | `/sales/overview` | Sales Accounts ledgers net of trade discounts (`DISCOUNT A/C`), excluding GST, round-off and rent. Last year = same calendar dates. Progress = YTD ÷ last year's full year, with the share of the year elapsed. |
| 2 | Realisation by SKU type / oil | Sales › Sales & realisation | `/sales/realisation` | Net sales ÷ kg. kg = units × pack size (from the item name) × units per box (from `altquantity`) × 0.91 kg/L. |
| 3 | Mix by oil and pack size | Sales › Sales & realisation | `/sales/mix` | Value and volume shares; oil × pack heat map. |
| 4 | City, agent, route, zone | Sales › Routes & customers | `/sales/dimension` | Route = `partygroupl3`, city = `partygroupl4`, zone = `zone`, agent = `costcentreclass` (**empty in Tally today**; change `DIM_AGENT` if agents are kept elsewhere). |
| 5 | Top 20 customers, top-10 share | Sales › Routes & customers | `/sales/top-customers` | FYTD; cash/counter/UPI sales excluded from the ranking. |
| 6 | Sales forecast 4–12 weeks, with range, two assumptions | Sales › Forecast | `/sales/forecast` | Current level × the week-by-week seasonal pattern of past years. "Last year" uses 1 year and an 8-week level; "5 years" averages up to 5 years with a 13-week level. 80% band; backtest error shown. |
| 7 | Stopped / sharply reduced | Sales › Customer actions | `/sales/lapsed` | Stopped: ≥4 billing days in the last year and silent > 2× usual gap (min 45 days). Sharp drop: last 90 days < 50% of previous 90. |
| 8 | Call list | Sales › Customer actions | `/sales/call-list` | Days since last bill > 1.2 × the customer's median gap; shows overdue dues as a warning. |
| 9 | Outstanding, overdue, ageing, due today / 7 / 30 days | Receivables | `/receivables/summary` | `customeroutstanding`, current company. Placeholder due dates (1-Jan-2000) replaced by bill date. |
| 10 | Days to pay vs credit period | Receivables | `/receivables/days-to-pay` | `araptransbillwise`: receipt date − bill date of the bill it settles, amount-weighted; agreed period from the bill, else the customer master. |
| 11 | Collections vs billing this month | Receivables | `/receivables/collections` | Debtor lines: Sales vouchers (billing) vs Receipt vouchers (collections). |
| 12 | Payment-risk score | Receivables | `/receivables/risk` | 35% delay beyond terms + 30% share over 60 days + 20% balance vs monthly billing + 15% worsening delay. |
| 13 | Expected collections, 4 weeks | Receivables | `/receivables/expected` | Each open bill on its predicted date × collection probability by age (`COLLECTION_PROBABILITY` in config). |
| 14 | Priority list; overdue but still supplied | Receivables | `/receivables/priority` | Overdue × risk × age; "still supplied" = > 30 days past due and invoiced in the last 14 days. |
| 15 | Payable, overdue, dues 7/15/30 | Payables | `/payables/summary` | `supplierpayable`, current company. |
| 16 | Days to pay suppliers; open advances | Payables | `/payables/days-to-pay`, `/payables/summary` | As item 10, creditor side; advances = negative pending. |
| 17 | 13-week cash flow | Cash | `/cash/forecast` | Open AR (predicted) + forecast sales collected in the customers' actual payment-time pattern − open AP (due + usual delay) − purchases at run-rate. Opening balance and other weekly outflows are inputs. |
| 18 | Gross spread per kg, monthly | Margin | `/margin/spread` | Sales ₹/kg − bulk-oil purchase ₹/kg (both ex-GST), per oil per month. |
| 19 | Open order book, fill rate | Margin | `/margin/orders` | Sales Order lines matched to invoice lines by the order number on the invoice batch line. |
| 20 | Packed volume by SKU | Production | `/production/volume` | `production` view; primary packing (bulk oil → pouches/cans/tins) counted once; boxing shown separately. |
| 21 | Packing loss % | Production | `/production/loss` | Bulk oil consumed vs units × BOM oil per unit (matched by item GUID). |
| 22 | Production vs sales gap | Production | `/production/vs-sales` | Net packed for sale (packed − used inside boxes) vs units sold, with stock and weeks of cover. |
| 23 | RFM segments (1 and 3 years) | Sales › Customer actions | `/sales/rfm?months=12|36` | Quintile scores 1–5. |
| 24 | Churn probability | Sales › Customer actions | `/sales/churn` | Logistic regression trained on monthly snapshots of your own history; hold-out AUC shown. |
| 25 | Festival effect (1 and 5 years) | Sales › Forecast | `/sales/festivals` | kg in the 14 days before each festival vs the surrounding 10 weeks. Dates in `data/festivals.json`. |
| 26 | Price elasticity | Sales › Forecast | `/sales/elasticity` | log(kg) on log(fixed-weight price index) with month effects; implausible results flagged. |
| 27 | Cross-sell gaps | Sales › Customer actions | `/sales/cross-sell` | Oils a customer does not buy that ≥30% of their route does. |
| 28 | Returns / credit-note rate | Sales › Routes & customers | `/sales/returns` | Credit notes ÷ sales by customer and SKU. |
| 29 | Route productivity | Sales › Routes & customers | `/sales/route-productivity` | Customers served, invoices, average bill, kg per invoice, last 90 days. |
| 30 | Predicted payment date per invoice | Receivables | `/receivables/predicted-dates` | Bill date + customer's median days to pay; late bills rescheduled 1–4 weeks out. |
| 31 | Suggested credit limit and period | Receivables | `/receivables/credit` | Period covers the 75th-percentile days to pay (capped by risk); limit = monthly billing × period × risk factor. |
| 32 | Supplier concentration | Payables | `/payables/concentration` | Shares, HHI, and single-source materials. |
| 33 | Payment schedule for the week | Payables | `/payables/schedule` | Critical suppliers first, then most overdue; paid until cash available (default: expected collections this week) runs out; advances adjusted first. |
| 34 | Supplier rate comparison same week | Margin | `/margin/supplier-rates` | Each supplier's ₹/kg vs the cheapest that week; extra cost. |
| 35 | Purchase price forecast, buy timing | Margin | `/margin/buy-timing` | Holt trend on weekly purchase rates; compares with `data/market_prices.csv` (update it from SEA daily quotes). |
| 36 | Packaging material per unit | Production | `/production/packaging` | Actual vs BOM per unit, matched by GUID. |
| 37 | Weekly packing plan | Production | `/production/plan` | Next week's forecast kg × recent SKU mix + ½ week safety − stock in Tally. |
| 38 | Unusual entries | Control | `/control/*` | Rate outliers (robust z-score), back-dated vouchers (date far behind vouchers created around it, by master id), abnormal packing loss. |

## 3. Things to check on the first live run

1. **Company list**: `/api/meta` shows the companies found and which is "current". History KPIs combine all `DAMODARA OIL MILL…` companies; overlapping dates are taken only from the newest company that covers them, so nothing is counted twice.
2. **Dimension columns**: if route/city are kept in other customer ledger-group levels, change `DIM_ROUTE` / `DIM_CITY`.
3. **Bill-wise signs**: the code detects the sign of `araptransbillwise.billlineamount` automatically (billing must come out positive). If collections look inverted, check that view.
4. **Festival dates** in `data/festivals.json` were entered from general knowledge; verify the lunar dates and add new years.
5. **Performance**: the first request loads up to 5 years of sales (`HISTORY_YEARS`) and caches it for 15 minutes. If it is slow, lower `HISTORY_YEARS` or add an index on `date`/`companyname` in the underlying tables.

## 4. What the data showed while building this (worth fixing in Tally / the views)

- **vw_ledgerinvtxn** excludes `'PurchaseOrder'`/`'SalesOrder'` (no space), so orders are *not* excluded. The order-book KPI currently relies on this; if the view is fixed, point `sql.ORDERS` at a view that keeps orders.
- **vw_voucherheader** returns only cancelled *and* deleted vouchers (`<> false` should be `<> true`).
- **vw_invtrans vs vw_ledgerinvtxn** use opposite signs for `quantity`; `vw_invtrans.altquantity` has the opposite sign to its own `quantity`.
- **itembom** repeats components when an item was renamed; the dashboard de-duplicates and matches on GUIDs.
- **Packing loss**: 96% of packing vouchers consume oil exactly at the BOM standard (0.91 kg per litre), so real losses are not recorded. Entering actual oil issued makes this KPI meaningful.
- **Film rolls**: 1 L pouch film is used about 7% above the BOM standard (groundnut and Plus).
- **Credit limits** are not set in Tally for most customers; the dashboard suggests them.
- **Agent** data is empty (`costcentreclass`).

## 5. Security

The database password was shared in a chat. Keep it only in `backend/.env` (already in `.gitignore`), and consider resetting it in the Neon console. The API is read-only; put it behind your network or a login before exposing it outside the office.

## 6. Deployment

**DigitalOcean App Platform (full app: API + dashboard)**: uses the root `Dockerfile` and `.do/app.yaml`.
Create App → GitHub → `varsha-m-deep-dive/Damodar` (branch `main`), or `doctl apps create --spec .do/app.yaml`.
In the app's Settings → Environment Variables, set `PGPASSWORD` as an *encrypted* value. Check `https://<app>.ondigitalocean.app/api/health`.

**Vercel (dashboard only)**: New Project → import the repo → **Root Directory: `frontend`** (Vite is detected from `frontend/vercel.json`).
Add environment variable `VITE_API_BASE=https://<app>.ondigitalocean.app` (no trailing slash), then deploy. The browser calls the DigitalOcean API directly (CORS is open for GET).
The Python backend is not run on Vercel: pandas/scikit-learn exceed Vercel's function size limit and the in-memory cache needs a long-running server.

Both URLs are public, and the API has no login. See section 5.
