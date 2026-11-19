"""Central configuration. Everything that is a business assumption lives here so it
can be reviewed and changed in one place. Values can be overridden with environment
variables (see .env.example)."""
import os
from pathlib import Path

try:  # optional: load backend/.env when python-dotenv is installed
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except Exception:  # pragma: no cover
    pass


def _env(name, default=None, cast=str):
    v = os.getenv(name)
    if v is None or v == "":
        return default
    try:
        return cast(v)
    except Exception:
        return default


# ---------------------------------------------------------------- database
PG = {
    "host": _env("PGHOST"),
    "dbname": _env("PGDATABASE"),
    "user": _env("PGUSER"),
    "password": _env("PGPASSWORD"),
    "sslmode": _env("PGSSLMODE", "require"),
    "channel_binding": _env("PGCHANNELBINDING", "prefer"),
}
PG_SCHEMA = _env("PGSCHEMA", "public")          # schema that holds the views
CACHE_TTL_SECONDS = _env("CACHE_TTL_SECONDS", 900, int)

# Delta refresh: after the first full load, history tables re-read only recent rows.
DELTA_ENABLED = _env("DELTA_ENABLED", "1") not in ("0", "false", "False", "no")
DELTA_OVERLAP_DAYS = _env("DELTA_OVERLAP_DAYS", 45, int)        # recent days re-read every refresh
DELTA_FULL_RELOAD_HOURS = _env("DELTA_FULL_RELOAD_HOURS", 24, float)  # full reload at least this often

# ---------------------------------------------------------------- authentication
AUTH_SECRET = _env("AUTH_SECRET")                 # long random string; signs login tokens
AUTH_REQUIRED = _env("AUTH_REQUIRED", "1") not in ("0", "false", "False", "no")
SESSION_HOURS = _env("SESSION_HOURS", 12, float)
RESET_TOKEN_MINUTES = _env("RESET_TOKEN_MINUTES", 60, int)
ADMIN_EMAIL = _env("ADMIN_EMAIL")                 # first admin, created if the users sheet is empty
ADMIN_PASSWORD = _env("ADMIN_PASSWORD")
FRONTEND_URL = (_env("FRONTEND_URL", "http://localhost:5173") or "").rstrip("/")  # for links in emails
ALLOWED_ORIGINS = [o.strip().rstrip("/") for o in (_env("ALLOWED_ORIGINS", "*") or "*").split(",") if o.strip()]

# ---------------------------------------------------------------- Google Sheets
# Service-account key: the whole JSON (GOOGLE_SERVICE_ACCOUNT_JSON) or a path to the file
# (GOOGLE_SERVICE_ACCOUNT_FILE). Share each spreadsheet with the service account's email.
GOOGLE_SERVICE_ACCOUNT_JSON = _env("GOOGLE_SERVICE_ACCOUNT_JSON")
GOOGLE_SERVICE_ACCOUNT_FILE = _env("GOOGLE_SERVICE_ACCOUNT_FILE")
USERS_SHEET_ID = _env("USERS_SHEET_ID")           # private spreadsheet holding login accounts
KPI_SHEET_ID = _env("KPI_SHEET_ID")               # spreadsheet that receives the KPI export
SHEETS_EXPORT_INTERVAL_MINUTES = _env("SHEETS_EXPORT_INTERVAL_MINUTES", 0, int)  # 0 = only on demand

