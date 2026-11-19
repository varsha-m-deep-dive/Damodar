"""Google Sheets access through a service account (gspread). Used for the login accounts
(USERS_SHEET_ID) and the KPI export (KPI_SHEET_ID)."""
import json
import threading

from . import config

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_client = None
_lock = threading.Lock()


class SheetsNotConfigured(RuntimeError):
    pass


def configured() -> bool:
    return bool(config.GOOGLE_SERVICE_ACCOUNT_JSON or config.GOOGLE_SERVICE_ACCOUNT_FILE)


def service_account_email():
    try:
        return _credentials_info().get("client_email")
    except Exception:
        return None


def _credentials_info() -> dict:
    if config.GOOGLE_SERVICE_ACCOUNT_JSON:
        raw = config.GOOGLE_SERVICE_ACCOUNT_JSON.strip()
        if not raw.startswith("{"):  # allow base64-encoded JSON
            import base64
            raw = base64.b64decode(raw).decode("utf-8")
        return json.loads(raw)
    if config.GOOGLE_SERVICE_ACCOUNT_FILE:
        with open(config.GOOGLE_SERVICE_ACCOUNT_FILE, encoding="utf-8") as f:
            return json.load(f)
    raise SheetsNotConfigured("Google service account not set (GOOGLE_SERVICE_ACCOUNT_JSON).")


def client():
    global _client
    with _lock:
        if _client is None:
            import gspread
            from google.oauth2.service_account import Credentials
            creds = Credentials.from_service_account_info(_credentials_info(), scopes=SCOPES)
            _client = gspread.authorize(creds)
        return _client


def open_sheet(sheet_id: str, what: str):
    if not sheet_id:
        raise SheetsNotConfigured(f"{what} spreadsheet id is not set.")
    try:
        return client().open_by_key(sheet_id)
    except Exception as e:
        if "PERMISSION_DENIED" in str(e) or "403" in str(e):
            raise RuntimeError(f"No access to the {what} spreadsheet. Share it (Editor) with "
                               f"{service_account_email()}.") from e
        raise
