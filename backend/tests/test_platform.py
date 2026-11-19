"""Auth, delta refresh and Sheets flattening (no database or Google access needed)."""
import pandas as pd
import pytest

from app import auth, config, db, sheets_export


def test_password_hash_roundtrip():
    h = auth.hash_password("correct horse")
    assert auth.verify_password("correct horse", h)
    assert not auth.verify_password("wrong", h)


def test_token_tied_to_password(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "LOCAL_FILE", tmp_path / "users.json")
    monkeypatch.setattr(auth, "_store", None)
    monkeypatch.setattr(config, "ADMIN_EMAIL", None)
    auth.create_user("a@b.co", "A", "admin", password="password1")
    tok = auth.login("a@b.co", "password1")["token"]
    assert auth.user_from_token(tok)["email"] == "a@b.co"
    assert auth.user_from_token(tok + "x") is None
    auth.change_password("a@b.co", "password1", "password2")
    assert auth.user_from_token(tok) is None          # old sessions signed out
    with pytest.raises(auth.AuthError):
        auth.login("a@b.co", "password1")


def test_reset_link_single_use(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "LOCAL_FILE", tmp_path / "users.json")
    monkeypatch.setattr(auth, "_store", None)
    monkeypatch.setattr(config, "ADMIN_EMAIL", None)
    link = auth.create_user("v@b.co", "V", "viewer", send_invite=False)["link"]
    token = link.split("token=")[1]
    auth.reset_password("v@b.co", token, "newpassword")
    with pytest.raises(auth.AuthError):
        auth.reset_password("v@b.co", token, "another1pw")


def test_delta_merge(monkeypatch):
    calls = []

    def fake(sql, params):
        calls.append(params["start"])
        days = pd.date_range(params["start"], pd.Timestamp.today().normalize())
        return pd.DataFrame({"date": [d.date() for d in days], "v": len(calls)})

    monkeypatch.setattr(db, "query_df", fake)
    db._raw.pop("t", None)
    start = (pd.Timestamp.today() - pd.Timedelta(days=400)).date()
    a = db.delta_query("t", "SQL", {"start": start}, "date")
    b = db.delta_query("t", "SQL", {"start": start}, "date")
    assert len(a) == len(b) and not b.date.duplicated().any()
    assert pd.Timestamp(calls[1]) > pd.Timestamp(calls[0])        # second call is partial
    assert (b.v.head(10) == 1).all() and (b.v.tail(10) == 2).all()
    assert db.refresh_log["t"]["mode"] == "delta"


def test_flatten():
    pairs, tables = sheets_export.flatten({"total": 5, "kpi": {"a": 1}, "rows": [{"x": 1}, {"x": 2, "y": [1]}]})
    assert ("total", 5) in pairs and ("kpi.a", 1) in pairs
    name, cols, rows = tables[0]
    assert name == "rows" and cols == ["x", "y"] and rows[1] == [2, "[1]"]