# ---------------------------------------------------------------- email (password reset)
# EMAIL_PROVIDER: "smtp" (Gmail with an App Password) or "resend" (HTTPS API; use this if
# the host blocks SMTP ports). If neither is configured, admins can copy reset links instead.
EMAIL_PROVIDER = (_env("EMAIL_PROVIDER", "smtp") or "smtp").lower()
SMTP_HOST = _env("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = _env("SMTP_PORT", 465, int)
SMTP_USER = _env("SMTP_USER")
SMTP_PASSWORD = _env("SMTP_PASSWORD")
EMAIL_FROM = _env("EMAIL_FROM") or SMTP_USER
RESEND_API_KEY = _env("RESEND_API_KEY")

# Offline demo: point at the Excel extract (Latest_views_*.xlsx) to run without a DB
DEMO_EXCEL = _env("DEMO_EXCEL")

# ---------------------------------------------------------------- companies
# Tally keeps one company per financial year. History KPIs use every company whose
# name matches this pattern; balances (outstanding, payables, stock, BOM) use only the
# current company. Gayathri Edible Oil Industries is excluded by default.
COMPANY_INCLUDE_REGEX = _env("COMPANY_INCLUDE_REGEX", r"^DAMODARA OIL MILL")
CURRENT_COMPANY = _env("CURRENT_COMPANY")        # blank = latest company with sales
HISTORY_YEARS = _env("HISTORY_YEARS", 5, int)     # how far back history loaders read

# ---------------------------------------------------------------- dimensions
# Field mapping found in the data: partygroupl3 = route ("ROUTE 1".."ROUTE 14"),
# partygroupl4 = town/city, costcentreclass = agent (empty in Tally today).
DIM_ROUTE = _env("DIM_ROUTE", "partygroupl3")
DIM_CITY = _env("DIM_CITY", "partygroupl4")
DIM_AGENT = _env("DIM_AGENT", "costcentreclass")
DIM_ZONE = _env("DIM_ZONE", "zone")

# Customers treated as walk-in cash sales (excluded from customer analytics)
CASH_PARTY_GROUPS = {"Cash-in-Hand"}
CASH_PARTY_NAME_PATTERN = r"^(?:CASH|COUNTER|UPI)\b|COUNTER CUSTOMER|CASH SALES|PHONEPE|GOOGLE ?PAY|PAYTM"

# ---------------------------------------------------------------- sales definitions
SALES_LEDGER_GROUP = "Sales Accounts"
# Ledgers that reduce net sales (trade discounts booked in Indirect Expenses)
DISCOUNT_LEDGERS = {"DISCOUNT A/C", "1% Credit Note"}
INCLUDE_DISCOUNTS_IN_NET_SALES = _env("INCLUDE_DISCOUNTS_IN_NET_SALES", "true").lower() == "true"
# Non-product income booked as sales (excluded)
EXCLUDE_SALES_LEDGER_PATTERNS = [r"RENT"]
EXCLUDE_VOUCHER_TYPE_PATTERNS = [r"RENT"]

# Oil family from stock group (stockgroupl1); fallback is keyword matching on the item
OIL_FAMILY_BY_GROUP = {
    "GROUNDNUT DOUBLE FILTERED OIL": "Groundnut",
    "SUNFLOWER REFINED OIL": "Sunflower",
    "RICEBRAN REFINED OIL": "Rice bran",
    "PLUS VEGETABLE COOKING OIL": "Vegetable (blended)",
    "PLUS BLENDED OIL": "Vegetable (blended)",
    "POOJA OIL": "Pooja oil",
    "GROUNDNUT SEED": "Groundnut seed",
}
OIL_FAMILY_KEYWORDS = [
    ("GROUND NUT", "Groundnut"), ("GROUNDNUT", "Groundnut"), ("G.N", "Groundnut"),
    ("SUNFLOWER", "Sunflower"), ("S.F", "Sunflower"),
    ("RICEBRAN", "Rice bran"), ("RICE BRAN", "Rice bran"), ("SURYA", "Rice bran"),
    ("PLUS", "Vegetable (blended)"), ("VEGETABLE", "Vegetable (blended)"),
    ("POOJA", "Pooja oil"),
]
FORECAST_FAMILIES = ["Groundnut", "Sunflower", "Rice bran", "Vegetable (blended)"]

# Litres to kg. Tally's BOM books 0.91 kg of oil per 1 L pouch (voucher 2035: 23,200 L -> 21,112 kg)
KG_PER_LITRE = _env("KG_PER_LITRE", 0.91, float)
# Default units per box when altquantity is missing, keyed by inner pack size in litres/kg
DEFAULT_UNITS_PER_BOX = {0.5: 32, 1.0: 16, 5.0: 4}
DEFAULT_UNITS_PER_BOX_PET = {0.5: 30, 1.0: 15}
GST_BILLING_FACTOR = _env("GST_BILLING_FACTOR", 1.05, float)  # net sales -> invoice value

# ---------------------------------------------------------------- receivables / payables
OVERDUE_BUT_SUPPLIED_MIN_DAYS = _env("OVERDUE_BUT_SUPPLIED_MIN_DAYS", 30, int)
OVERDUE_BUT_SUPPLIED_LOOKBACK_DAYS = _env("OVERDUE_BUT_SUPPLIED_LOOKBACK_DAYS", 14, int)
# Probability that an open bill is collected within the next 4 weeks, by days past due.
# Starting points only; the dashboard shows them so they can be tuned.
COLLECTION_PROBABILITY = [  # (max days past due, probability)
    (0, 0.95), (30, 0.85), (60, 0.70), (90, 0.55), (180, 0.35), (10**6, 0.10)]
CREDIT_PERIOD_STEPS = [7, 15, 21, 30, 45, 60]
CREDIT_LIMIT_RISK_MULTIPLIER = {"Low": 1.2, "Medium": 1.0, "High": 0.6}

# ---------------------------------------------------------------- analytics
REORDER_GAP_TOLERANCE = 1.2      # call list: days since last bill > 1.2 x usual gap
MIN_INVOICES_FOR_GAP = 3
STOPPED_MIN_PRIOR_INVOICES = 4
SHARP_DROP_RATIO = 0.5           # last 90 days < 50% of previous 90 days
CHURN_HORIZON_DAYS = 90
BACKDATED_TOLERANCE_DAYS = _env("BACKDATED_TOLERANCE_DAYS", 7, int)
OUTLIER_MAD_K = 4.0              # rate outlier threshold in robust z-score units

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
