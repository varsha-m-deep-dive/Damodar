"""Login accounts, sessions and password reset.

Accounts live in a private Google Sheet (USERS_SHEET_ID, tab "users"). Without it (local
development) they live in backend/data/users.local.json. Passwords are stored only as scrypt
hashes. A login returns a signed token (HMAC-SHA256 with AUTH_SECRET) that the dashboard sends
as `Authorization: Bearer <token>`. Tokens carry a fingerprint of the password hash, so
changing or resetting a password signs out every other session of that user."""
import base64
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config, emailer, gsheets

COLUMNS = ["email", "name", "role", "password_hash", "active", "created_at", "last_login",
           "reset_hash", "reset_expires"]
ROLES = ("admin", "viewer")
MIN_PASSWORD_LEN = 8
INVITE_DAYS = 7
LOCAL_FILE = Path(__file__).resolve().parents[1] / "data" / "users.local.json"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AuthError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s):
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def norm_email(e):
    return (e or "").strip().lower()


# ------------------------------------------------------------------ passwords
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    n, r, p = 2 ** 14, 8, 1
    h = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt${n}${r}${p}${base64.b64encode(salt).decode()}${base64.b64encode(h).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, h = stored.split("$")
        if algo != "scrypt":
            return False
        calc = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r),
                              p=int(p), dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(h))
    except Exception:
        return False


def check_password_rules(password):
    if not password or len(password) < MIN_PASSWORD_LEN:
        raise AuthError(f"Password must be at least {MIN_PASSWORD_LEN} characters.")
    if len(password) > 200:
        raise AuthError("Password is too long.")


def _sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


# ------------------------------------------------------------------ tokens
_secret = None


def _key():
    global _secret
    if _secret is None:
        if config.AUTH_SECRET:
            _secret = config.AUTH_SECRET.encode()
        else:
            print("WARNING: AUTH_SECRET is not set; using a random key (everyone is signed out on restart).")
            _secret = secrets.token_bytes(32)
    return _secret


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _pv(user):
    """Password fingerprint: changes whenever the password changes."""
    return _sha(user.get("password_hash") or "")[:12]


def make_token(user) -> str:
    payload = {"sub": user["email"], "role": user["role"], "pv": _pv(user),
               "exp": int(time.time() + config.SESSION_HOURS * 3600)}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64(hmac.new(_key(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def user_from_token(token: str):
    """Return the public user dict for a valid token, else None."""
    try:
        body, sig = token.split(".")
        good = _b64(hmac.new(_key(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, good):
            return None
        payload = json.loads(_unb64(body))
        if payload.get("exp", 0) < time.time():
            return None
        user = store().get(payload.get("sub"))
        if not user or not user["active"] or _pv(user) != payload.get("pv"):
            return None
        return public(user)
    except Exception:
        return None


def public(user):
    return {"email": user["email"], "name": user.get("name") or "", "role": user["role"],
            "active": user["active"], "created_at": user.get("created_at") or "",
            "last_login": user.get("last_login") or "",
            "has_password": bool(user.get("password_hash"))}


# ------------------------------------------------------------------ user stores
def _row_to_user(r):
    u = {c: ("" if r.get(c) is None else str(r.get(c))) for c in COLUMNS}
    u["email"] = norm_email(u["email"])
    u["role"] = u["role"] if u["role"] in ROLES else "viewer"
    u["active"] = u["active"].strip().upper() not in ("FALSE", "0", "NO", "N")
    return u


def _user_to_row(u):
    return [("TRUE" if u.get(c) else "FALSE") if c == "active" else str(u.get(c) or "") for c in COLUMNS]


class _Store:
    """Common cache + lock. Subclasses implement _load() -> list[dict] and _save(user, is_new)."""
    TTL = 30

    def __init__(self):
        self._lock = threading.RLock()
        self._users = None
        self._at = 0

    def all(self):
        with self._lock:
            if self._users is None or time.time() - self._at > self.TTL:
                self._users = {u["email"]: u for u in map(_row_to_user, self._load()) if u["email"]}
                self._at = time.time()
            return dict(self._users)

    def get(self, email):
        return self.all().get(norm_email(email))

    def save(self, user):
        with self._lock:
            is_new = user["email"] not in self.all()
            self._save(user, is_new)
            self._users[user["email"]] = user


class SheetStore(_Store):
    name = "google-sheet"

    def _ws(self):
        sh = gsheets.open_sheet(config.USERS_SHEET_ID, "users")
        try:
            ws = sh.worksheet("users")
        except Exception:
            ws = sh.add_worksheet("users", rows=200, cols=len(COLUMNS))
        if ws.row_values(1)[:len(COLUMNS)] != COLUMNS:
            ws.update(values=[COLUMNS], range_name="A1")
        return ws

    def _load(self):
        ws = self._ws()
        self._ws_cache = ws
        values = ws.get_all_values()
        rows = values[1:]
        self._row_index = {}
        out = []
        for i, row in enumerate(rows, start=2):
            r = dict(zip(COLUMNS, row + [""] * (len(COLUMNS) - len(row))))
            e = norm_email(r["email"])
            if e:
                self._row_index[e] = i
                out.append(r)
        return out

    def _save(self, user, is_new):
        ws = getattr(self, "_ws_cache", None) or self._ws()
        if is_new:
            ws.append_row(_user_to_row(user), value_input_option="RAW")
            self._at = 0  # re-read to learn the new row number
        else:
            i = self._row_index[user["email"]]
            ws.update(values=[_user_to_row(user)], range_name=f"A{i}", raw=True)


class FileStore(_Store):
    name = "local-file"
    TTL = 0

    def _load(self):
        if not LOCAL_FILE.exists():
            return []
        return json.loads(LOCAL_FILE.read_text(encoding="utf-8"))

    def _save(self, user, is_new):
        users = self.all()
        users[user["email"]] = user
        rows = [dict(zip(COLUMNS, _user_to_row(u))) for u in users.values()]
        LOCAL_FILE.write_text(json.dumps(rows, indent=1), encoding="utf-8")


_store = None
_store_lock = threading.Lock()


def store() -> _Store:
    global _store
    with _store_lock:
        if _store is None:
            _store = SheetStore() if config.USERS_SHEET_ID else FileStore()
            _bootstrap(_store)
        return _store


def _bootstrap(s):
    """Create the first admin from ADMIN_EMAIL / ADMIN_PASSWORD when there is no admin yet."""
    email = norm_email(config.ADMIN_EMAIL)
    if not email:
        return
    users = s.all()
    if any(u["role"] == "admin" for u in users.values()):
        return
    u = users.get(email) or _new_user(email, "Admin", "admin")
    u["role"], u["active"] = "admin", True
    if config.ADMIN_PASSWORD and not u.get("password_hash"):
        u["password_hash"] = hash_password(config.ADMIN_PASSWORD)
    s.save(u)
    print(f"Created admin account {email}")


def _new_user(email, name, role):
    return {"email": email, "name": name or "", "role": role, "password_hash": "", "active": True,
            "created_at": _iso(_now()), "last_login": "", "reset_hash": "", "reset_expires": ""}


# ------------------------------------------------------------------ login rate limit
_fails = {}
_fails_lock = threading.Lock()
MAX_FAILS, FAIL_WINDOW = 8, 15 * 60


def _too_many(*keys):
    now = time.time()
    with _fails_lock:
        for k in keys:
            _fails[k] = [t for t in _fails.get(k, []) if now - t < FAIL_WINDOW]
            if len(_fails[k]) >= MAX_FAILS:
                return True
    return False


def _record_fail(*keys):
    with _fails_lock:
        for k in keys:
            _fails.setdefault(k, []).append(time.time())


# ------------------------------------------------------------------ actions
def login(email, password, ip="?"):
    email = norm_email(email)
    if _too_many(f"e:{email}", f"ip:{ip}"):
        raise AuthError("Too many failed attempts. Try again in 15 minutes.", 429)
    u = store().get(email)
    if not u or not u["active"] or not u.get("password_hash") or not verify_password(password or "", u["password_hash"]):
        _record_fail(f"e:{email}", f"ip:{ip}")
        raise AuthError("Wrong email or password.", 401)
    u = dict(u, last_login=_iso(_now()))
    try:
        store().save(u)
    except Exception as e:  # never block a login on a bookkeeping write
        print(f"could not record last_login: {e}")
    return {"token": make_token(u), "user": public(u), "expires_in_hours": config.SESSION_HOURS}


def change_password(email, current, new):
    u = store().get(email)
    if not u or not verify_password(current or "", u.get("password_hash") or ""):
        raise AuthError("Current password is wrong.", 401)
    check_password_rules(new)
    u = dict(u, password_hash=hash_password(new), reset_hash="", reset_expires="")
    store().save(u)
    return {"token": make_token(u), "user": public(u)}


def _issue_reset(u, minutes, base_url=None):
    token = secrets.token_urlsafe(32)
    u = dict(u, reset_hash=_sha(token), reset_expires=_iso(_now() + timedelta(minutes=minutes)))
    store().save(u)
    from urllib.parse import urlencode
    base = (config.FRONTEND_URL or base_url or "http://localhost:5173").rstrip("/")
    link = f"{base}/#reset?{urlencode({'email': u['email'], 'token': token})}"
    return u, link


def forgot_password(email, base_url=None):
    """Always answers the same way, so it cannot be used to find out which emails exist."""
    u = store().get(email)
    if u and u["active"]:
        u, link = _issue_reset(u, config.RESET_TOKEN_MINUTES, base_url)
        try:
            emailer.send_reset(u["email"], u.get("name"), link, config.RESET_TOKEN_MINUTES, invite=False)
        except Exception as e:
            print(f"reset email to {u['email']} failed: {e}")
    return {"ok": True, "message": "If that email has an account, a reset link has been sent."}


def reset_password(email, token, new):
    u = store().get(email)
    exp = _parse_iso(u.get("reset_expires")) if u else None
    if (not u or not u["active"] or not u.get("reset_hash") or not exp or exp < _now()
            or not hmac.compare_digest(u["reset_hash"], _sha(token or ""))):
        raise AuthError("This reset link is invalid or has expired. Ask for a new one.", 400)
    check_password_rules(new)
    u = dict(u, password_hash=hash_password(new), reset_hash="", reset_expires="")
    store().save(u)
    return {"token": make_token(u), "user": public(u)}


# ------------------------------------------------------------------ admin
def list_users():
    return {"users": sorted((public(u) for u in store().all().values()), key=lambda u: u["email"]),
            "store": store().name, "email_enabled": emailer.enabled()}


def create_user(email, name, role, password=None, send_invite=True, base_url=None):
    email = norm_email(email)
    if not EMAIL_RE.match(email):
        raise AuthError("Enter a valid email address.")
    if role not in ROLES:
        raise AuthError(f"Role must be one of {', '.join(ROLES)}.")
    if store().get(email):
        raise AuthError("A user with that email already exists.", 409)
    u = _new_user(email, name, role)
    if password:
        check_password_rules(password)
        u["password_hash"] = hash_password(password)
    store().save(u)
    out = {"user": public(u)}
    if not password:
        u, link = _issue_reset(u, INVITE_DAYS * 24 * 60, base_url)
        out["link"] = link
        out["emailed"] = False
        if send_invite and emailer.enabled():
            try:
                emailer.send_reset(email, name, link, INVITE_DAYS * 24 * 60, invite=True)
                out["emailed"] = True
            except Exception as e:
                out["email_error"] = str(e)
    return out


def update_user(email, actor_email, name=None, role=None, active=None):
    u = store().get(email)
    if not u:
        raise AuthError("No such user.", 404)
    u = dict(u)
    if name is not None:
        u["name"] = name
    if role is not None:
        if role not in ROLES:
            raise AuthError("Unknown role.")
        u["role"] = role
    if active is not None:
        u["active"] = bool(active)
    if norm_email(email) == norm_email(actor_email) and (u["role"] != "admin" or not u["active"]):
        raise AuthError("You cannot remove your own admin access.")
    store().save(u)
    return {"user": public(u)}


def admin_reset_link(email, send_email=False, base_url=None):
    u = store().get(email)
    if not u:
        raise AuthError("No such user.", 404)
    minutes = 24 * 60
    u, link = _issue_reset(u, minutes, base_url)
    out = {"link": link, "expires_hours": 24, "emailed": False}
    if send_email and emailer.enabled():
        try:
            emailer.send_reset(u["email"], u.get("name"), link, minutes, invite=not u.get("password_hash"))
            out["emailed"] = True
        except Exception as e:
            out["email_error"] = str(e)
    return out
